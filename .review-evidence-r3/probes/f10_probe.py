# -*- coding: utf-8 -*-
"""Evidence probe: a value written as inline code followed by a parenthetical
annotation is not cleaned by strip_ticks(), which only strips ticks when they
are the first and last characters of the whole value. The literal value
`path`（说明） is then used as the evidence path, so the gate reports
"证据文件不可用" and exits 1 on an otherwise fully compliant report.

The two variants differ ONLY by the trailing annotation.
Exits 1 when the annotated variant is judged unusable while the bare one passes.
"""
import os, subprocess, sys, tempfile

GATE = sys.argv[1]

TEMPLATE = """### F1 证据文件写法用例 · 严重度：高
- 位置：src/real.py:1
- 复现：python -c "print('checked=1')"
- 证据文件：{pointer}
- 反向前置：python -c "import sys;sys.exit(1)"
- 反向前置证据：ev/R1.txt
- 实测：见证据文件
"""


def main():
    root = tempfile.mkdtemp(prefix="fer-f10-")
    results = {}
    for name, pointer in (("bare", "`ev/F1.txt`"),
                          ("annotated", "`ev/F1.txt`（原始输出，未摘录）")):
        d = os.path.join(root, name)
        os.makedirs(os.path.join(d, "src"))
        os.makedirs(os.path.join(d, "ev"))
        open(os.path.join(d, "report.md"), "w", encoding="utf-8").write(
            TEMPLATE.format(pointer=pointer))
        open(os.path.join(d, "src", "real.py"), "w").write("x = 1\n")
        open(os.path.join(d, "ev", "F1.txt"), "w").write("[exit code: 0]\nchecked=1\n")
        open(os.path.join(d, "ev", "R1.txt"), "w").write("[exit code: 1]\nfail\n")
        proc = subprocess.run([sys.executable, GATE, "report.md"], cwd=d, capture_output=True)
        results[name] = proc.returncode
        print("### 证据文件 值 = " + pointer + " -> exit " + str(proc.returncode))
        print(proc.stdout.decode("utf-8", "replace").rstrip())
        print("")

    if results["bare"] == 0 and results["annotated"] == 1:
        print("F10_ANNOTATED_POINTER_MISJUDGED: 两份报告唯一差别是括注，"
              "裸写法退 0、带括注退 1 —— 合法写法被误杀")
        return 1
    print("F10_ANNOTATED_POINTER_OK: bare=" + str(results["bare"])
          + " annotated=" + str(results["annotated"]))
    return 0


sys.exit(main())
