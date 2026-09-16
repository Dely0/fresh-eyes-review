# -*- coding: utf-8 -*-
"""Evidence probe: a handoff document that has NO `## 范围` heading is still
accepted by check_handoff(), because the required-section test is an OR
(`any(section in heading ...)`) instead of an AND.

Prints F1_STILL_ACCEPTED and exits 1 when the gate accepts it (defect present).
"""
import os, subprocess, sys, tempfile

GATE = sys.argv[1]

HANDOFF_NO_SCOPE = """# 审查交接文档

## 已定取舍
- 归一化只折叠十类 token | 依据：HumanDecision：真人要求保守 | 影响边界：假不一致升级给人
"""

REPORT = """### F1 兜底 · 严重度：高
- 位置：src/real.py:1
- 复现：python -c "print('checked=1')"
- 证据文件：ev/F1.txt
- 反向前置：python -c "import sys;sys.exit(1)"
- 反向前置证据：ev/R1.txt
- 实测：见证据文件
"""


def main():
    d = tempfile.mkdtemp(prefix="fer-h1-")
    os.makedirs(os.path.join(d, "src"))
    os.makedirs(os.path.join(d, "ev"))
    open(os.path.join(d, "src", "real.py"), "w").write("x = 1\n")
    open(os.path.join(d, ".review-handoff.md"), "w", encoding="utf-8").write(HANDOFF_NO_SCOPE)
    open(os.path.join(d, "report.md"), "w", encoding="utf-8").write(REPORT)
    open(os.path.join(d, "ev", "F1.txt"), "w").write("[exit code: 0]\nchecked=1\n")
    open(os.path.join(d, "ev", "R1.txt"), "w").write("[exit code: 1]\nfail\n")
    proc = subprocess.run(
        [sys.executable, GATE, "--strict", "--handoff", ".review-handoff.md", "report.md"],
        cwd=d, capture_output=True)
    print(proc.stdout.decode("utf-8", "replace").rstrip())
    print("gate exit=" + str(proc.returncode))
    if proc.returncode == 0:
        print("F1_STILL_ACCEPTED: 交接文档没有 ## 范围 小节，--strict 下仍然通过")
        return 1
    print("F1_REJECTED: 缺 ## 范围 的交接文档被拦下了")
    return 0


sys.exit(main())
