#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check a fresh-eyes review report against the evidence format, and optionally
replay its evidence.

The report format is the one mandated by the `fresh-eyes-review` skill. Every
finding is a block headed `### F<n> ...` that must carry:

    位置         file:line
    复现         one command that anyone can copy and run
    实测         the observed output, OR
    证据文件      path to a file holding the raw output

A finding without a location, a reproduction command and either inline output or
an evidence file is not evidence, it is an opinion, and must be sent back.

WHY THE EVIDENCE FILE EXISTS
----------------------------
Checking that a report merely *mentions* a command and an output proves nothing:
a model can run nothing and write a plausible transcript. That failure is not
hypothetical -- it is documented in the wild (see andrewstellman/quality-playbook,
whose gate gained a replay step after a model wrote its own fabricated expected
output into an evidence file). So the report may point at a file, and `--replay`
re-runs the command and diffs the real output against that file.

`--replay` executes the commands written in the report. It has a hand-slip
deny-list and a timeout. **It is not a sandbox.** Only replay a report you have
read, in a workspace you are willing to have those commands touch.

Usage:
    python check_review_report.py [--strict] <report.md>
    python check_review_report.py --replay [--workdir DIR] [--timeout SEC] <report.md>

Exit codes:
    0  every finding carries usable evidence; under --replay, every replay matched
    1  at least one finding is missing evidence, or a replay differed / was refused
    2  usage, read, or encoding error -- the report could not be read at all

`--strict` also fails on warnings (missing severity, location without a line
number, ...). Default keeps warnings advisory.

Evidence file format (mandatory when the field is present):

    [exit code: 0]
    <raw stdout+stderr of the reproduction command, verbatim>

Volatile output (timestamps, durations, uuids, temp paths, pids, addresses) is
normalized before the diff. If your command's output is volatile in some other
way, stabilize it in the command itself (e.g. pipe through sed/grep) rather than
expecting the gate to guess.

Conservative on purpose: Python 3.8 syntax only, no f-string with backslashes or
nested same quotes, so it also runs on the older interpreters other machines on
the team happen to have.

