#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Two small checks:

1. Would round one's *own* report have been judged '反向前置太短' by the
   pre-change gate? The new test comment claims '第 3 轮报告的 F7/F8 就是这样被
   误杀的'. Run the HEAD (pre-change) gate over `.review-evidence-r3/report.md`
   with --strict and look for that wording (and the F7/F8 blocks in general).
2. Is the per-round evidence directory actually gitignored?

Transcript written to argv[1] in UTF-8.
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = r"C:\Users\dupenglai\.dsh\tmp\fer-repo"
R3_REPORT = os.path.join(REPO, ".review-evidence-r3", "report.md")
out = open(sys.argv[1], "w", encoding="utf-8", newline="\n")

old = r"C:\Users\dupenglai\AppData\Local\Temp\fer-old-r4\check_review_report.py"
env = dict(os.environ)
env["PYTHONDONTWRITEBYTECODE"] = "1"
env["PYTHONUTF8"] = "1"

out.write("== 1. HEAD（改动前）门禁 --strict 跑第 3 轮报告全文 ==\n")
proc = subprocess.run([sys.executable, old, "--strict", "--workdir",
                       os.path.dirname(R3_REPORT), R3_REPORT],
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
text = proc.stdout.decode("utf-8", "replace")
out.write("gate exit = " + str(proc.returncode) + "\n")
out.write("--- stdout ---\n" + text)
if proc.stderr:
    out.write("--- stderr ---\n" + proc.stderr.decode("utf-8", "replace"))
out.write("--- 关键字统计 ---\n")
out.write("出现「反向前置」太短 次数 = " + str(text.count("太短")) + "\n")
for line in text.splitlines():
    if line.startswith("[FAIL]") or line.startswith("[ OK ]") or line.startswith("[OK"):
        out.write("   " + line + "\n")

out.write("\n== 2. .review-evidence-r3 / -r4 是否被 gitignore ==\n")
for target in [".review-evidence/", ".review-evidence-r3/x.txt", ".review-evidence-r4/x.txt",
               ".review-handoff.md"]:
    p = subprocess.run(["git", "check-ignore", "-v", target], cwd=REPO,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out.write("git check-ignore -v " + target + " -> exit " + str(p.returncode) + " "
              + repr(p.stdout.decode("utf-8", "replace").strip()) + "\n")
p = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
out.write("\ngit status --porcelain:\n" + p.stdout.decode("utf-8", "replace"))

out.close()
print("written: " + sys.argv[1])
