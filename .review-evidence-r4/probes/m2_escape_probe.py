#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Does the suite pin the 'falsify report is missing a required section' rule?

Mutation M2 deletes that rule; the suite still reports 0 red. This shows the two
falsify assertions that expect exit 1 for missing sections are satisfied by the
*empty-section* rule instead, so they never exercised the deleted rule.

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

# 套件夹具 falsify_no_verdict_headings 的原文
NO_HEADINGS = "### 对抗性复审 · 目标：2026-09-16 报告\n\n- F1 `--strict` 不计数反向前置提醒 · 严重度：高\n"
# 套件夹具 falsify_missing_undecided_section（falsify_body(omit_undecided=True)）
HANDOFF_OK = """# 审查交接文档

## 范围
- 工作目录：`C:\\work\\repo`

## 已定取舍
- 归一化只折叠十类已知易变 token | 依据：HumanDecision：真人明确要求先保守 | 影响边界：会产生假不一致
"""

root = tempfile.mkdtemp(prefix="fer-m2-r4-")
env = dict(os.environ)
env["PYTHONDONTWRITEBYTECODE"] = "1"
env["PYTHONUTF8"] = "1"

mutated = os.path.join(root, "gate_M2.py")
# 删掉 check_falsify_report 里的「缺少小节」规则（第二处 if not any(section in heading ...)）
needle = "if not any(section in heading for heading in headings):"
first = src0.find(needle)
second = src0.find(needle, first + 1)
assert second > 0
open(mutated, "w", encoding="utf-8").write(
    src0[:second] + "if False:" + src0[second + len(needle):])


def run(label, gate_path, report_body):
    case = os.path.join(root, label)
    os.makedirs(case, exist_ok=True)
    open(os.path.join(case, ".review-handoff.md"), "w", encoding="utf-8").write(HANDOFF_OK)
    open(os.path.join(case, "report.md"), "w", encoding="utf-8").write(report_body)
    proc = subprocess.run([sys.executable, gate_path, "--falsify", "--handoff",
                           ".review-handoff.md", "--strict",
                           os.path.join(case, "report.md")],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    out.write("\n### " + label + "\n")
    out.write("gate exit = " + str(proc.returncode) + "\n")
    out.write("--- stdout ---\n" + proc.stdout.decode("utf-8", "replace"))
    out.write("--- stderr ---\n" + proc.stderr.decode("utf-8", "replace"))
    out.write("--- end ---\n")
    return proc


out.write("夹具 = 套件里的 falsify_no_verdict_headings（整份报告一个小节都没有）\n")
a = run("no_headings_original_gate", GATE, NO_HEADINGS)
b = run("no_headings_M2_gate", mutated, NO_HEADINGS)
out.write("\n退出码：原文 " + str(a.returncode) + " / M2 " + str(b.returncode)
          + "（断言只比对退出码，所以 M2 下照样绿）\n")
out.write("输出文本相同吗：" + str(a.stdout == b.stdout) + "\n")
out.write("=> 原文靠「缺少小节」判红；M2 删掉该规则后改由「小节下没有任何条目」判红，"
          "退出码一样是 1。\n")

out.close()
shutil.rmtree(root, ignore_errors=True)
print("written: " + sys.argv[1])
