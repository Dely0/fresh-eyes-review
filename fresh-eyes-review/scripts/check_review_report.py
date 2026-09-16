#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check a fresh-eyes review report against the evidence format, and optionally
replay its evidence.

The report format is the one mandated by the `fresh-eyes-review` skill. Every
finding is a block headed `### F<n> ...` that must carry:

    位置           file:line
    复现           one command that anyone can copy and run
    实测           the observed output, OR
    证据文件        path to a file holding the raw output
    反向前置        one command that FAILS on the defective code
    反向前置证据     path to that command's raw output (exit code must be non-zero)

A finding without a location, a reproduction command and either inline output or
an evidence file is not evidence, it is an opinion, and must be sent back.

WHY THE PRE-FIX LINE EXISTS
---------------------------
Replay proves a command ran; it cannot prove the command has any bearing on the
claim. A reviewer can run `assert True`, record its (matching) output, and pass
`--replay` while proving nothing. The pre-fix line closes that: if you claim a
defect is real, the mechanical proof is a command that fails on the defective
code. Its evidence file must therefore record a NON-ZERO exit code. A recorded
exit code of 0 means the command passed, so the defect is not demonstrated --
that is a hard failure, not a warning.

`--pre-fix` re-runs those commands before you fix anything and requires them to
still fail. `--replay` runs after the fix and requires the reproduction to match.
Run the first before touching code, the second after: red then green.

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
    python check_review_report.py --pre-fix [--workdir DIR] [--timeout SEC] <report.md>
    python check_review_report.py --replay [--workdir DIR] [--timeout SEC] <report.md>

Exit codes:
    0  every finding carries usable evidence; under --pre-fix, every pre-fix
       command still fails; under --replay, every replay matched
    1  at least one finding is missing evidence, or its pre-fix evidence records
       a passing (0) exit code, or a pre-fix/replay run did not behave as
       required, or it was refused
    2  usage, read, or encoding error -- the report could not be read at all
       (also: --pre-fix and --replay are mutually exclusive)

`--strict` also fails on warnings (missing severity, location without a line
number, a location that does not exist, a missing pre-fix line, ...). Default
keeps warnings advisory.

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

# stderr matters as much as stdout here: several messages are Chinese, and on a
# cp936 console they would be unreadable in a redirect. The regression suite
# asserts on one of them, so leaving stderr alone made the suite red on Windows
# while looking green under PYTHONUTF8=1.
try:
    sys.stderr.reconfigure(encoding="utf-8")
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
    ("red", ("反向前置", "前置复现", "pre-fix", "prefix", "red")),
    ("red_evidence", ("反向前置证据", "前置证据文件", "pre-fix evidence", "red evidence")),
)

FIELD_NAMES = {
    "location": "位置",
    "repro": "复现",
    "evidence": "证据文件",
    "observed": "实测",
    "red": "反向前置",
    "red_evidence": "反向前置证据",
}

EMPTY_VALUES = (
    "无", "n/a", "na", "none", "-", "—", "不适用", "略", "待补", "未提供",
    "见上", "同上", "同前", "todo", "tbd", "?",
)

CANNOT_RUN_MARKERS = (
    "未能执行", "无法执行", "cannot run", "could not run", "not run",
    "没有执行", "未运行",
)

# The pre-fix line is the one place a "could not run" escape hatch is refused:
# the whole point of the line is that the defect was observed failing.
RED_CANNOT_RUN_MARKERS = (
    "未能执行", "无法执行", "cannot run", "could not run", "not run",
    "没有执行", "未运行", "不适用", "无法复现",
)

