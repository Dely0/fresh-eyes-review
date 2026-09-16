# -*- coding: utf-8 -*-
"""Evidence probe: the three provenance markers are interchangeable to the gate.

check_handoff() accepts any of HumanDecision / RecordedDecision /
OrchestratorClaim with exactly the same weight, so an entry that honestly
declares itself an OrchestratorClaim (i.e. the orchestrator's own assertion,
not a human decision) is machine-identical to one that claims a HumanDecision.
The gate hands the author the more self-serving label for free.

Exits 1 when both labels produce the same --strict verdict.
"""
import os, subprocess, sys, tempfile

GATE = sys.argv[1]

REPORT = """### F1 兜底 · 严重度：高
- 位置：src/real.py:1
- 复现：python -c "print('checked=1')"
- 证据文件：ev/F1.txt
- 反向前置：python -c "import sys;sys.exit(1)"
- 反向前置证据：ev/R1.txt
- 实测：见证据文件
"""


def handoff(marker, cite):
    return ("# 审查交接文档\n\n## 范围\n- 工作目录：`C:\\work\\repo`\n\n"
            "## 已定取舍\n- 不要报归一化产生的假不一致 | 依据：" + marker
            + "：" + cite + " | 影响边界：无\n")


def main():
    root = tempfile.mkdtemp(prefix="fer-f7-")
    results = {}
    for name, body in (("orchestrator", handoff("OrchestratorClaim", "我（编排者）决定")),
                       ("human", handoff("HumanDecision", "我（编排者）决定"))):
        d = os.path.join(root, name)
        os.makedirs(os.path.join(d, "src"))
        os.makedirs(os.path.join(d, "ev"))
        open(os.path.join(d, ".review-handoff.md"), "w", encoding="utf-8").write(body)
        open(os.path.join(d, "report.md"), "w", encoding="utf-8").write(REPORT)
        open(os.path.join(d, "src", "real.py"), "w").write("x = 1\n")
        open(os.path.join(d, "ev", "F1.txt"), "w").write("[exit code: 0]\nchecked=1\n")
        open(os.path.join(d, "ev", "R1.txt"), "w").write("[exit code: 1]\nfail\n")
        proc = subprocess.run(
            [sys.executable, GATE, "--strict", "--handoff", ".review-handoff.md", "report.md"],
            cwd=d, capture_output=True)
        results[name] = proc.returncode
        print("marker=" + name + " -> gate exit " + str(proc.returncode))
    same = results["orchestrator"] == results["human"] == 0
    print("两种出处标注在 --strict 下退出码相同且都通过 = " + str(same))
    if same:
        print("F7_PROVENANCE_MARKERS_INTERCHANGEABLE: 自认「编排者自己的主张」与自称「真人决定」"
              "在门禁下不可区分，诚实标注没有任何成本")
        return 1
    print("F7_PROVENANCE_MARKERS_DISTINGUISHED")
    return 0


sys.exit(main())
