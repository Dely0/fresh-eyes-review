# -*- coding: utf-8 -*-
import io, os, subprocess, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

P, G = sys.argv[1], sys.argv[2]

REPORT = """### F1 兜底报告 · 严重度：高
- 位置：src/real.py:1
- 复现：python -c "print('checked=1')"
- 证据文件：ev/F1.txt
- 反向前置：python -c "import sys;sys.exit(1)"
- 反向前置证据：ev/R1.txt
- 实测：见证据文件
"""

HANDOFF_OK = """# 交接文档

## 范围
- 工作目录：`C:\\work`

## 已定取舍
- 只支持 Markdown | 依据：HumanDecision：真人拍板 | 影响边界：不支持 JSON
"""

CASES = {
 # both required sections, but every trade-off item is a numbered list (no provenance)
 "p1_numbered_mixed": ("""# 交接文档

## 范围
- 工作目录：`C:\\work`

## 已定取舍
1. 归一化只折叠十类 token，无出处
2. 只支持 Markdown | 依据：HumanDecision：真人拍板
""", REPORT, ["--strict"]),
 # valid report + handoff missing provenance, default (non-strict) -> warns only
 "p2_handoff_default": ("""# 交接文档

## 范围
- 工作目录：`C:\\work`

## 已定取舍
- 归一化只折叠十类 token，无出处
""", REPORT, []),
 # report has one warning (no severity) + handoff has 1 warning -> count 1 or 2?
 "p6_double_count": ("""# 交接文档

## 范围
- 工作目录：`C:\\work`

## 已定取舍
- 归一化只折叠十类 token，无出处
""", """### F1 没写严重度的问题
- 位置：src/real.py:1
- 复现：python -c "print('checked=1')"
- 证据文件：ev/F1.txt
- 反向前置：python -c "import sys;sys.exit(1)"
- 反向前置证据：ev/R1.txt
- 实测：见证据文件
""", ["--strict"]),
 # falsify: only 未决 present
 "p3_falsify_one_section": (HANDOFF_OK, "## 未决\n- F9 无法验证\n", ["--falsify", "--strict"]),
 # falsify: all three present but whole report is one line of heading only
 "p4_falsify_empty_sections": (HANDOFF_OK, "## 我确认成立的\n## 我驳倒的\n## 未决\n", ["--falsify", "--strict"]),
 # falsify with a handoff that itself has no provenance, strict
 "p5_falsify_handoff_warn": ("""# 交接文档

## 范围
- 工作目录：`C:\\work`

## 已定取舍
- 归一化只折叠十类 token，无出处
""", """## 我确认成立的
- F1 成立 · 严重度：高
## 我驳倒的
- F7 不成立 · 严重度：低
## 未决
- F9 无法验证
""", ["--falsify", "--strict"]),
 # falsify: claim bullets carry provenance words? try totally unmarked body with no bullets
 "p7_falsify_prose_only": (HANDOFF_OK, "## 我确认成立的\n我确认 F1 成立。\n## 我驳倒的\n我驳倒 F7。\n## 未决\nF9。\n", ["--falsify", "--strict"]),
}
for name, (handoff, report, extra) in CASES.items():
    d = os.path.join(P, name)
    os.makedirs(os.path.join(d, "src"), exist_ok=True)
    os.makedirs(os.path.join(d, "ev"), exist_ok=True)
    open(os.path.join(d, "src", "real.py"), "w").write("x = 1\n")
    open(os.path.join(d, ".review-handoff.md"), "w", encoding="utf-8").write(handoff)
    open(os.path.join(d, "report.md"), "w", encoding="utf-8").write(report)
    open(os.path.join(d, "ev", "F1.txt"), "w").write("[exit code: 0]\nchecked=1\n")
    open(os.path.join(d, "ev", "R1.txt"), "w").write("[exit code: 1]\nfail\n")
    argv = [sys.executable, G] + extra + ["--handoff", ".review-handoff.md", "report.md"]
    p = subprocess.run(argv, cwd=d, capture_output=True)
    print("=" * 70)
    print("CASE", name, "-> exit", p.returncode)
    print(p.stdout.decode("utf-8", "replace").rstrip())
    err = p.stderr.decode("utf-8", "replace").rstrip()
    if err:
        print("STDERR:", err)