Regression suite: scripts/test_check_review_report.py
"""

import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


class ReadError(Exception):
    """The report could not be read (missing, unreadable, unknown encoding)."""


# --- field labels -----------------------------------------------------------

FIELD_KEYS = (
    ("location", ("位置", "文件路径", "文件", "location")),
    ("repro", ("复现", "复现步骤", "reproduce", "repro")),
    ("evidence", ("证据文件", "证据", "evidence file", "evidence")),
    ("observed", ("实测", "实测输出", "observed", "output")),
)

FIELD_NAMES = {
    "location": "位置",
    "repro": "复现",
    "evidence": "证据文件",
    "observed": "实测",
}

EMPTY_VALUES = (
    "无", "n/a", "na", "none", "-", "—", "不适用", "略", "待补", "未提供",
    "见上", "同上", "同前", "todo", "tbd", "?",
)

CANNOT_RUN_MARKERS = (
    "未能执行", "无法执行", "cannot run", "could not run", "not run",
    "没有执行", "未运行",
)

EXIT_MARKER_RE = re.compile(r"^\[exit code:\s*(-?\d+)\]\s*$")

# --- syntax ----------------------------------------------------------------

HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]*(.*)$")
FENCE_RE = re.compile(r"^[ \t]{0,3}(?:```|~~~)")
BLOCK_HEAD_RE = re.compile(r"^F(\d+)\b(.*)$")

LABEL_RE = re.compile(
    r"^[ \t]*(?:[-*+\u2022][ \t]+)?"
    r"[*_`\"']{0,3}[ \t]*"
    r"(?P<label>[^:*:\uFF1A`*_'\"]{1,14}?)"
    r"[ \t]*[*_`\"']{0,3}[ \t]*"
    r"[:\uFF1A][ \t]*(?P<value>.*)$"
)

NONE_LINE_RE = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?"
    r"(?:\u5ba1\u5b8c\u4e86[\u3002\uff0c,.]?[ \t]*)?"
    r"(?:\u672c?\u62a5\u544a[\uff1a:]?[ \t]*)?"
    r"(\u672a\u53d1\u73b0\u95ee\u9898|\u6ca1\u6709\u95ee\u9898|\u65e0\u95ee\u9898"
    r"|no findings|no issues)"
    r"[\u3002.\uff01!]?[ \t]*$",
    re.IGNORECASE,
)

PATHISH_RE = re.compile(r"[A-Za-z0-9_\-./\\]+\.[A-Za-z0-9]{1,8}|[/\\]")
TECHISH_RE = re.compile(r"[A-Za-z0-9_\-./\\]{3,}")
LINE_NO_RE = re.compile(r":\d+")
# Severity must be asserted with a value, not merely mentioned: a heading that
# says "没写严重度的问题" does not declare one.
SEVERITY_RE = re.compile(r"(\u4e25\u91cd\u5ea6|severity)[ \t]*[:\uff1a][ \t]*\S", re.IGNORECASE)

# --- replay safety ----------------------------------------------------------

# A hand-slip filter, NOT a security boundary. It cannot stop a determined
# command, and it is not meant to: --replay is opt-in and documented as
# "read the report first".
DANGEROUS_PATTERNS = (
    r"rm[ \t]+-[a-z]*[rf]",
    r"rm[ \t]+-r",
    r"\bmkfs\b",
    r"\bdd[ \t]+if=",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bformat[ \t]+[a-z]:",
    r"del[ \t]+/[fsq]",
    r"rmdir[ \t]+/s",
    r"git[ \t]+push\b",
    r"git[ \t]+reset[ \t]+--hard",
    r"git[ \t]+clean[ \t]+-[a-z]*[fd]",
    r"drop[ \t]+(table|database)\b",
    r"\btruncate\b",
    r"\|\s*(sudo[ \t]+)?(ba)?sh\b",
    r">\s*/dev/sd",
    r"chmod[ \t]+-R[ \t]+777[ \t]+/",
    r"\b(npm|pnpm|yarn)[ \t]+publish\b",
    r"\bdsh[ \t]+plugin\b",
    r":\(\)\s*\{",
    r"\bsudo\b",
)

NORMALIZERS = (
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?"
                r"(?:Z|[+-]\d{2}:?\d{2})?"), "<timestamp>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "<date>"),
    (re.compile(r"\b\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\b"), "<time>"),
    (re.compile(r"\b\d+(?:\.\d+)?[ \t]*(?:ms|us|\u00b5s|ns|secs|seconds|sec"
                r"|mins|minutes|min|\u6beb\u79d2|\u5206\u949f|\u79d2)\b"), "<duration>"),
    (re.compile(r"\b\d+(?:\.\d+)?[ \t]*s\b"), "<duration>"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    (re.compile(r"\b0x[0-9a-fA-F]{6,}\b"), "<address>"),
    (re.compile(r"\bpid[=: \t]+\d+\b", re.IGNORECASE), "pid=<pid>"),
    (re.compile(r"\b[A-Za-z]:\\[^\s\"']*(?:Temp|tmp)[^\s\"']*"), "<tmp-path>"),
    (re.compile(r"(?<![A-Za-z0-9])/tmp/[^\s\"']+"), "<tmp-path>"),
)


def normalize(text):
    """Fold volatile tokens so a re-run can be compared with a recorded run."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    folded = "\n".join(lines)
    for pattern, replacement in NORMALIZERS:
        folded = pattern.sub(replacement, folded)
    return folded


def is_dangerous(command):
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return pattern
    return None


# --- reading ---------------------------------------------------------------


def read_report(path):
    """Return (text, encoding_note). Raise ReadError when undecodable."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except (OSError, ValueError) as error:
        raise ReadError("cannot read " + path + ": " + str(error))

    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16"), "检测到 UTF-16 BOM，已按 UTF-16 解码"
        except UnicodeDecodeError as error:
            raise ReadError("UTF-16 解码失败：" + str(error))

    try:
        return raw.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        pass

    try:
        text = raw.decode("gb18030")
    except UnicodeDecodeError as error:
        raise ReadError(
            "文件既不是 UTF-8 也不是 GB18030，无法解码：" + str(error)
            + "。请把报告转存为 UTF-8 后再跑门禁。"
        )
    return text, "文件不是 UTF-8，已按 GB18030 解码（建议转存为 UTF-8）"


def read_evidence(path):
    """Return (exit_code or None, body, problem or None)."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except (OSError, ValueError) as error:
        return None, "", "证据文件读不了：" + str(error)

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gb18030")
        except UnicodeDecodeError as error:
            return None, "", "证据文件编码解不开：" + str(error)

    lines = text.replace("\r\n", "\n").split("\n")
    if not lines:
        return None, "", "证据文件是空的"
    marker = EXIT_MARKER_RE.match(lines[0].strip())
    if marker is None:
        return None, "", "证据文件首行必须是 [exit code: N]，实际是：" + lines[0].strip()[:60]
    return int(marker.group(1)), "\n".join(lines[1:]), None


