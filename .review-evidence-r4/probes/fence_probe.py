#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fence blindness in check_handoff / check_falsify_report.

`find_blocks` deliberately skips fenced code, but the handoff and falsify
section scanners do not: they take every line starting with `##` as a heading and
every `-` line as an entry, fence or not. So a document whose only "sections" and
"entries" are a quoted format example inside a ``` block passes --strict.

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

HANDOFF_REAL = """# 审查交接文档

## 范围
- 工作目录：`C:\\work\\repo`

## 已定取舍
- 归一化只折叠十类已知易变 token | 依据：HumanDecision：真人要求 | 影响边界：会产生假不一致
"""

# 交接文档：两个必需小节都只出现在围栏里的「格式示例」中
HANDOFF_FENCED = """# 审查交接文档

下面是格式示例，我还没填：

```markdown
## 范围
- 工作目录：`<绝对路径>`

## 已定取舍
- <取舍> | 依据：<HumanDecision / RecordedDecision / OrchestratorClaim>：<谁定的>
```
"""

# 对抗性复审报告：三段与条目全部只出现在围栏里的示例中
FALSIFY_FENCED = """### 对抗性复审 · 目标：上一轮（格式示例，尚未填写）

```markdown
## 我确认成立的
- F1 缓存淘汰多留一条 · 判定：成立

## 我驳倒的
- F2 上轮说日志会丢，实际是正常轮转 · 判定：驳回

## 未决
- F3 涉及 CI 行为，本地无法验证
```
"""

GOOD_REPORT = (
    "### F1 兜底报告 · 严重度：高\n"
    "- 位置：src/real.py:1\n"
    "- 复现：python -c \"print('checked=1')\"\n"
    "- 证据文件：ev/F1.txt\n"
    "- 反向前置：python -c \"import sys;sys.exit(1)\"\n"
    "- 反向前置证据：ev/R1.txt\n"
    "- 实测：见证据文件\n")
GOOD_FILES = {"src/real.py": b"x = 1\n", "ev/F1.txt": b"[exit code: 0]\nchecked=1\n",
              "ev/R1.txt": b"[exit code: 1]\nfail\n"}

root = tempfile.mkdtemp(prefix="fer-fence-r4-")
env = dict(os.environ)
env["PYTHONDONTWRITEBYTECODE"] = "1"
env["PYTHONUTF8"] = "1"


def run(label, files, extras, report_name="report.md"):
    case = os.path.join(root, label)
    os.makedirs(case, exist_ok=True)
    for rel, payload in files.items():
        path = os.path.join(case, rel)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        open(path, "wb").write(payload)
    proc = subprocess.run([sys.executable, GATE] + extras + [os.path.join(case, report_name)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    out.write("\n### " + label + "\n")
    out.write("$ python <gate> " + " ".join(extras) + " <" + report_name + ">\n")
    out.write("gate exit = " + str(proc.returncode) + "\n")
    out.write("--- stdout ---\n" + proc.stdout.decode("utf-8", "replace"))
    out.write("--- stderr ---\n" + proc.stderr.decode("utf-8", "replace"))
    out.write("--- end ---\n")
    return proc


run("handoff_sections_only_in_fence",
    {".review-handoff.md": HANDOFF_FENCED.encode("utf-8"),
     "report.md": GOOD_REPORT.encode("utf-8"), **GOOD_FILES},
    ["--strict", "--handoff", ".review-handoff.md"])

run("falsify_verdicts_only_in_fence",
    {".review-handoff.md": HANDOFF_REAL.encode("utf-8"),
     "report.md": FALSIFY_FENCED.encode("utf-8")},
    ["--falsify", "--handoff", ".review-handoff.md", "--strict"])

out.close()
shutil.rmtree(root, ignore_errors=True)
print("written: " + sys.argv[1])
