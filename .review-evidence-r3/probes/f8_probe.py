# -*- coding: utf-8 -*-
"""Evidence probe: README's exit-code table claims a non-compliant handoff
document exits 1, with no qualification; the implementation only *warns* about
a missing provenance marker in the default (non-strict) mode.

Asserts:
  (a) the implementation exits 0 (warning only) for a handoff whose trade-off
      entry has no provenance;
  (b) README's exit-code line for code 1 mentions the handoff document but not
      the default-only reminder.
Exits 1 when README is wrong about the default mode.
"""
import os, subprocess, sys, tempfile

REPO = r"C:\Users\dupenglai\.dsh\tmp\fer-repo"
GATE = os.path.join(REPO, "fresh-eyes-review", "scripts", "check_review_report.py")

HANDOFF_NO_PROVENANCE = """# 审查交接文档

## 范围
- 工作目录：`C:\\work\\repo`

## 已定取舍
- 归一化只折叠十类已知易变 token | 影响边界：未被识别的易变内容会产生假不一致
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
    d = tempfile.mkdtemp(prefix="fer-f8-")
    os.makedirs(os.path.join(d, "src"))
    os.makedirs(os.path.join(d, "ev"))
    open(os.path.join(d, ".review-handoff.md"), "w", encoding="utf-8").write(HANDOFF_NO_PROVENANCE)
    open(os.path.join(d, "report.md"), "w", encoding="utf-8").write(REPORT)
    open(os.path.join(d, "src", "real.py"), "w").write("x = 1\n")
    open(os.path.join(d, "ev", "F1.txt"), "w").write("[exit code: 0]\nchecked=1\n")
    open(os.path.join(d, "ev", "R1.txt"), "w").write("[exit code: 1]\nfail\n")

    default = subprocess.run(
        [sys.executable, GATE, "--handoff", ".review-handoff.md", "report.md"],
        cwd=d, capture_output=True)
    strict = subprocess.run(
        [sys.executable, GATE, "--strict", "--handoff", ".review-handoff.md", "report.md"],
        cwd=d, capture_output=True)
    out = default.stdout.decode("utf-8", "replace").rstrip()
    print("默认档输出：")
    print(out)
    print("默认档 exit=" + str(default.returncode) + "  --strict exit=" + str(strict.returncode))

    readme = open(os.path.join(REPO, "README.md"), encoding="utf-8").read().splitlines()
    line1 = [l for l in readme if l.startswith("| `1` |")][0]
    print("")
    print("README 退出码 1 行：")
    print(line1)
    mentions_handoff = "交接文档" in line1
    mentions_default_reminder = "提醒" in line1
    print("该行提到交接文档 = " + str(mentions_handoff)
          + "；该行说明「默认只提醒」= " + str(mentions_default_reminder))

    if default.returncode == 0 and mentions_handoff and not mentions_default_reminder:
        print("")
        print("F8_DOC_MISMATCH: 缺出处的交接文档在默认档退 0（只提醒），"
              "README 的退出码 1 行却把「交接文档不合格」一律写成退 1，且未提默认档只提醒")
        return 1
    print("F8_DOC_MATCHES")
    return 0


sys.exit(main())