# --- parsing ---------------------------------------------------------------


def field_key(label):
    lowered = label.strip().lower()
    for key, labels in FIELD_KEYS:
        for candidate in labels:
            if lowered == candidate.lower():
                return key
    return None


def looks_like_label(label):
    """True when a labelled line should end the previous value.

    Known field names always count. Anything containing a non-ASCII character
    counts too (影响, 建议修法, ...). A purely ASCII unknown label does not, so
    that `ValueError: bad input` inside a pasted traceback is not mistaken for a
    new field.
    """
    if field_key(label) is not None:
        return True
    for char in label:
        if ord(char) > 127:
            return True
    return False


def find_blocks(lines):
    """Return [(number, header, body_lines), ...] in document order.

    A block body ends at the next Markdown heading -- outside fenced code --
    rather than at the end of the file. Without that cut, a trailing section
    such as `## 未能验证` hands its fields to the last finding and a finding with
    no evidence at all is reported as OK.
    """
    starts = []
    in_fence = False
    for index, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = HEADING_RE.match(line)
        if not heading:
            continue
        head = BLOCK_HEAD_RE.match(heading.group(2).strip())
        if head:
            starts.append((index, head.group(1), heading.group(2).strip()))

    blocks = []
    for position, (start, number, header) in enumerate(starts):
        limit = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        body_end = limit
        in_fence = False
        for index in range(start + 1, limit):
            line = lines[index]
            if FENCE_RE.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            if HEADING_RE.match(line):
                body_end = index
                break
        blocks.append((number, header, lines[start + 1:body_end]))
    return blocks


def parse_fields(body_lines):
    """Return {key: text or None} for the recognised fields.

    A label with an empty inline value collects the lines below it, up to the
    next labelled line -- so multi-line commands and fenced output count as the
    value, which is the natural way to write evidence.
    """
    segments = []
    current = None
    in_fence = False
    for line in body_lines:
        if FENCE_RE.match(line):
            in_fence = not in_fence
            if current is not None:
                current[2].append(line)
            continue
        if not in_fence:
            matched = LABEL_RE.match(line)
            if matched and looks_like_label(matched.group("label")):
                key = field_key(matched.group("label"))
                inline = matched.group("value").strip()
                current = [key, inline, []]
                segments.append(current)
                continue
        if current is not None:
            current[2].append(line)

    found = {}
    for key, _labels in FIELD_KEYS:
        text = None
        for key_of_segment, inline, tail in segments:
            if key_of_segment != key:
                continue
            candidate = "\n".join([inline] + tail).strip()
            if candidate:
                text = candidate
                break
            if text is None:
                text = ""
        found[key] = text
    return found


# --- checking --------------------------------------------------------------


def is_blank(value):
    if value is None:
        return True
    stripped = value.strip()
    return stripped == "" or stripped.lower() in EMPTY_VALUES


def strip_ticks(value):
    """`path/to/file` -> path/to/file, for values written as inline code."""
    text = value.strip()
    if text.startswith("`") and text.endswith("`") and len(text) > 2:
        text = text[1:-1].strip()
    return text


