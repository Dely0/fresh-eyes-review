#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Show WHY `falsify_unmarked_claim` passes, and that it survives M3.

`falsify_unmarked_claim`'s fixture only carries `## 我确认成立的`, so the gate
fails it on the *missing sections* rule -- never on the verdict-marker rule the
assertion claims to pin. Deleting the verdict-marker check (mutation M3) leaves
the gate's answer byte-identical, which is why the suite does not go red.

Transcript written to argv[1] in UTF-8.
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = r"C:\Users\dupenglai\.dsh\tmp\fer-repo"
GATE = os.path.join(REPO, "fresh-eyes-review", "scripts", "check_review_report.py")

out = open(sys.argv[1], "w", encoding="utf-8", newline="\n")
src0 = open(GATE, "rb").read().decode("utf-8")

HANDOFF_OK = """# 审查交接文档

## 范围
- 工作目录：`C:\\work\\repo`

## 已定取舍
- 归一化只折叠十类已知易变 token | 依据：HumanDecision：真人明确要求先保守 | 影响边界：会产生假不一致
"""

# 套件里 falsify_unmarked_claim 的原始夹具
UNMARKED = "### 对抗性复审\n\n## 我确认成立的\n- F1 这个问题是成立的\n"

# 同一夹具的「修好版」：三段都在，只有一条判定条目没带标注
ALL_SECTIONS_NO_MARKER = (
    "### 对抗性复审\n\n## 我确认成立的\n- F1 这个问题是成立的\n\n"
    "## 我驳倒的\n- F2 上轮说日志会丢 · 判定：驳回\n\n## 未决\n- F9 本地没法验证\n")

root = tempfile.mkdtemp(prefix="fer-green-r4-")
env = dict(os.environ)
env["PYTHONDONTWRITEBYTECODE"] = "1"
env["PYTHONUTF8"] = "1"


def run(label, gate_path, report_body, extras):
    case = os.path.join(root, label)
    os.makedirs(case, exist_ok=True)
    with open(os.path.join(case, ".review-handoff.md"), "w", encoding="utf-8") as fh:
        fh.write(HANDOFF_OK)
    with open(os.path.join(case, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(report_body)
    proc = subprocess.run([sys.executable, gate_path] + extras
                          + [os.path.join(case, "report.md")],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    out.write("\n### " + label + "\n")
    out.write("$ python <gate> " + " ".join(extras) + " <report.md>\n")
    out.write("gate exit = " + str(proc.returncode) + "\n")
    out.write("--- stdout ---\n" + proc.stdout.decode("utf-8", "replace"))
    out.write("--- stderr ---\n" + proc.stderr.decode("utf-8", "replace"))
    out.write("--- end ---\n")
    return proc


mutated = os.path.join(root, "gate_M3.py")
open(mutated, "w", encoding="utf-8").write(
    src0.replace("if not any(marker in entry for marker in FALSIFY_VERDICT_MARKERS):",
                 "if False:"))

out.write("夹具 A = 套件里 falsify_unmarked_claim 的原文（只有「我确认成立的」一节）\n")
a1 = run("A_original_gate", GATE, UNMARKED,
         ["--falsify", "--handoff", ".review-handoff.md", "--strict"])
a2 = run("A_M3_gate", mutated, UNMARKED,
         ["--falsify", "--handoff", ".review-handoff.md", "--strict"])
out.write("\nA 两次运行输出相同吗（除 gate 路径外）："
          + str(a1.stdout == a2.stdout and a1.returncode == a2.returncode) + "\n")
out.write("=> 这条断言判红的原因与小节缺失有关，与「判定标注」规则无关；\n"
          "   把标注规则整条删掉（M3），它照样红，所以套件在 M3 下全绿。\n")

out.write("\n\n夹具 B = 三段齐全、只有一条判定条目缺标注（这才是标注规则真正的靶子）\n")
b1 = run("B_all_sections_gate", GATE, ALL_SECTIONS_NO_MARKER,
         ["--falsify", "--handoff", ".review-handoff.md", "--strict"])
b2 = run("B_all_sections_M3_gate", mutated, ALL_SECTIONS_NO_MARKER,
         ["--falsify", "--handoff", ".review-handoff.md", "--strict"])
out.write("\nB 两次运行的退出码：原文 " + str(b1.returncode) + " / M3 "
          + str(b2.returncode) + "\n")
out.write("=> 套件里没有任何用例使用 B 这种夹具（三段齐全、缺标注）。\n")

out.write("\n\n夹具 C = 同 B，但用默认档（不带 --strict）\n")
c1 = run("C_all_sections_default", GATE, ALL_SECTIONS_NO_MARKER,
         ["--falsify", "--handoff", ".review-handoff.md"])

out.close()
shutil.rmtree(root, ignore_errors=True)
print("written: " + sys.argv[1])