# --- handoff document (mode C: adversarial re-review) -----------------------
# The orchestrator writes this document, and the orchestrator is the party under
# review, so it is inherently self-serving. Provenance is therefore mandatory on
# every deliberate-trade-off entry, and it is machine-checked: an entry without
# an explicit source is a suppression order dressed up as a decision.
PROVENANCE_MARKERS = ("HumanDecision", "RecordedDecision", "OrchestratorClaim")
HANDOFF_REQUIRED_SECTIONS = ("范围", "已定取舍")
FALSIFY_SECTIONS = ("我确认成立的", "我驳倒的", "未决")
FALSIFY_VERDICT_MARKERS = ("严重度：", "判定：")
# A verdict that names no round-one finding is not a verdict. F5: a report whose
# three sections each say something vague ("逐条复核完毕") passed --strict while
# the gate printed "每条判定都标了出处", which was false on both counts.
# F1 might be followed directly by Chinese ("F1这个问题"): \b does not fire
# between a digit and a CJK character, so a word-boundary regex reports such a
# report as naming no finding at all -- a false failure on a legal report.
FINDING_REF_RE = re.compile(r"\bF\d+(?![0-9])")
NO_CLAIM_VALUES = ("无", "none", "-", "—", "n/a", "na", "不适用")

# --- review mode switch -----------------------------------------------------
# Mode C (adversarial re-review) costs another subagent round. It must not be
# entered on the orchestrator's own initiative: the round-one handoff document
# has to declare the mode, and the gate refuses --falsify when the declaration
# still says round one only. That turns "don't silently escalate to multi-round"
# into something a machine can enforce, instead of a wish in a document.
MODE_DECLARATION_RE = re.compile(r"审查模式\s*[\uFF1A:]\s*(.+)")
MODE_ADVERSARIAL_MARKERS = ("对抗性复审", "adversarial")
MODE_ROUND1_MARKERS = ("首轮", "round one", "round 1", "single")

USAGE = ("check_review_report.py [--strict] [--replay] [--pre-fix] [--falsify] "
         "[--handoff FILE] [--workdir DIR] [--timeout SEC] <report.md>")

EXIT_MARKER_RE = re.compile(r"^\[exit code:\s*(-?\d+)\]\s*$")

# --- cited location --------------------------------------------------------
# A path plus an optional line or line range, e.g. src/dedupe.py:139 or
# src/dedupe.py:12-34. Validated against the filesystem because a replayed
# command cannot prove that the *cited* location exists: a reviewer can run a
# deterministic command, get matching output, and still point at a file and
# line that were never there.
LOCATION_RE = re.compile(r"([A-Za-z0-9_.\-/\\]+\.[A-Za-z0-9_]+)[:\uFF1A](\d+)(?:\s*[-–]\s*(\d+))?")
CODE_SUFFIXES = (
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs", ".c", ".h",
    ".cc", ".cpp", ".hpp", ".swift", ".scala", ".sh", ".ps1", ".psm1",
    ".bat", ".cmd", ".sql", ".json", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".md", ".mjs",
)

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


def provenance_of(entry):
    """Return the provenance marker an entry actually declares, or None.

    Deliberately strict: the marker must open the value of a `依据:` label. A
    bare substring test is not enough, because "依据：未经 HumanDecision 确认"
    mentions the marker precisely to deny it, and an entry that merely says
    "HumanDecision 这事我们讨论过" has no basis label at all.
    """
    match = re.search(r"依据\s*[:\uFF1A]", entry)
    if match is None:
        return None
    value = entry[match.end():].strip()
    for marker in PROVENANCE_MARKERS:
        if value.startswith(marker):
            return marker
    return None