def check_block(header, fields):
    """Return (problems, warnings) for one finding, before any replay."""
    problems = []
    warnings = []

    for key in ("location", "repro"):
        if fields.get(key) is None:
            problems.append("缺少「" + FIELD_NAMES[key] + "」这一行")
        elif is_blank(fields.get(key)):
            problems.append("「" + FIELD_NAMES[key] + "」是空的")

    has_evidence_file = not is_blank(fields.get("evidence"))
    has_inline = not is_blank(fields.get("observed"))
    if fields.get("observed") is None and fields.get("evidence") is None:
        problems.append("既没有「实测」也没有「证据文件」")
    elif not has_evidence_file and not has_inline:
        problems.append("「实测」和「证据文件」都是空的 —— 至少要有一样")

    if not SEVERITY_RE.search(header):
        warnings.append("标题里没写严重度（高/中/低），不利于分流")

    location = fields.get("location")
    if location and not is_blank(location):
        if PATHISH_RE.search(location) is None:
            problems.append("「位置」里看不到文件路径")
        elif LINE_NO_RE.search(location) is None and "行" not in location:
            warnings.append("「位置」没有行号（文档类审查可以忽略）")

    repro = fields.get("repro")
    if repro and not is_blank(repro):
        if len(repro) < 8:
            problems.append("「复现」太短，不足以让别人照抄执行")
        elif TECHISH_RE.search(repro) is None:
            warnings.append("「复现」里看不到命令、路径或参数，可能只是描述")

    observed = fields.get("observed")
    if observed and not is_blank(observed):
        lowered = observed.lower()
        marker = None
        for candidate in CANNOT_RUN_MARKERS:
            if candidate in lowered:
                marker = candidate
                break
        if marker is not None:
            reason = observed[lowered.index(marker) + len(marker):]
            reason = reason.strip().lstrip(":：,，。. ").strip()
            if len(reason) < 2 or reason.lower() in EMPTY_VALUES:
                problems.append("写了「未能执行」但没给原因")
        elif len(observed) < 4 and not has_evidence_file:
            warnings.append("「实测」几乎没有内容，看起来不是真的跑过")

    return problems, warnings


def check_evidence_file(fields, workdir):
    """A pointer to a missing or malformed evidence file is worse than none."""
    evidence = strip_ticks(fields.get("evidence") or "")
    path = evidence if os.path.isabs(evidence) else os.path.join(workdir, evidence)
    _code, body, problem = read_evidence(path)
    if problem:
        return "证据文件不可用：" + problem
    if not body.strip():
        return "证据文件只有退出码、没有输出内容"
    return None


def replay_finding(fields, workdir, timeout):
    """Return (verdict, detail) for one finding under --replay."""
    command = strip_ticks(fields.get("repro") or "")
    evidence = strip_ticks(fields.get("evidence") or "")

    matched = is_dangerous(command)
    if matched:
        return "REFUSED", "命令命中拒绝表（" + matched + "），未执行"

    evidence_path = evidence
    if not os.path.isabs(evidence_path):
        evidence_path = os.path.join(workdir, evidence_path)

    expected_code, expected_body, problem = read_evidence(evidence_path)
    if problem:
        return "UNUSABLE", problem

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "重跑超过 " + str(timeout) + "s 仍未结束"
    except (OSError, ValueError) as error:
        return "ERROR", "重跑起不来：" + str(error)

    actual_body = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != expected_code:
        return "DIFFERS", ("退出码不一致：证据文件记的是 " + str(expected_code)
                           + "，重跑得到 " + str(proc.returncode))

    expected_norm = normalize(expected_body)
    actual_norm = normalize(actual_body)
    if expected_norm == actual_norm:
        return "REPRODUCED", ""

    expected_lines = expected_norm.split("\n")
    actual_lines = actual_norm.split("\n")
    for index in range(max(len(expected_lines), len(actual_lines))):
        want = expected_lines[index] if index < len(expected_lines) else "(无此行)"
        got = actual_lines[index] if index < len(actual_lines) else "(无此行)"
        if want != got:
            return "DIFFERS", ("第 " + str(index + 1) + " 行不一致（归一化后）\n"
                               + "           证据文件: " + want[:140] + "\n"
                               + "           重跑结果: " + got[:140])
    return "DIFFERS", "输出不一致"


# --- entry -----------------------------------------------------------------


