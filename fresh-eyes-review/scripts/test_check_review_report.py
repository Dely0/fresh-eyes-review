#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression suite for check_review_report.py.

Every case is a bug that was actually found in a real review, or the safety net
that keeps a fix from over-reaching. Fixtures are generated here rather than read
from disk, so the suite is self-contained and can run anywhere.

Usage:
    python test_check_review_report.py

Exit codes:
    0  every assertion holds
    1  at least one assertion failed (the gate does not behave as documented)

Each case declares the exit code the gate MUST return. A red case means the gate
is wrong, not the test. Add a new rule to the gate? Add a case here that goes red
first.
"""

import base64
import os
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "check_review_report.py")

GOOD = """### F1 判重在生产上从没问过模型 · 严重度：高
- 位置：src/dedupe.py:139
- 复现：python src/dedupe.py --check
- 实测：checked=1 same=0 attached=0 calls=0
- 影响：静默失效，功能从未生效
- 建议修法：字段容忍缺失
"""

WARN_ONLY = """### F1 没写严重度的问题
- 位置：src/app.py:1
- 复现：python src/app.py --check
- 实测：exit=0
"""

# 证据文件路径相对报告所在目录
REPLAY_OK = """### F1 备份清理会误删导出目录 · 严重度：高
- 位置：scripts/backup.py:44
- 复现：echo cleaned=0 kept=1
- 证据文件：ev/F1.txt
- 实测：cleaned=0 kept=1
- 影响：人工导出的目录被整目录删除
- 建议修法：清理前按前缀白名单过滤
"""

EV_OK = b"[exit code: 0]\ncleaned=0 kept=1\n"


# 位置校验夹具：报告引用 location，可选地造出 stub 文件。
# red=True 时带一条合规的「反向前置」，好让这些用例只暴露位置校验的提醒，
# 不被「缺少反向前置」那条提醒干扰（后者另有专门用例）。这条前置命令不引用
# stub 文件 —— 否则位置校验会把它的提醒也算进来，掩盖这些用例要验的东西。
REAL_PY = b"x = 1\ny = 2\n"


def location_report(location, stubs, red=True):
    lines = [
        "### F1 幻觉定位用例 · 严重度：高",
        "- 位置：" + location,
        "- 复现：echo checked=1",
        "- 实测：checked=1",
    ]
    if red:
        lines.append("- 反向前置：python -c \"import sys;sys.exit(1)\"")
        lines.append("- 反向前置证据：ev/R1.txt")
    lines.append("- 影响：误判")
    files = {"report.md": ("\n".join(lines) + "\n").encode("utf-8")}
    if red:
        files["ev/R1.txt"] = b"[exit code: 1]\nfail\n"
    for stub in stubs:
        files[stub] = REAL_PY
    return files


HANDOFF_OK = """# 审查交接文档

## 范围
- 工作目录：`C:\\work\\repo`
- 改动范围：`git diff` 的 6 个文件
- 验收标准：既有回归全绿；不引入对合法报告的误报

## 已定取舍
- 归一化只折叠十类已知易变 token | 依据：HumanDecision：真人明确要求先保守，假失败率量出来再放宽 | 影响边界：未被识别的易变内容会产生假不一致，会被升级给人
- 报告只支持 Markdown 一种输入 | 依据：RecordedDecision：issue #1 里确认 | 影响边界：无法解析 JSON 报告

## 已驳回的发现
- F3「位置校验会误杀 `notes.txt`」| 驳回理由：非代码后缀本就不参与校验，这是有意的
"""

HANDOFF_NO_PROVENANCE = """# 审查交接文档

## 范围
- 工作目录：`C:\\work\\repo`

## 已定取舍
- 归一化只折叠十类已知易变 token | 影响边界：未被识别的易变内容会产生假不一致
"""

FALSIFY_NO_HEADINGS = """### 对抗性复审 · 目标：2026-09-16 报告