def check_handoff(markdown):
    """Return (problems, warnings) for a handoff document.

    Problems mean the document cannot be used as briefing material (it is
    missing the sections that make it a briefing rather than an instruction).
    Warnings are the honesty checks: a deliberate trade-off without provenance
    is a claim, not a decision, and must be labelled as such.
    """
    problems = []
    warnings = []
    if markdown.strip() == "":
        return ["交接文档是空的"], warnings

    lines, _fenced = strip_fences(markdown)
    headings = [line.strip().lstrip("#").strip() for line in lines
                if line.strip().startswith("##")]

    # Every required section must be present on its own: a document that only
    # carries the trade-offs is a suppression note, not a briefing.
    for section in HANDOFF_REQUIRED_SECTIONS:
        if not any(section in heading for heading in headings):
            problems.append("交接文档缺少必需小节：「## " + section + "」")

    in_tradeoffs = False
    entries = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("##"):
            in_tradeoffs = "已定取舍" in stripped
            continue
        if not in_tradeoffs:
            continue
        if stripped.startswith(("-", "*", "+")) and len(stripped) > 1:
            entries += 1
            if provenance_of(stripped) is None:
                warnings.append("取舍条目没有可辨认的出处（要求「依据：」后紧接 "
                                "HumanDecision / RecordedDecision / OrchestratorClaim）："
                                + stripped[:48])
    if entries == 0:
        problems.append("「## 已定取舍」下没有任何条目 —— 空小节和「别管」是一回事")

    return problems, warnings


def strip_fences(markdown):
    """Drop fenced code blocks, returning (kept_lines, fence_lines).

    Section and entry scanning must not count what is inside a fence: a report
    whose only "## 我确认成立的" heading sits in a ``` example is not a report,
    and a handoff document that merely quotes the template must not thereby
    satisfy its required sections.
    """
    kept = []
    fenced = []
    in_fence = False
    for line in markdown.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            fenced.append(line)
        else:
            kept.append(line)
    return kept, fenced


def declared_mode(markdown):
    """The review mode declared by a handoff document, or None."""
    for line in markdown.splitlines():
        match = MODE_DECLARATION_RE.search(line)
        if match is None:
            continue
        value = match.group(1).strip()
        lowered = value.lower()
        if any(marker in value for marker in MODE_ADVERSARIAL_MARKERS) or \
                any(marker in lowered for marker in MODE_ADVERSARIAL_MARKERS):
            return "adversarial"
        if any(marker in value for marker in MODE_ROUND1_MARKERS) or \
                any(marker in lowered for marker in MODE_ROUND1_MARKERS):
            return "round1"
        return "unknown"
    return None


def check_mode_declaration(markdown, falsify):
    """Return problems for the mode declaration.

    Rules: a handoff document must declare its mode; and --falsify (mode C) is
    only allowed when the declaration says the human confirmed the extra round.
    """
    problems = []
    mode = declared_mode(markdown)
    if mode is None:
        problems.append("交接文档缺少「审查模式：…」声明行 —— 说不清这一轮是首轮还是多轮，"
                        "就没法拦「偷偷升级到多轮」")
        return problems
    if falsify and mode != "adversarial":
        problems.append("交接文档声明的是首轮（或无法识别），却要跑 --falsify："
                        "对抗性复审必须由人先确认，并在声明里写清")
    return problems


def check_mode_declaration_permissive(markdown):
    """Mode check for plain --handoff runs.

    A document without a declaration is fine outside mode C -- it is only the
    escalation into multi-round that must be declared. Keeping the two rules
    apart stops --handoff from demanding something it never needed, which would
    be a breaking change for every existing handoff document.
    """
    if declared_mode(markdown) is None:
        return ["交接文档没有「审查模式：…」声明行（建议补上，便于日后审计）"]
    return []


