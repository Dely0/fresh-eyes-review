# -*- coding: utf-8 -*-
"""Evidence probe: the `--falsify` path validates only section *headings* and
marker *presence*. A second-round report that never names a single round-one
finding still exits 0 under --strict, and the gate prints
「分段齐全，每条判定都标了出处」.

Exits 1 while the gate accepts a report with no per-finding verdicts.
"""
import os, subprocess, sys, tempfile

GATE = sys.argv[1]

HANDOFF = """# 审查交接文档

## 范围
- 工作目录：`C:\\work\\repo`

## 已定取舍
- 只支持 Markdown | 依据：HumanDecision：真人拍板 | 影响边界：不支持 JSON
"""

EMPTY_SECTIONS = "## 我确认成立的\n## 我驳倒的\n## 未决\n"

POST_HOC = """## 我确认成立的
- 逐条复核完毕 · 判定：成立
## 我驳倒的
- 上轮结论有误 · 判定：驳回
## 未决
- 有几条没能本地验证
"""

REPORT = """### F1 兜底 · 严重度：高
- 位置：src/real.py:1
- 复现：python -c "print('checked=1')"
- 证据文件：ev/F1.txt
- 反向前置：python -c "import sys;sys.exit(1)"
- 反向前置证据：ev/R1.txt
- 实测：见证据文件
"""


def run(root, name, round2, workdir_has_report=True):
    d = os.path.join(root, name)
    os.makedirs(os.path.join(d, "src"))
    os.makedirs(os.path.join(d, "ev"))
    open(os.path.join(d, ".review-handoff.md"), "w", encoding="utf-8").write(HANDOFF)
    open(os.path.join(d, "src", "real.py"), "w").write("x = 1\n")
    open(os.path.join(d, "ev", "F1.txt"), "w").write("[exit code: 0]\nchecked=1\n")
    open(os.path.join(d, "ev", "R1.txt"), "w").write("[exit code: 1]\nfail\n")
    if workdir_has_report:
        open(os.path.join(d, "report.md"), "w", encoding="utf-8").write(REPORT)
    open(os.path.join(d, "round2.md"), "w", encoding="utf-8").write(round2)
    proc = subprocess.run(
        [sys.executable, GATE, "--falsify", "--strict",
         "--handoff", ".review-handoff.md", "round2.md"],
        cwd=d, capture_output=True)
    return proc.returncode, proc.stdout.decode("utf-8", "replace").rstrip()


def main():
    root = tempfile.mkdtemp(prefix="fer-f4-")
    bad = 0
    for name, round2 in (("empty_sections", EMPTY_SECTIONS), ("post_hoc", POST_HOC)):
        code, out = run(root, name, round2)
        print("=" * 70)
        print("CASE " + name + " -> exit " + str(code))
        print(out)
        if code == 0:
            bad += 1
    if bad:
        print("")
        print("F4_FALSIFY_VACUOUS_PASSES: " + str(bad) + " 份完全没有逐条判决的报告在 --strict 下通过")
        return 1
    print("F4_FALSIFY_VACUOUS_REJECTED")
    return 0


sys.exit(main())