- F1 `--strict` 不计数反向前置提醒 · 严重度：高
"""


def falsify_body(confirmed="- F1 缓存淘汰多留一条 · 严重度：高",
                 refuted="- F2 上轮说日志会丢，实际是正常轮转 · 严重度：低",
                 undecided="- F9 涉及 CI 行为，本地无法验证",
                 omit_undecided=False):
    """按参数拼一份对抗性复审报告，方便逐条构造边界用例。

    用参数而不是字符串 replace：replace 的目标一旦不存在，就会静默返回原文，
    让用例在「什么都没改」的夹具上通过 —— 那种伪绿本套件已经踩过两次。
    """
    lines = ["### 对抗性复审 · 目标：2026-09-16 报告（3 条）", "",
             "## 我确认成立的", confirmed, "",
             "## 我驳倒的", refuted, ""]
    if not omit_undecided:
        lines += ["## 未决", undecided, ""]
    return "\n".join(lines)


FALSIFY_OK = falsify_body()



MODE_ROUND1 = "审查模式：首轮"
MODE_ADVERSARIAL = "审查模式：首轮 + 对抗性复审（用户已确认）"


def handoff_files(body, report_files=None, mode=MODE_ROUND1):
    """交接文档夹具。mode=None 表示不写模式声明行（旧文档）。

    模式声明是「不许偷偷升级到多轮」的那个开关：声明为「首轮」却跑
    --falsify，门禁必须退 2。
    """
    if mode is not None:
        body = body.replace("# 审查交接文档",
                            "# 审查交接文档\n\n" + mode, 1)
    files = {".review-handoff.md": body.encode("utf-8")}
    if report_files:
        files.update(report_files)
    return files


# 模式 C 的用例需要一份「已确认多轮」的交接文档 + 一份合法的报告。
# 这条声明就是开关：声明首轮却跑 --falsify，门禁退 2。
HANDOFF_ADVERSARIAL = MODE_ADVERSARIAL + "\n\n" + HANDOFF_OK.split("\n", 1)[1]


def adversarial_files(report_body):
    """模式 C 的通用夹具：带声明的交接文档 + 指定的第二轮报告。"""
    return {".review-handoff.md": HANDOFF_ADVERSARIAL.encode("utf-8"),
            "report.md": report_body if isinstance(report_body, bytes)
            else report_body.encode("utf-8")}


def good_report_files():
    """一份完全合规的报告，供模式 C 的用例兜底。

    必须是「零提醒」的：否则 --strict 会因为报告自身的位置/反向前置提醒变红，
    把用例要验的交接文档规则掩盖过去。
    """
    return {
        "report.md": ("### F1 模式 C 兜底报告 · 严重度：高\n"
                      "- 位置：src/real.py:1\n"
                      "- 复现：python -c \"print('checked=1')\"\n"
                      "- 证据文件：ev/F1.txt\n"
                      "- 反向前置：python -c \"import sys;sys.exit(1)\"\n"
                      "- 反向前置证据：ev/R1.txt\n"
                      "- 实测：见证据文件\n").encode("utf-8"),
        "src/real.py": b"x = 1\n",
        "ev/F1.txt": b"[exit code: 0]\nchecked=1\n",
        "ev/R1.txt": b"[exit code: 1]\nfail\n",
    }


def replay_report(command, evidence_path="ev/F1.txt", observed="见证据文件"):
    return (
        "### F1 重放用例 · 严重度：高\n"
        "- 位置：scripts/backup.py:44\n"
        "- 复现：" + command + "\n"
        "- 证据文件：" + evidence_path + "\n"
        "- 实测：" + observed + "\n"
        "- 影响：误删\n"
    ).encode("utf-8")


def red_report(red, evidence_path="ev/R1.txt", repro=None, repro_evidence="ev/F1R.txt",
               location="src/backup.py:1", stubs=("src/backup.py",)):
    """Report fixture for the pre-fix contract. red=None omits the field.

    `repro` defaults to a command whose output matches `repro_evidence`,
    so the --replay half of a case is self-consistent by construction. The
    location is deliberately real (a stub file is emitted) and carries a line
    number, so these cases expose *only* the pre-fix rules -- otherwise a red
    case could go red on the location warning and pass for the wrong reason.
    """
    if repro is None:
        repro = "python -c \"import sys;sys.exit(0)\""
    lines = [
        "### F1 反向前置用例 · 严重度：高",
        "- 位置：" + location,
        "- 复现：" + repro,
        "- 证据文件：" + repro_evidence,
        "- 实测：见证据文件",
    ]
    files = {}
    if red is not None:
        lines.append("- 反向前置：" + red)
        lines.append("- 反向前置证据：" + evidence_path)
    lines.append("- 影响：误删")
    files["report.md"] = ("\n".join(lines) + "\n").encode("utf-8")
    if red is not None:
        files[evidence_path] = b"[exit code: 1]\nfail\n"
    for stub in stubs:
        files[stub] = b"x = 1\n"
    return files


CASES = [
    # --- 基础格式 ---------------------------------------------------------
    ("good", {"report.md": GOOD.encode("utf-8")}, [], 0,
     "安全网：完全合规的报告必须通过"),
    ("missing_observed", {"report.md": GOOD.replace(
        "- 实测：checked=1 same=0 attached=0 calls=0\n", "").encode("utf-8")}, [], 1,
     "既没有实测也没有证据文件必须被拦"),

    # --- F1 块边界不得泄漏到尾部小节 ---------------------------------------
    ("tail_leak", {"report.md": (
        "### F1 末条发现一个字段都没写 · 严重度：高\n\n"
        "## 未能验证\n"
        "- 位置：src/a.py:1\n"
        "- 复现：python src/a.py --check\n"
        "- 实测：未能执行：没有网络\n"
    ).encode("utf-8")}, [], 1,
     "尾部小节的字段不得替末条发现补齐（假阴性）"),
    ("mid_leak", {"report.md": (
        "### F1 缺字段的发现 · 严重度：高\n\n"
        "### F2 这条是好的 · 严重度：高\n"
        "- 位置：src/a.py:1\n- 复现：python src/a.py --check\n- 实测：exit=0\n\n"
        "## 未能验证\n- 实测：未能执行：没网\n"
    ).encode("utf-8")}, [], 1,
     "中间小节的字段不得算到前一条发现头上"),

    # --- F2 「未发现问题」必须独占一行 -------------------------------------
    ("none_standalone", {"report.md": "审完了。未发现问题。\n".encode("utf-8")}, [], 0,
     "独占一行的结论句应当被接受"),
    ("prose_none_word", {"report.md": "重跑之后无问题。\n".encode("utf-8")}, [], 1,
     "正文里出现「无问题」子串不能翻成通过（假阴性）"),
    ("prose_no_blocks", {"report.md": "我读了代码，整体还行。\n".encode("utf-8")}, [], 1,
     "散文式报告不算报告"),
    ("bad_block_plus_none", {"report.md": (
        "### F1 缺证据 · 严重度：高\n- 位置：src/a.py:1\n"
        "- 复现：python src/a.py --check\n\n未发现问题\n"
    ).encode("utf-8")}, [], 1,
     "有发现块时，结论句不能覆盖发现块的失败"),
    ("empty_file", {"report.md": b""}, [], 1, "空报告必须失败"),

    # --- F3 编码 -----------------------------------------------------------
    ("gbk_good", {"report.md": GOOD.encode("gb18030")}, [], 0,
     "GBK 落盘的合规报告不该被误杀"),
    ("utf16_good", {"report.md": GOOD.encode("utf-16")}, [], 0,
     "UTF-16 BOM 的合规报告不该被误杀"),
    ("undecodable", {"report.md": b"\xff\xff\xff\xff"}, [], 2,
     "解码失败属于读取错误，必须退 2 而不是 1"),

    # --- F4/F5 标签与多行值 ------------------------------------------------
    ("bold_labels", {"report.md": (
        "### F1 加粗标签也要认 · 严重度：中\n"
        "- **位置**：`scripts/check_review_report.py`:65\n"
        "- **复现**：`python scripts/x.py --dry-run`\n"
        "- **实测**：`exit=0`\n"
    ).encode("utf-8")}, [], 0,
     "`- **位置**：…` 是模板允许的写法，不该误杀"),
    ("ascii_labels", {"report.md": (
        "### F1 ascii labels · severity: high\n"
        "- location: src/a.py:1\n"
        "- reproduce: python src/a.py --check\n"
        "- observed: exit=0\n"
    ).encode("utf-8")}, [], 0, "ASCII 字段名同样合法"),
    ("value_next_line", {"report.md": (
        "### F1 多行证据 · 严重度：高\n"
        "- 位置：scripts/backup.py:44\n"
        "- 复现：\n"
        "  python scripts/backup.py --out /tmp/bk --keep 1\n"
        "- 实测：\n"
        "  ```\n"
        "  md-snapshots 被整目录删除\n"
        "  exit=0\n"
        "  ```\n"
        "- 影响：误删人工导出的目录\n"
    ).encode("utf-8")}, [], 0, "多行命令与围栏输出是自然写法，不该误杀"),
    ("value_next_line_traceback", {"report.md": (
        "### F1 粘贴的报错里带冒号 · 严重度：高\n"
        "- 位置：src/a.py:1\n"
        "- 复现：python src/a.py --check\n"
        "- 实测：\n"
        "  ```\n"
        "  Traceback (most recent call last):\n"
        "  ValueError: bad input\n"
        "  ```\n"
    ).encode("utf-8")}, [], 0,
     "围栏里的 `ValueError: …` 不得被当成新字段而截断值"),

    # --- F6 废话不算证据 ---------------------------------------------------
    ("junk_values", {"report.md": (
        "### F1 问题 · 严重度：高\n"
        "- 位置：src/a.py:1\n- 复现：见上\n- 实测：无\n"
    ).encode("utf-8")}, [], 1, "「见上」「无」这类填充词不算证据"),
    ("warn_only_default", {"report.md": WARN_ONLY.encode("utf-8")}, [], 0,
     "默认档：提醒不影响退出码"),
    ("warn_only_strict", {"report.md": WARN_ONLY.encode("utf-8")}, ["--strict"], 1,
     "--strict 档：提醒也应让门禁失败"),

    # --- F9 「未能执行」的原因阈值 -----------------------------------------
    ("cannot_run_short_reason", {"report.md": (
        "### F1 跑不了但给了原因 · 严重度：中\n"
        "- 位置：docs/upgrade.md\n"
        "- 复现：重启服务后观察启动行的配置键\n"
        "- 实测：未能执行：没网\n"
    ).encode("utf-8")}, [], 0, "给了原因（哪怕两个字）就不该判「没给原因」"),
    ("cannot_run_no_reason", {"report.md": (
        "### F1 跑不了也没说原因 · 严重度：中\n"
        "- 位置：src/a.py:1\n- 复现：python src/a.py --check\n- 实测：未能执行\n"
    ).encode("utf-8")}, [], 1, "只写「未能执行」而不给原因必须被拦"),

    # --- 证据文件（静态校验） ----------------------------------------------
    ("evidence_ok", {"report.md": REPLAY_OK.encode("utf-8"), "ev/F1.txt": EV_OK}, [], 0,
     "证据文件存在且格式正确应当通过"),
    ("evidence_missing", {"report.md": replay_report("echo ok")}, [], 1,
     "指向不存在的证据文件必须被拦（悬空指针比没有更糟）"),
    ("evidence_no_marker", {"report.md": REPLAY_OK.encode("utf-8"),
                            "ev/F1.txt": b"cleaned=0 kept=1\n"}, [], 1,
     "证据文件首行必须是 [exit code: N]"),
    ("evidence_empty_body", {"report.md": REPLAY_OK.encode("utf-8"),
                             "ev/F1.txt": b"[exit code: 0]\n"}, [], 1,
     "证据文件只有退出码、没有输出内容必须被拦"),

    # --- 重放档 -------------------------------------------------------------
    ("replay_reproduced", {"report.md": REPLAY_OK.encode("utf-8"), "ev/F1.txt": EV_OK},
     ["--replay"], 0, "重跑输出与证据文件一致时必须通过"),
    ("replay_differs", {"report.md": REPLAY_OK.encode("utf-8"),
                        "ev/F1.txt": b"[exit code: 0]\ncleaned=9 kept=9\n"},
     ["--replay"], 1, "重跑输出与证据文件不一致必须被拦"),
    ("replay_exit_mismatch", {"report.md": REPLAY_OK.encode("utf-8"),
                              "ev/F1.txt": b"[exit code: 3]\ncleaned=0 kept=1\n"},
     ["--replay"], 1, "退出码不一致必须被拦"),
    ("replay_normalized", {
        "report.md": replay_report("echo done at 2026-09-16T00:00:00Z in 12ms"),
        "ev/F1.txt": b"[exit code: 0]\ndone at 2025-01-01T11:11:11Z in 999ms\n"},
     ["--replay"], 0, "易变内容（时间戳/耗时）归一化后一致应当通过"),
    ("replay_refused", {
        "report.md": replay_report("rm -rf build/ --dry-run"),
        "ev/F1.txt": b"[exit code: 0]\nremoved\n"},
     ["--replay"], 1, "命中拒绝表的命令不得执行，按不合格处理"),
    ("replay_timeout", {
        "report.md": replay_report('python -c "import time;time.sleep(3)"'),
        "ev/F1.txt": b"[exit code: 0]\nnever\n"},
     ["--replay", "--timeout", "1"], 1, "重跑超时必须被拦"),
    ("replay_requires_evidence_file", {"report.md": GOOD.encode("utf-8")},
     ["--replay"], 1, "重放档下只有内联实测、没有证据文件的条目不满足重放前提"),
    ("replay_none_declared", {"report.md": "未发现问题\n".encode("utf-8")},
     ["--replay"], 0, "声明未发现问题时重放档也应通过"),

    # --- 位置可核实性（幻觉定位） --------------------------------------------
    # 一条发现可以在「命令能跑、重放一致」的同时，把位置指向一个根本不存在的
    # 文件与行号。这是唯一能纯机械判定的语义缺口，所以不该只靠人看。位置校验
    # 是提醒（--strict 下计为不合格），因为报告可以合法引用 --workdir 之外的路径。
    ("location_missing_file",
     location_report("src/ghost.py:12", ["src/real.py"]),
     [], 0, "默认档下位置文件不存在只是提醒，不改变退出码"),
    ("location_missing_file_strict",
     location_report("src/ghost.py:12", ["src/real.py"]),
     ["--strict"], 1, "--strict 下幻想出来的位置必须被拦"),
    ("location_line_out_of_range",
     location_report("src/real.py:9999", ["src/real.py"]),
     ["--strict"], 1, "行号超出文件总行数必须被拦"),
    ("location_line_in_range",
     location_report("src/real.py:2", ["src/real.py"]),
     ["--strict"], 0, "位置真实且行号在范围内时 --strict 也应通过"),
    ("location_no_slash_code_file",
     location_report("real.py:1", ["real.py"]),
     ["--strict"], 0, "不带目录的代码文件名也要能解析（相对 workdir 解析）"),
    ("location_non_code_extension",
     location_report("notes.txt:3", []),
     ["--strict"], 0, "非代码后缀不参与位置校验，避免误伤文档类审查"),
    # 位置解析的三个真实缺陷（独立审查发现并复现过）：
    # 1) 盘符被当成路径内容 -> 绝对路径被误判不存在
    # 2) 含空格路径被截断 -> 真实文件被误判不存在
    # 3) 只看第一个匹配 -> 前置一个非代码后缀即可整体绕过校验
    ("location_with_spaces",
     location_report("src/my dir/a b.py:1", ["src/my dir/a b.py"]),
     ["--strict"], 0, "含空格的路径必须能正确解析（截断会误杀真实文件）"),
    ("location_non_code_first_bypass",
     location_report("notes.txt:3 src/ghost.py:1", ["src/real.py"]),
     ["--strict"], 1, "非代码后缀写在前面时，后面的代码路径仍须被校验"),
    ("location_multi_file_any_resolves",
     location_report("notes.txt:3 src/real.py:1", ["src/real.py"]),
     ["--strict"], 0, "多文件位置中任一个真实存在即算位置成立"),
    ("location_url_is_not_a_path",
     location_report("见 https://example.com/x/a.py:5", []),
     ["--strict"], 0, "URL 不是被指控的文件，不应报「文件不存在」"),

    # --- 反向前置（修复前必须失败） ------------------------------------------
    # 这是堵住「恒真命令当实测」「命令与发现无关」的机械办法：一条声称有缺陷的
    # 发现，必须给出一个「在有缺陷的代码上会失败」的命令，且退出码非零。
    # 证据文件记的是 0，就说明命令通过了 —— 缺陷不成立。
    ("red_exit_zero",
     dict(red_report('python -c "print(1)"', repro='python -c "print(\'checked=1\')"'), **{"ev/F1R.txt": b"[exit code: 0]\nchecked=1\n", "ev/R1.txt": base64.b64decode("W2V4aXQgY29kZTogMF0Kb2sK")}),
     [], 1, "反向前置证据是 exit 0：命令在缺陷代码上通过了，缺陷不成立"),
    ("red_exit_nonzero",
     dict(red_report('python -c "import sys;sys.exit(1)"', repro='python -c "print(\'checked=1\')"'), **{"ev/F1R.txt": b"[exit code: 0]\nchecked=1\n", "ev/R1.txt": base64.b64decode("W2V4aXQgY29kZTogMV0KQXNzZXJ0aW9uRXJyb3I6IGV4cGVjdGVkIDQyLCBnb3QgNDEK")}),
     [], 0, "反向前置证据是失败的退出码：缺陷被观察到失败，通过"),
    ("red_missing_evidence",
     red_report('python -c "import sys;sys.exit(1)"', repro='python -c "print(\'checked=1\')"', evidence_path="ev/nope.txt"),
     ["--strict"], 1, "有反向前置命令但没有落盘证据，--strict 下不合格"),
    ("red_absent_strict",
     dict(red_report(None, repro='python -c "print(\'checked=1\')"'),
          **{"ev/F1R.txt": b"[exit code: 0]\nchecked=1\n"}),
     ["--strict"], 1, "完全没有反向前置字段，--strict 下必须因这条提醒判不合格"),
    ("red_absent_default",
     dict(red_report(None, repro='python -c "print(\'checked=1\')"'),
          **{"ev/F1R.txt": b"[exit code: 0]\nchecked=1\n"}),
     [], 0, "默认档下缺少反向前置只是提醒，不改变退出码"),
    ("red_warning_counted_under_strict",
     dict(red_report(None, repro='python -c "print(\'checked=1\')"'),
          **{"ev/F1R.txt": b"[exit code: 0]\nchecked=1\n"}),
     ["--strict"], 1,
     "位置合法、无其他问题，唯缺反向前置时 --strict 仍须拦住（锁死提醒计数 bug）"),
    ("red_cannot_run",
     red_report("未能执行：这个缺陷只能靠读代码看出来", repro='python -c "print(\'checked=1\')"'),
     [], 1, "反向前置不接受「未能执行」——这一行必须是能跑的命令"),
    ("red_pre_fix_reproduces",
     dict(red_report('python -c "import sys;sys.exit(3)"', repro='python -c "print(\'checked=1\')"'), **{"ev/F1R.txt": b"[exit code: 0]\nchecked=1\n", "ev/R1.txt": base64.b64decode("W2V4aXQgY29kZTogM10KZmFpbGVkCg==")}),
     ["--pre-fix"], 0, "--pre-fix 档：命令现在仍然失败，缺陷被复现，通过"),
    ("red_pre_fix_already_green",
     dict(red_report('python -c "print(2)"', repro='python -c "print(\'checked=1\')"'),
          **{"ev/F1R.txt": b"[exit code: 0]\nchecked=1\n", "ev/R1.txt": base64.b64decode("W2V4aXQgY29kZTogMV0Kc3RhbGUgZmFpbHVyZSBmcm9tIGJlZm9yZSB0aGUgZml4Cg==")}),
     ["--pre-fix"], 1, "--pre-fix 档：命令这次通过了，缺陷无法复现，必须拦下"),
    ("red_pre_fix_no_red",
     red_report(None, repro='python -c "print(\'checked=1\')"'),
     ["--pre-fix"], 1, "--pre-fix 档下没有反向前置就无从核实缺陷是否存在"),
    ("red_replay_conflict",
     dict(red_report('python -c "import sys;sys.exit(1)"', repro='python -c "print(\'checked=1\')"'), **{"ev/F1R.txt": b"[exit code: 0]\nchecked=1\n", "ev/R1.txt": base64.b64decode("W2V4aXQgY29kZTogMV0KYm9vbQo=")}),
     ["--pre-fix", "--replay"], 2, "--pre-fix 与 --replay 互斥，用法错误退 2"),
    ("red_refused_command",
     dict(red_report("rm -rf build/ --dry-run", repro='python -c "print(\'checked=1\')"'),
          **{"ev/F1R.txt": b"[exit code: 0]\nchecked=1\n", "ev/R1.txt": base64.b64decode("W2V4aXQgY29kZTogMV0KYm9vbQo=")}),
     ["--pre-fix"], 1, "反向前置的命令同样受拒绝表约束，不得执行"),

    # --- 先红后绿的「绿半边」--------------------------------------------------
    # --replay 除比对复现证据外，还重跑反向前置命令并要求它**已经通过**。它抓的是
    # 「修完之后前置命令仍然失败」——修复没完成，或前置命令与那条缺陷无关。
    ("replay_red_still_failing",
     dict(red_report('python -c "import sys;sys.exit(1)"', repro='python -c "print(\'checked=1\')"'), **{"ev/F1R.txt": b"[exit code: 0]\nchecked=1\n", "ev/R1.txt": base64.b64decode("W2V4aXQgY29kZTogMV0KYm9vbQo=")}),
     ["--replay"], 1, "--replay 档：修完之后反向前置仍然失败，说明修复没完成或前置命令无关"),
    ("replay_red_now_green",
     dict(red_report('python -c "print(2)"', repro='python -c "print(\'checked=1\')"'), **{"ev/F1R.txt": b"[exit code: 0]\nchecked=1\n", "ev/R1.txt": base64.b64decode("W2V4aXQgY29kZTogMV0KYm9vbQo=")}),
     ["--replay"], 0, "--replay 档：复现一致且前置命令已转绿，先红后绿成立"),
    ("replay_without_red",
     dict(location_report("src/real.py:1", ["src/real.py"], red=False),
          **{"ev/F1.txt": b"[exit code: 0]\n"}),
     ["--replay", "--strict"], 1,
     "没有反向前置时 --replay 只验了绿半边，--strict 下必须提示补前置命令"),

    # --- 交接文档与对抗性复审（模式 C） ---------------------------------------
    # 交接文档是「执行者写给审查者的有限情报」：已定取舍必须带出处，否则
    # 执行者可以拿它自由封口，这套门禁的信誉就没了。无出处只提醒。
    ("handoff_ok",
     handoff_files(HANDOFF_OK, good_report_files()),
     ["--strict", "--handoff", ".review-handoff.md"], 0,
     "取舍带出处、字段齐全时 --strict 也应通过"),
    ("handoff_missing_provenance",
     handoff_files(HANDOFF_NO_PROVENANCE, good_report_files()),
     ["--strict", "--handoff", ".review-handoff.md"], 1,
     "取舍条目缺出处（HumanDecision/RecordedDecision/OrchestratorClaim）时 --strict 必须拦"),
    ("handoff_missing_provenance_default",
     handoff_files(HANDOFF_NO_PROVENANCE, good_report_files()),
     ["--handoff", ".review-handoff.md"], 0,
     "默认档下缺出处只是提醒，不改变退出码"),
    ("handoff_no_tradeoffs",
     handoff_files("# 审查交接文档\n\n## 范围\n- 工作目录：`C:\\\\work`\n\n"
                   "## 已定取舍\n\n## 已驳回的发现\n",
                   good_report_files()),
     ["--strict", "--handoff", ".review-handoff.md"], 1,
     "「已定取舍」小节为空时必须拦下，否则它只是一句「别管」"),
    ("handoff_missing_tradeoffs_section",
     handoff_files("# 审查交接文档\n\n## 范围\n- 工作目录：`C:\\\\work`\n",
                   good_report_files()),
     ["--strict", "--handoff", ".review-handoff.md"], 1,
     "缺「## 已定取舍」必须拦下——空小节与整个小节缺失是两种情况，都要覆盖"),
    ("handoff_only_scope_no_tradeoffs_section",
     handoff_files("# 审查交接文档\n\n## 范围\n- 工作目录：`C:\\\\work`\n\n"
                   "## 已驳回的发现\n- F1 某发现 | 驳回理由：不成立\n",
                   good_report_files()),
     ["--strict", "--handoff", ".review-handoff.md"], 1,
     "只缺「## 已定取舍」而其他小节都在时必须拦下：这条夹具让「缺小节」独立生效，"
     "不被「取舍小节为空」那条检查兜底（定向变异 M5 的克星）"),
    # --- 第 3 轮独立审查（F1/F2/F5/F6/F9）发现的真实缺陷 ----------------------
    ("handoff_missing_scope_section",
     handoff_files("# 审查交接文档\n\n## 已定取舍\n"
                   "- 归一化保守 | 依据：HumanDecision：真人要求 | 影响边界：只产生假不一致\n",
                   good_report_files()),
     ["--strict", "--handoff", ".review-handoff.md"], 1,
     "F1：缺「## 范围」时不能算「必需小节都在」——命中任一小节就放行是 OR 的错"),
    ("handoff_negated_provenance",
     handoff_files("# 审查交接文档\n\n## 范围\n- 工作目录：`C:\\\\work`\n\n"
                   "## 已定取舍\n- 不要报假不一致 | 依据：未经 HumanDecision 确认，"
                   "是本轮执行者自行决定 | 影响边界：无\n",
                   good_report_files()),
     ["--strict", "--handoff", ".review-handoff.md"], 1,
     "F2：写「未经 HumanDecision 确认」不能算有出处——子串匹配把否定当成了肯定"),
    ("handoff_provenance_needs_basis_label",
     handoff_files("# 审查交接文档\n\n## 范围\n- 工作目录：`C:\\\\work`\n\n"
                   "## 已定取舍\n- 某取舍 | 影响边界：HumanDecision 这事我们讨论过\n",
                   good_report_files()),
     ["--strict", "--handoff", ".review-handoff.md"], 1,
     "F2：出处必须出现在「依据：」之后，散落在影响边界里的标记不算"),
    ("handoff_ok_still_passes",
     handoff_files(HANDOFF_OK, good_report_files()),
     ["--strict", "--handoff", ".review-handoff.md"], 0,
     "修 F1/F2 之后，合规的交接文档仍须通过（防过度收紧）"),
    ("falsify_vacuous_report",
     {".review-handoff.md": HANDOFF_ADVERSARIAL.encode("utf-8"),
      "report.md": ("### 对抗性复审 · 目标：上一轮\n\n## 我确认成立的\n"
                    "- 逐条复核完毕 · 判定：成立\n\n## 我驳倒的\n"
                    "- 上轮结论有误 · 判定：驳回\n\n## 未决\n"
                    "- 有几条没能本地验证\n").encode("utf-8")},
     ["--falsify", "--handoff", ".review-handoff.md", "--strict"], 1,
     "F5：不点名任何一条旧发现、也没有出处的空洞报告不能算通过"),
    # extras 里不要放 "report.md"：harness 会在末尾再拼一次报告路径，
    # 于是门禁看到两个位置参数、走「用法错误退 2」——期望值恰好也是 2，
    # 这条断言就变成无论如何都绿（第 3 轮审查 F4 的根因）。
    ("falsify_requires_handoff_flag",
     {".review-handoff.md": HANDOFF_ADVERSARIAL.encode("utf-8"),
      "report.md": FALSIFY_OK.encode("utf-8")},
     ["--falsify"], 2,
     "--falsify 必须同时给出 --handoff（否则第二轮不知道第一轮是什么）",
     "必须同时给出 --handoff"),
    ("falsify_ignores_replay",
     {".review-handoff.md": HANDOFF_ADVERSARIAL.encode("utf-8"),
      "report.md": FALSIFY_OK.encode("utf-8")},
     ["--falsify", "--replay", "--handoff", ".review-handoff.md"], 2,
     "F6：--falsify 与 --replay 同给必须退 2，不能静默吞掉"),
    ("falsify_ignores_pre_fix",
     {".review-handoff.md": HANDOFF_ADVERSARIAL.encode("utf-8"),
      "report.md": FALSIFY_OK.encode("utf-8")},
     ["--falsify", "--pre-fix", "--handoff", ".review-handoff.md"], 2,
     "F6：--falsify 与 --pre-fix 同给必须退 2，不能静默吞掉"),
    # 顺序要把「实测」放在最前：若证据行后面紧跟的是以反引号开头的标签，
    # 字段解析会不认它，把后续行吞进证据值（F9 的更深一层）。
    ("evidence_path_with_annotation",
     dict(good_report_files(),
          **{"report.md": ("### F1 带注解的证据路径 · 严重度：高\n"
                           "- 位置：src/real.py:1\n"
                           "- 实测：见证据文件\n"
                           "- 复现：python -c \"print('checked=1')\"\n"
                           "- 证据文件：`ev/F1.txt`（原始输出，未摘录）\n"
                           "- 反向前置：python -c \"import sys;sys.exit(0)\"\n"
                           "- 反向前置证据：`ev/R1.txt`（首行 [exit code: 1]）\n").encode("utf-8")}),
     ["--replay", "--strict"], 0,
     "F9：路径用 inline code 且后面跟注解时必须能解析，不能判「证据文件读不了」"),
    ("handoff_file_missing",
     good_report_files(),
     ["--handoff", ".review-handoff.md"], 2,
     "指定的交接文档不存在属用法错误，退 2"),
    ("falsify_ok",
     {".review-handoff.md": HANDOFF_ADVERSARIAL.encode("utf-8"),
      "report.md": FALSIFY_OK.encode("utf-8")},
     ["--falsify", "--handoff", ".review-handoff.md", "--strict"], 0,
     "对抗性复审报告分段齐全、每条带判定后缀时通过"),
    ("falsify_no_verdict_headings",
     {".review-handoff.md": HANDOFF_ADVERSARIAL.encode("utf-8"),
      "report.md": FALSIFY_NO_HEADINGS.encode("utf-8")},
     ["--falsify", "--handoff", ".review-handoff.md", "--strict"], 1,
     "对抗性复审必须分「确认成立 / 驳倒 / 未决」，否则无法判断它做了什么"),
    ("falsify_missing_undecided_section",
     {".review-handoff.md": HANDOFF_ADVERSARIAL.encode("utf-8"),
      "report.md": falsify_body(omit_undecided=True).encode("utf-8")},
     ["--falsify", "--handoff", ".review-handoff.md", "--strict"], 1,
     "缺「## 未决」也必须拦下——「没提」和「确认无未决」是两件事"),
    ("falsify_section_without_finding_ref",
     {".review-handoff.md": HANDOFF_ADVERSARIAL.encode("utf-8"),
      "report.md": falsify_body(confirmed="- 逐条复核完毕 · 严重度：高").encode("utf-8")},
     ["--falsify", "--handoff", ".review-handoff.md", "--strict"], 1,
     "判决必须落到具体发现编号上，泛泛一句「复核完毕」不算"),
    ("red_command_too_short",
     dict(red_report("echo x", repro='python -c "print(\'checked=1\')"'),
          **{"ev/F1R.txt": b"[exit code: 0]\nchecked=1\n"}),
     ["--strict"], 1,
     "「反向前置」短到无法照抄执行时必须拦下（这条规则此前没有任何断言覆盖）"),
    ("red_same_as_repro",
     dict(red_report("同上", repro='python -c "print(\'checked=1\')"'),
          **{"ev/F1R.txt": b"[exit code: 0]\nchecked=1\n"}),
     ["--strict"], 0,
     "「反向前置：同上」是合理写法——指同一条命令，不该被判「太短」（第 3 轮报告的 F7/F8 就是这样被误杀的）"),
    ("falsify_unmarked_claim",
     {".review-handoff.md": HANDOFF_ADVERSARIAL.encode("utf-8"),
      "report.md": ("### 对抗性复审\n\n## 我确认成立的\n"
                    "- F1 这个问题是成立的\n").encode("utf-8")},
     ["--falsify", "--handoff", ".review-handoff.md", "--strict"], 1,
     "每条判定必须带「· 严重度：」或「· 判定：」后缀，便于逐条核对"),

    # --- 模式 C 的开关（不许偷偷升级到多轮） ----------------------------------
    ("falsify_requires_adversarial_mode",
     handoff_files(HANDOFF_OK, good_report_files(), mode=MODE_ROUND1),
     ["--falsify", "--handoff", ".review-handoff.md", "--strict"], 2,
     "交接文档声明「首轮」时不得跑 --falsify：多轮必须由人先确认"),
    ("falsify_with_adversarial_mode",
     adversarial_files(FALSIFY_OK),
     ["--falsify", "--handoff", ".review-handoff.md", "--strict"], 0,
     "声明「首轮 + 对抗性复审（用户已确认）」且报告合规时 --falsify 通过"),
    ("falsify_without_mode_declaration",
     handoff_files(HANDOFF_OK, good_report_files(), mode=None),
     ["--falsify", "--handoff", ".review-handoff.md", "--strict"], 2,
     "没有模式声明行时不得跑 --falsify（旧文档也不行）"),

    # --- 围栏代码块不得计入小节判定（第 4 轮对抗性复审） ----------------------
    ("handoff_section_only_in_fence",
     handoff_files("# 审查交接文档\n\n## 已定取舍\n"
                   "- 归一化保守 | 依据：HumanDecision：真人要求 | 影响边界：只产生假不一致\n\n"
                   "```markdown\n## 范围\n- 工作目录：/x\n```\n",
                   good_report_files()),
     ["--strict", "--handoff", ".review-handoff.md"], 1,
     "「## 范围」只出现在围栏示例里，不算有这个必需小节"),
    ("falsify_sections_only_in_fence",
     {".review-handoff.md": ("# 审查交接文档\n\n" + MODE_ADVERSARIAL
                             + "\n\n## 范围\n- 工作目录：/x\n\n## 已定取舍\n"
                             "- x | 依据：HumanDecision：真人要求 | 影响边界：y\n").encode("utf-8"),
      "report.md": ("### 对抗性复审\n\n```markdown\n## 我确认成立的\n"
                    "- F1 某问题 · 严重度：高\n\n## 我驳倒的\n- F2 某结论 · 判定：驳回\n\n"
                    "## 未决\n- 无\n```\n").encode("utf-8")},
     ["--falsify", "--handoff", ".review-handoff.md", "--strict"], 1,
     "三段只出现在围栏示例里的对抗性复审报告必须被拦下"),

    # --- 编号与中文相邻时也要认得出（第 4 轮对抗性复审的假失败） --------------
    ("falsify_finding_ref_adjacent_cjk",
     {".review-handoff.md": ("# 审查交接文档\n\n" + MODE_ADVERSARIAL
                             + "\n\n## 范围\n- 工作目录：/x\n\n## 已定取舍\n"
                             "- x | 依据：HumanDecision：真人要求 | 影响边界：y\n").encode("utf-8"),
      "report.md": ("### 对抗性复审 · 目标：上一轮（3 条）\n\n"
                    "## 我确认成立的\n- F1这个问题确实存在 · 严重度：高\n\n"
                    "## 我驳倒的\n- F2这条上轮报错了 · 严重度：低\n\n"
                    "## 未决\n- F9涉及 CI 行为\n").encode("utf-8")},
     ["--falsify", "--handoff", ".review-handoff.md", "--strict"], 0,
     "F1这个问题（中文紧跟编号）必须认得出，不能误判「没有点名任何发现」"),

    # --- 证据路径：注解里出现反引号时不能劫持路径 ------------------------------
    ("evidence_path_note_has_ticks",
     dict(good_report_files(),
          **{"report.md": ("### F1 注解里还有反引号 · 严重度：高\n"
                           "- 位置：src/real.py:1\n"
                           "- 实测：见证据文件\n"
                           "- 复现：python -c \"print('checked=1')\"\n"
                           "- 证据文件：ev/F1.txt（同 `probe.log` 那份）\n"
                           "- 反向前置：python -c \"import sys;sys.exit(0)\"\n"
                           "- 反向前置证据：ev/R1.txt（首行 [exit code: 1]）\n").encode("utf-8")}),
     ["--replay", "--strict"], 0,
     "注解里的反引号（`probe.log`）不得劫持真正的证据路径 ev/F1.txt"),

    # --- 用法 ---------------------------------------------------------------
    ("unknown_option", {"report.md": GOOD.encode("utf-8")}, ["--nope"], 2,
     "未知选项退 2"),
]


def run_case(root, name, files, extras):
    case_dir = os.path.join(root, name)
    os.makedirs(case_dir, exist_ok=True)
    for relative, payload in files.items():
        path = os.path.join(case_dir, relative)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(payload)
    report = os.path.join(case_dir, "report.md")
    command = [sys.executable, GATE] + extras + [report]
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode, proc.stdout, proc.stderr


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    only = set()
    skip_harness = False
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--only":
            index += 1
            if index >= len(argv):
                sys.stderr.write("--only 需要一个用例名\n")
                return 2
            only.add(argv[index])
        elif item == "--skip-harness":
            skip_harness = True
        else:
            sys.stderr.write("unknown option: " + item + "\n")
            sys.stderr.write("usage: test_check_review_report.py "
                             "[--only NAME]... [--skip-harness]\n")
            return 2
        index += 1

    root = tempfile.mkdtemp(prefix="fresh-eyes-review-tests-")
    red = 0
    total = 0
    try:
        for case in CASES:
            name, files, extras, expected, why = case[:5]
            expect_stderr = case[5] if len(case) > 5 else None
            if only and name not in only:
                continue
            total += 1
            try:
                code, out, err = run_case(root, name, files, extras)
            except Exception as error:  # pragma: no cover - harness failure
                red += 1
                print("[ RED ] " + name + "  跑不起来: " + str(error))
                continue
            err_text = err.decode("utf-8", "replace")
            if code == expected and (expect_stderr is None or expect_stderr in err_text):
                print("[GREEN] " + name + "  exit=" + str(code))
            else:
                red += 1
                text = (out + err).decode("utf-8", "replace").strip().splitlines()
                tail = text[-1] if text else "(无输出)"
                print("[ RED ] " + name + "  期望 exit=" + str(expected)
                      + "，实得 exit=" + str(code))
                print("        为什么该红: " + why)
                if expect_stderr is not None and expect_stderr not in err_text:
                    print("        stderr 里没有: " + expect_stderr)
                print("        末行输出: " + tail)

        # The two hand-written cases below are the slow part (they always spawn
        # the gate), so --only can skip them. Full runs of course keep them.
        if not skip_harness:
            total += 1
            missing = os.path.join(root, "does-not-exist.md")
            proc = subprocess.run([sys.executable, GATE, missing],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode == 2:
                print("[GREEN] missing_file  exit=2")
            else:
                red += 1
                print("[ RED ] missing_file  期望 exit=2，实得 exit=" + str(proc.returncode))

            total += 1
            proc = subprocess.run([sys.executable, GATE],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode == 2:
                print("[GREEN] no_args  exit=2")
            else:
                red += 1
                print("[ RED ] no_args  期望 exit=2，实得 exit=" + str(proc.returncode))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("")
    scope = "" if not only else "（只跑 " + str(len(only)) + " 个指定用例）"
    print("共 " + str(total) + " 条断言，变红 " + str(red) + " 条。" + scope)
    if red:
        print("结论：门禁的行为与文档不符 —— 先修脚本，不要依赖它的退出码。")
        return 1
    print("结论：全绿 —— 门禁行为与断言一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