def check_falsify_report(markdown):
    """Return (problems, warnings) for an adversarial re-review report.

    The point of mode C is that it can *disagree* with round one, so it cannot
    be forced into the finding-shaped contract. What it can be held to is that
    it says, per round-one finding, whether it still stands -- and that every
    claim is labelled with a verdict, the same distinction the main report makes
    between a claim and an observation.
    """
    problems = []
    warnings = []
    if markdown.strip() == "":
        return ["对抗性复审报告是空的"], warnings

    lines, _fenced = strip_fences(markdown)
    headings = [line.strip().lstrip("#").strip() for line in lines
                if line.strip().startswith("##")]
    for section in FALSIFY_SECTIONS:
        if not any(section in heading for heading in headings):
            problems.append("对抗性复审报告缺少小节：「## " + section + "」"
                            "（说不清哪些确认、哪些驳倒，就无法判断它做了什么）")
    if problems:
        return problems, warnings

    # Collect the bullet entries of each section, so each section can be judged
    # on its own: an empty or vague section is the failure mode F5 describes.
    sections = {section: [] for section in FALSIFY_SECTIONS}
    current = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("##"):
            current = None
            for section in FALSIFY_SECTIONS:
                if section in stripped:
                    current = section
                    break
            continue
        if current is not None and stripped.startswith(("-", "*", "+")) and len(stripped) > 1:
            sections[current].append(stripped)

    for section in FALSIFY_SECTIONS:
        entries = sections[section]
        if not entries:
            problems.append("「## " + section + "」下没有任何条目 —— 请逐条写，"
                            "没有就明确写一行「- 无」")
            continue
        if all(entry.strip("-*+ ").lower() in NO_CLAIM_VALUES for entry in entries):
            continue  # an explicit "- 无" is an answer
        if not any(FINDING_REF_RE.search(entry) for entry in entries):
            problems.append("「## " + section + "」没有点名任何一条上一轮发现 —— "
                            "判决必须落到具体条目上（例如 F1、F3）")

    # Only the two verdict-bearing sections take a per-entry verdict marker;
    # "未决" entries have no verdict to mark by definition.
    claims = 0
    for section in FALSIFY_SECTIONS[:2]:
        for entry in sections[section]:
            claims += 1
            if not any(marker in entry for marker in FALSIFY_VERDICT_MARKERS):
                warnings.append("判定条目没有标注（「· 严重度：」或「· 判定：」）："
                                + entry[:48])
    if claims == 0:
        warnings.append("没有逐条判定 —— 请明确写出你确认了什么、驳倒了什么")
    return problems, warnings


def load_handoff(path, workdir):
    """Read a handoff document. Returns (markdown, problem)."""
    full = path if os.path.isabs(path) else os.path.join(workdir, path)
    if not os.path.isfile(full):
        return "", "交接文档不存在：" + full
    try:
        with open(full, "rb") as handle:
            raw = handle.read()
    except OSError as error:
        return "", "交接文档读不了：" + str(error)
    try:
        return raw.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        try:
            return raw.decode("gb18030"), None
        except UnicodeDecodeError as error:
            return "", "交接文档编码解不开：" + str(error)


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


def extract_path(value):
    """Pull the path out of an evidence pointer.

    The pointer is often written as inline code followed by a note --
    `` `ev/F1.txt`（原始输出，未摘录） `` -- which is a perfectly reasonable way
    for a human to write it, and which `strip_ticks` alone turns into a
    one-string filename. Prefer whatever is inside the first pair of backticks;
    otherwise fall back to a path-shaped token.
    """
    text = value.strip()
    if "`" in text:
        parts = text.split("`")
        for index in range(1, len(parts), 2):
            candidate = parts[index].strip()
            if candidate == "":
                continue
            # Only a backticked span that stands on its own is a path. In
            # "ev/F1.txt（同 `probe.log` 那份）" the real path is bare and the
            # ticks belong to a note -- taking the note as the path would be a
            # false "evidence file unreadable".
            before = parts[index - 1].strip()
            after = parts[index + 1].strip() if index + 1 < len(parts) else ""
            boundary = ("", "（", "(", "：", ":", "，", ",", "、", " ")
            if before in boundary and (after == "" or after.startswith(boundary)):
                return candidate
            if before != "" and before not in boundary:
                continue
    match = PATHISH_RE.search(text) if PATHISH_RE is not None else None
    if match is not None:
        return match.group(0).strip()
    return strip_ticks(text)


def extract_command(value):
    """Pull the command out of a repro/red field.

    Same reasoning as extract_path: the command is usually written as inline
    code, and a trailing note must not end up inside the command string.
    """
    return extract_path(value) if "`" in value else value.strip()