def run(path, strict, replay, workdir, timeout):
    try:
        text, encoding_note = read_report(path)
    except ReadError as error:
        sys.stderr.write(str(error) + "\n")
        return 2

    if encoding_note:
        print("[WARN] " + encoding_note)

    if workdir is None:
        workdir = os.path.dirname(os.path.abspath(path)) or os.getcwd()
    if not os.path.isdir(workdir):
        sys.stderr.write("--workdir 不是目录: " + workdir + "\n")
        return 2

    lines = text.splitlines()
    blocks = find_blocks(lines)

    if not blocks:
        for line in lines:
            if NONE_LINE_RE.match(line):
                print("[OK] 报告用独占一行的结论句声明了未发现问题 —— 通过")
                return 0
        print("[FAIL] 找不到任何 '### F<n>' 发现块，也没有独占一行的「未发现问题」结论句")
        print("       审查报告必须按模板分条，或明确声明没有发现。")
        return 1

    failed = 0
    warned = 0
    for number, header, body in blocks:
        fields = parse_fields(body)
        problems, warnings = check_block(header, fields)
        warned += len(warnings)

        if not problems and not is_blank(fields.get("evidence")):
            evidence_problem = check_evidence_file(fields, workdir)
            if evidence_problem:
                problems.append(evidence_problem)

        verdict = None
        detail = ""
        if replay and not problems:
            verdict, detail = replay_finding(fields, workdir, timeout)
        elif replay:
            verdict = "NO-EVIDENCE"
            detail = "字段不齐，未尝试重放"

        bad = bool(problems) or (verdict is not None and verdict != "REPRODUCED")
        if bad:
            failed += 1
            print("[FAIL] F" + number + " " + header)
            for problem in problems:
                print("       - " + problem)
            if verdict is not None and verdict != "REPRODUCED":
                print("       - 重放：" + verdict + " " + detail)
        else:
            label = "[ OK ]"
            if verdict == "REPRODUCED":
                label = "[OK/▶ ]"
            print(label + " F" + number + " " + header)
            if verdict == "REPRODUCED":
                print("       重放：输出与证据文件一致")
        for warning in warnings:
            print("       ! " + warning)

    total = len(blocks)
    print("")
    print("共 " + str(total) + " 条发现：" + str(total - failed) + " 条合格，"
          + str(failed) + " 条不合格，另有 " + str(warned) + " 条提醒。")

    if failed:
        if replay:
            print("重放不一致不等于造假 —— 也可能是环境差异；这种条目升级给人判断，"
                  "不要直接当噪声丢掉，也不要直接当成指控。")
        print("不合格的条目必须退回补证据，或直接当噪声丢弃 —— 不要凭它改代码。")
        return 1

    if strict and warned:
        print("--strict：还有 " + str(warned) + " 条提醒未清，本次按不合格处理。")
        return 1

    if replay:
        print("格式达标且全部重放一致 —— 每条都真的跑过，而且现在还能跑出同样的结果。")
    else:
        print("格式达标 —— 这只说明每条都写了位置/复现/证据，"
              "不代表内容为真：要验真实性请用 --replay，或自己逐条照抄命令。")
    return 0


def main(argv):
    args = []
    strict = False
    replay = False
    workdir = None
    timeout = 120.0

    index = 1
    while index < len(argv):
        item = argv[index]
        if item == "--strict":
            strict = True
        elif item == "--replay":
            replay = True
        elif item == "--workdir":
            index += 1
            if index >= len(argv):
                sys.stderr.write("--workdir 需要一个参数\n")
                return 2
            workdir = argv[index]
        elif item == "--timeout":
            index += 1
            if index >= len(argv):
                sys.stderr.write("--timeout 需要一个参数\n")
                return 2
            try:
                timeout = float(argv[index])
            except ValueError:
                sys.stderr.write("--timeout 需要是数字\n")
                return 2
        elif item.startswith("--"):
            sys.stderr.write("unknown option: " + item + "\n")
            sys.stderr.write("usage: check_review_report.py [--strict] [--replay] "
                             "[--workdir DIR] [--timeout SEC] <report.md>\n")
            return 2
        else:
            args.append(item)
        index += 1

    if len(args) != 1:
        sys.stderr.write("usage: check_review_report.py [--strict] [--replay] "
                         "[--workdir DIR] [--timeout SEC] <report.md>\n")
        return 2
    return run(args[0], strict, replay, workdir, timeout)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