def count_lines(path):
    """Line count of a file, counting a trailing newline as a terminator.

    Read as bytes: a file we cannot decode still has a knowable length, and
    failing to count it must never crash the gate.
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    if data == b"":
        return 0
    lines = data.count(b"\n")
    if not data.endswith(b"\n"):
        lines += 1
    return lines


def trim_path_left(text, end):
    """Extend a path leftwards from `end`, stopping at whitespace or punctuation.

    A space stays inside the path only when a separator also sits further left,
    so `foo.py:1 src/bar.py:2` yields the second path without dragging the first
    one's tail along. A drive letter is kept: the colon right after a single
    leading alphanumeric is part of `C:\...`, not a boundary.
    """
    start = end
    while start > 0:
        char = text[start - 1]
        if char == ":":
            if start >= 2 and text[start - 2].isalnum() and (start - 2 == 0 or text[start - 3] in " \t("):
                start -= 2
                continue
            break
        if char == " ":
            prefix = text[:start - 1]
            if "/" not in prefix and "\\" not in prefix:
                break
            start -= 1
            continue
        if char in "\"'`(),;<>[]{}|*?=":
            break
        start -= 1
    return text[start:end]


def path_candidates(location):
    """Yield (anchor, path, line) for every `<path>:<n>` that hints at code.

    Every match is yielded rather than only the first: a location may list
    several files, and a non-code one appearing first (a note, a log) must not
    stop the code paths after it from being checked.
    """
    for match in LOCATION_RE.finditer(location):
        left_extra = trim_path_left(location, match.start(1))
        anchor = match.start(1) - len(left_extra)
        # A scheme in the left context means this is a URL, not a cited file;
        # checking it would only produce a false "file not found".
        if "://" in location[max(0, anchor - 10):match.end(1)]:
            continue
        path = left_extra + match.group(1)
        if path == "":
            continue
        if not path.lower().endswith(CODE_SUFFIXES):
            continue
        yield anchor, path, int(match.group(2))


def check_location_path(location, workdir):
    """Warn when a cited file or line is not there.

    This is the one part of a finding that can be checked mechanically without
    judging meaning, so it should not be left to a human. It warns rather than
    fails, because a report may legitimately cite a path outside --workdir.

    A location may list several files. Any candidate that resolves counts as
    "the location is real"; only when none resolves is the citation reported as
    missing, and the first one is named.
    """
    candidates = list(path_candidates(location))
    if not candidates:
        return None
    first_path = candidates[0][1]
    for _anchor, path, line in candidates:
        resolved = path if os.path.isabs(path) else os.path.join(workdir, path)
        if not os.path.isfile(resolved):
            continue
        total = count_lines(resolved)
        if total is not None and line > total:
            return ("「位置」的行号 " + str(line) + " 超出文件总行数 "
                    + str(total) + "：" + path)
    if any(os.path.isfile(p if os.path.isabs(p) else os.path.join(workdir, p))
           for _a, p, _n in candidates):
        return None
    return "「位置」指向的文件不存在：" + first_path + "（在 --workdir 下没找到）"


def check_block(header, fields, workdir=None):
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
        if workdir is not None:
            location_warning = check_location_path(location, workdir)
            if location_warning is not None:
                warnings.append(location_warning)

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
    evidence = extract_path(fields.get("evidence") or "")
    path = evidence if os.path.isabs(evidence) else os.path.join(workdir, evidence)
    _code, body, problem = read_evidence(path)
    if problem:
        return "证据文件不可用：" + problem
    if not body.strip():
        return "证据文件只有退出码、没有输出内容"
    return None


def resolve_red(fields):
    """The pre-fix command, resolving the shorthand "同上" to the repro field.

    Writing "同上" is a normal human shorthand for "the same command as the
    reproduction above" -- it is a reference, not prose, so it must not be
    judged as a too-short command. A trailing note is allowed:
    "同上（探针断言 X 与 Y 矛盾）" still refers to the repro command.
    """
    red = (fields.get("red") or "").strip()
    normalized = red.replace("：", ":")
    if normalized.startswith(("同上", "同前")):
        return (fields.get("repro") or "").strip()
    if normalized.lower().startswith(("same as above", "same")):
        return (fields.get("repro") or "").strip()
    return red


def check_red(fields, workdir):
    """Check the pre-fix (red) fields. Returns (problems, warnings).

    The core rule, and the reason this field exists: **the recorded pre-fix
    exit code must be non-zero.** A finding claims a defect is real; the one
    mechanical proof of that is a command that fails on the defective code.
    If the recorded exit code is 0, the command passed and therefore does not
    demonstrate the defect -- which is exactly how "assert True" posing as a
    defect report is caught.
    """
    problems = []
    warnings = []
    raw_red = fields.get("red")
    red_evidence = fields.get("red_evidence")

    # Resolve the "同上" shorthand *before* the blank test: is_blank() treats
    # 同上 as an empty value, so checking first would report the field as
    # missing even though it points at a perfectly good command above.
    red = resolve_red(fields).strip() if raw_red is not None else ""
    if is_blank(raw_red) and is_blank(red):
        warnings.append("缺少「反向前置」：没有给出「修复前必须失败」的复现入口，缺陷是否真实只能靠人判断")
        return problems, warnings

    text = extract_command(red)
    lowered = text.lower()
    cannot_run = None
    for marker in RED_CANNOT_RUN_MARKERS:
        if marker in lowered:
            cannot_run = marker
            break
    if cannot_run is not None:
        problems.append("「反向前置」写了「" + cannot_run + "」——这一行必须是能跑的命令"
                        "（缺陷被观察到失败，是这条发现唯二的事实之一）")
        return problems, warnings

    if len(text) < 8:
        problems.append("「反向前置」太短，不足以让别人照抄执行")
    elif TECHISH_RE.search(text) is None:
        warnings.append("「反向前置」里看不到命令、路径或参数，可能只是描述")

    if red_evidence is None or is_blank(red_evidence):
        warnings.append("有「反向前置」但没有「反向前置证据」文件 —— 修复前的退出码没有被落盘，"
                        "无法机械核实这条缺陷真的被观察到失败")
        return problems, warnings

    pointer = extract_path(red_evidence)
    path = pointer if os.path.isabs(pointer) else os.path.join(workdir, pointer)
    code, body, problem = read_evidence(path)
    if problem:
        problems.append("反向前置证据不可用：" + problem)
        return problems, warnings
    if code == 0:
        problems.append("反向前置证据记的是 exit code 0 —— 命令在「有缺陷」的代码上通过了，"
                        "说明这条缺陷不成立（或这条命令证明不了它）")
        return problems, warnings
    if code is None:
        problems.append("反向前置证据没有可解析的退出码")
        return problems, warnings
    if not body.strip():
        warnings.append("反向前置证据只有退出码、没有失败输出")
    if code < 0:
        warnings.append("反向前置证据的退出码是负数（" + str(code) + "）—— 那是信号终止而不是失败，"
                        "请确认它真的是一次失败的测试运行")
    return problems, warnings


def replay_red(fields, workdir, timeout):
    """Re-run the pre-fix command; under --pre-fix it must still fail.

    Only meaningful before the fix is applied: once the defect is fixed the
    command is expected to pass, and reporting DIFFERS then would be wrong.
    """
    _problems, _warnings = check_red(fields, workdir)
    command = extract_command(fields.get("red") or "")
    matched = is_dangerous(command)
    if matched:
        return "REFUSED", "命令命中拒绝表（" + matched + "），未执行"

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

    if proc.returncode == 0:
        return "DIFFERS", ("反向前置命令这次通过了（exit 0）—— 缺陷没能复现。"
                           "若你已修好它，请改用 --replay 验证修复，而不是 --pre-fix")
    return "REPRODUCED", ""


def replay_red_green(fields, workdir, timeout):
    """Under --replay, the pre-fix command must have turned GREEN.

    This is the other half of "red then green", and it is what makes a forged
    pre-fix exit code useless: the command is actually re-run here, so an author
    cannot claim "this fails on the defective code" with a command that never
    could. A command that is still failing after the fix means either the fix is
    incomplete, the command was never about this defect, or it was fabricated.
    """
    command = extract_command(fields.get("red") or "")
    matched = is_dangerous(command)
    if matched:
        return "REFUSED", "命令命中拒绝表（" + matched + "），未执行"

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

    if proc.returncode != 0:
        return "DIFFERS", ("反向前置命令修完之后仍然是失败的（exit "
                           + str(proc.returncode) + "）—— 要么修复没完成，"
                           "要么这条命令与那条缺陷无关")
    return "REPRODUCED", ""


def replay_finding(fields, workdir, timeout):
    """Return (verdict, detail) for one finding under --replay."""
    command = extract_command(fields.get("repro") or "")
    evidence = extract_path(fields.get("evidence") or "")

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


def run(path, strict, replay, workdir, timeout, pre_fix=False, handoff=None, falsify=False):
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

    # --- handoff document (optional, mode C) --------------------------------
    handoff_warnings = []
    if handoff is not None:
        markdown, handoff_problem = load_handoff(handoff, workdir)
        if handoff_problem is not None:
            sys.stderr.write(handoff_problem + "\n")
            return 2
        handoff_problems, handoff_warnings = check_handoff(markdown)
        for problem in handoff_problems:
            print("[FAIL] 交接文档：" + problem)
        for warning in handoff_warnings:
            print("[WARN] 交接文档：" + warning)
        if handoff_problems:
            print("交接文档不合格 —— 它是审查者的简报，必须能被机器读懂："
                  "范围为谁、取舍谁的、边界在哪。")
            return 1

    # --- review-mode switch -------------------------------------------------
    # Checked before anything else runs: entering mode C without a human-backed
    # declaration must be refused, not merely noted.
    if handoff is not None and falsify:
        # Mode C only: entering a second review round needs a declaration that a
        # human confirmed it. Plain --handoff stays permissive (see above).
        mode_problems = check_mode_declaration(markdown, True)
        for problem in mode_problems:
            print("[FAIL] 审查模式：" + problem)
        if mode_problems:
            return 2

    # --- adversarial re-review (mode C) -------------------------------------
    if falsify:
        falsify_problems, falsify_warnings = check_falsify_report(text)
        for problem in falsify_problems:
            print("[FAIL] 对抗性复审：" + problem)
        for warning in falsify_warnings:
            print("[WARN] 对抗性复审：" + warning)
        if falsify_problems:
            return 1
        if strict and (falsify_warnings or handoff_warnings):
            print("--strict：对抗性复审/交接文档还有 "
                  + str(len(falsify_warnings) + len(handoff_warnings)) + " 条提醒未清，本次按不合格处理。")
            return 1
        if handoff_warnings and not strict:
            print("对抗性复审通过（交接文档另有 " + str(len(handoff_warnings))
                  + " 条提醒，见上）。")
            return 0
        print("对抗性复审通过 —— 分段齐全，每条判定都标了出处。")
        return 0

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
    warned = len(handoff_warnings) if handoff is not None else 0
    for number, header, body in blocks:
        fields = parse_fields(body)
        problems, warnings = check_block(header, fields, workdir)

        if not problems and not is_blank(fields.get("evidence")):
            evidence_problem = check_evidence_file(fields, workdir)
            if evidence_problem:
                problems.append(evidence_problem)

        # The pre-fix checks contribute warnings too, so the count has to happen
        # after they are merged -- counting earlier silently exempts every
        # red-field warning from --strict.
        red_problems, red_warnings = check_red(fields, workdir)
        problems.extend(red_problems)
        warnings.extend(red_warnings)
        warned += len(warnings)

        verdict = None
        detail = ""
        green_note = ""
        if pre_fix and not problems:
            if is_blank(fields.get("red")):
                verdict = "NO-EVIDENCE"
                detail = "没有「反向前置」，无法核实缺陷是否真的被观察到失败"
            else:
                verdict, detail = replay_red(fields, workdir, timeout)
        elif replay and not problems:
            verdict, detail = replay_finding(fields, workdir, timeout)
            # "red then green" needs both halves: --pre-fix proves the command
            # failed before the fix, --replay proves it passes after. Running
            # the second here is what makes a forged pre-fix exit code useless.
            if verdict == "REPRODUCED":
                if is_blank(fields.get("red")):
                    warnings.append("这条发现没有「反向前置」，所以只验了「修复后能重现」，"
                                    "没有验过「修复前确实失败」——先补前置命令，改之前用 --pre-fix 跑一次")
                    warned += 1
                else:
                    green_verdict, green_detail = replay_red_green(fields, workdir, timeout)
                    if green_verdict != "REPRODUCED":
                        verdict, detail = green_verdict, green_detail
                    else:
                        green_note = "反向前置命令修完之后已通过（先红后绿）"
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
                print("       - " + ("前置重跑：" if pre_fix else "重放：") + verdict + " " + detail)
        else:
            label = "[ OK ]"
            if verdict == "REPRODUCED":
                label = "[OK/▶ ]"
            print(label + " F" + number + " " + header)
            if verdict == "REPRODUCED":
                if pre_fix:
                    print("       前置重跑：命令仍然失败 —— 缺陷被复现")
                elif green_note != "":
                    print("       重放：输出与证据文件一致；" + green_note)
                else:
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

    if pre_fix:
        print("前置重跑通过 —— 每条都给出了「修复前必须失败」的命令，而且它现在真的还失败着。")
    elif replay:
        print("格式达标且全部重放一致 —— 每条都真的跑过，而且现在还能跑出同样的结果。")
    else:
        print("格式达标 —— 这只说明每条都写了位置/复现/证据，"
              "不代表内容为真：要验真实性请用 --replay，或自己逐条照抄命令。")
    return 0


def main(argv):
    args = []
    strict = False
    replay = False
    pre_fix = False
    falsify = False
    handoff = None
    workdir = None
    timeout = 120.0

    index = 1
    while index < len(argv):
        item = argv[index]
        if item == "--strict":
            strict = True
        elif item == "--replay":
            replay = True
        elif item == "--pre-fix":
            pre_fix = True
        elif item == "--falsify":
            falsify = True
        elif item == "--handoff":
            index += 1
            if index >= len(argv):
                sys.stderr.write("--handoff 需要一个参数\n")
                return 2
            handoff = argv[index]
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
            sys.stderr.write("usage: " + USAGE + "\n")
            return 2
        else:
            args.append(item)
        index += 1

    if pre_fix and replay:
        sys.stderr.write("--pre-fix 与 --replay 互斥：前者验「修复前必须失败」，"
                         "后者验「修复后能重现」，请在改动前后各跑一次\n")
        return 2

    # Mode C needs round one's findings to attack; without the handoff the
    # second reviewer would have nothing to falsify and would just re-review.
    if falsify and handoff is None:
        sys.stderr.write("--falsify 必须同时给出 --handoff：对抗性复审的对象是"
                         "「上一轮报告」，没有交接文档就无从下手\n")
        return 2

    # Mode C judges round one's report; it does not walk the finding blocks, so
    # pairing it with the evidence modes would silently skip them and still
    # print a green result. Refuse rather than report work that never happened.
    if falsify and (pre_fix or replay):
        sys.stderr.write("--falsify 与 --pre-fix / --replay 不能同时使用："
                         "模式 C 判的是「上一轮的报告」，不走发现块与证据重放；"
                         "这两类校验请分别运行\n")
        return 2

    if len(args) != 1:
        sys.stderr.write("usage: " + USAGE + "\n")
        return 2
    return run(args[0], strict, replay, workdir, timeout, pre_fix, handoff, falsify)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
