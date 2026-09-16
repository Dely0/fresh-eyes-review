#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round-4 behaviour probe: build fixtures, run the gate, print raw output.

Every case prints the exact gate argv, its exit code, and its raw stdout/stderr
so the captured transcript is the gate's own words, not a paraphrase.
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = r"C:\Users\dupenglai\.dsh\tmp\fer-repo"
GATE = os.path.join(REPO, "fresh-eyes-review", "scripts", "check_review_report.py")

HANDOFF_OK = """# 审查交接文档

## 范围
- 工作目录：`C:\\work\\repo`
- 改动范围：`git diff` 的 6 个文件

## 已定取舍
- 归一化只折叠十类已知易变 token | 依据：HumanDecision：真人明确要求先保守 | 影响边界：会产生假不一致
"""

HANDOFF_ONLY_TRADEOFFS = """# 审查交接文档

## 已定取舍
- 归一化只折叠十类已知易变 token | 依据：HumanDecision：真人明确要求先保守 | 影响边界：会产生假不一致
"""

# 范围 小节只出现在围栏代码块里的「示例」中
HANDOFF_SCOPE_IN_FENCE = """# 审查交接文档

## 已定取舍
- 归一化只折叠十类已知易变 token | 依据：HumanDecision：真人明确要求先保守 | 影响边界：会产生假不一致

下面是一份示例，不要照着抄：

```
## 范围
- 工作目录：`C:\\work\\repo`
```
"""

HANDOFF_NEGATED = """# 审查交接文档

## 范围
- 工作目录：`C:\\work\\repo`

## 已定取舍
- 不要报假不一致 | 依据：未经 HumanDecision 确认，是本轮执行者自行决定 | 影响边界：无
"""

HANDOFF_ORCH = HANDOFF_OK.replace("依据：HumanDecision：真人明确要求先保守",
                                 "依据：OrchestratorClaim：执行者自己说的")
HANDOFF_HUMAN = HANDOFF_OK

GOOD_REPORT = (
    "### F1 模式 C 兜底报告 · 严重度：高\n"
    "- 位置：src/real.py:1\n"
    "- 复现：python -c \"print('checked=1')\"\n"
    "- 证据文件：ev/F1.txt\n"
    "- 反向前置：python -c \"import sys;sys.exit(1)\"\n"
    "- 反向前置证据：ev/R1.txt\n"
    "- 实测：见证据文件\n"
)

GOOD_FILES = {
    "src/real.py": b"x = 1\n",
    "ev/F1.txt": b"[exit code: 0]\nchecked=1\n",
    "ev/R1.txt": b"[exit code: 1]\nfail\n",
}

FALSIFY_VACUOUS = """### 对抗性复审 · 目标：上一轮

## 我确认成立的
- 逐条复核完毕 · 判定：成立

## 我驳倒的
- 上轮结论有误 · 判定：驳回

## 未决
- 有几条没能本地验证
"""

# 三个小节都有、都点名了发现编号，但两条判定条目都没带「· 严重度：/· 判定：」
FALSIFY_NO_MARKERS = """### 对抗性复审 · 目标：上一轮（2 条）

## 我确认成立的
- F1 缓存淘汰多留一条

## 我驳倒的
- F2 上轮说日志会丢，实际是正常轮转

## 未决
- F9 涉及 CI 行为，本地无法验证
"""

# 发现编号后直接跟中文，没有空格：`- F1这条不成立`
FALSIFY_CN_ADJACENT = """### 对抗性复审 · 目标：上一轮（2 条）

## 我确认成立的
- F1这个问题确实存在 · 严重度：高

## 我驳倒的
- F2这条上轮报错了 · 严重度：低

## 未决
- F9涉及 CI 行为，本地无法验证
"""


def red_report(red, repro, repro_evidence_body, red_evidence_body=b"[exit code: 1]\nfail\n",
               evidence_field="ev/F1R.txt", red_field="ev/R1.txt"):
    lines = [
        "### F1 反向前置用例 · 严重度：高",
        "- 位置：src/backup.py:1",
        "- 复现：" + repro,
        "- 证据文件：" + evidence_field,
        "- 实测：见证据文件",
        "- 反向前置：" + red,
        "- 反向前置证据：" + red_field,
        "- 影响：误删",
    ]
    files = {
        "report.md": ("\n".join(lines) + "\n").encode("utf-8"),
        "src/backup.py": b"x = 1\n",
        "ev/F1R.txt": repro_evidence_body,
        "ev/R1.txt": red_evidence_body,
    }
    return files


CASES = []


def case(name, files, extras, note=""):
    CASES.append((name, files, extras, note))


case("F1_handoff_only_tradeoffs",
     {".review-handoff.md": HANDOFF_ONLY_TRADEOFFS.encode("utf-8"),
      "report.md": GOOD_REPORT.encode("utf-8"), **GOOD_FILES},
     ["--strict", "--handoff", ".review-handoff.md"],
     "F1 修复后：缺 ## 范围 应退 1")

case("F1_handoff_scope_inside_fence",
     {".review-handoff.md": HANDOFF_SCOPE_IN_FENCE.encode("utf-8"),
      "report.md": GOOD_REPORT.encode("utf-8"), **GOOD_FILES},
     ["--strict", "--handoff", ".review-handoff.md"],
     "F1 残余：## 范围 只出现在围栏示例里，是否仍算「必需小节在」")

case("F2_negated_provenance",
     {".review-handoff.md": HANDOFF_NEGATED.encode("utf-8"),
      "report.md": GOOD_REPORT.encode("utf-8"), **GOOD_FILES},
     ["--strict", "--handoff", ".review-handoff.md"],
     "F2 修复后：「依据：未经 HumanDecision 确认」应退 1")

case("F3_orchestrator_claim",
     {".review-handoff.md": HANDOFF_ORCH.encode("utf-8"),
      "report.md": GOOD_REPORT.encode("utf-8"), **GOOD_FILES},
     ["--strict", "--handoff", ".review-handoff.md"],
     "F3：自称 OrchestratorClaim 的取舍条目")

case("F3_human_decision",
     {".review-handoff.md": HANDOFF_HUMAN.encode("utf-8"),
      "report.md": GOOD_REPORT.encode("utf-8"), **GOOD_FILES},
     ["--strict", "--handoff", ".review-handoff.md"],
     "F3：同一条取舍改称 HumanDecision")

case("F5_vacuous_report",
     {".review-handoff.md": HANDOFF_OK.encode("utf-8"),
      "report.md": FALSIFY_VACUOUS.encode("utf-8")},
     ["--falsify", "--handoff", ".review-handoff.md", "--strict"],
     "F5 修复后：空洞报告应退 1")

case("F5_no_verdict_markers_default",
     {".review-handoff.md": HANDOFF_OK.encode("utf-8"),
      "report.md": FALSIFY_NO_MARKERS.encode("utf-8")},
     ["--falsify", "--handoff", ".review-handoff.md"],
     "F5 残余：默认档下判定标注缺失，成功话术是否仍然出现")

case("F5_cn_adjacent_finding_ref",
     {".review-handoff.md": HANDOFF_OK.encode("utf-8"),
      "report.md": FALSIFY_CN_ADJACENT.encode("utf-8")},
     ["--falsify", "--handoff", ".review-handoff.md", "--strict"],
     "F5 新问题：F1/F2 后面紧跟中文时 \\bF\\d+\\b 是否仍然算「点名了发现」")

case("F6_falsify_plus_replay",
     {".review-handoff.md": HANDOFF_OK.encode("utf-8"),
      "report.md": FALSIFY_NO_MARKERS.encode("utf-8")},
     ["--replay", "--falsify", "--handoff", ".review-handoff.md"],
     "F6 修复后：--falsify + --replay（顺序颠倒）应退 2")

case("F6_falsify_plus_pre_fix",
     {".review-handoff.md": HANDOFF_OK.encode("utf-8"),
      "report.md": FALSIFY_NO_MARKERS.encode("utf-8")},
     ["--falsify", "--pre-fix", "--handoff", ".review-handoff.md"],
     "F6 修复后：--falsify + --pre-fix 应退 2")

case("F9_annotation_inline_code",
     {".review-handoff.md": HANDOFF_OK.encode("utf-8"), **GOOD_FILES,
      "report.md": ("### F1 带注解的证据路径 · 严重度：高\n"
                    "- 位置：src/real.py:1\n"
                    "- 实测：见证据文件\n"
                    "- 复现：python -c \"print('checked=1')\"\n"
                    "- 证据文件：`ev/F1.txt`（原始输出，未摘录）\n"
                    "- 反向前置：python -c \"import sys;sys.exit(0)\"\n"
                    "- 反向前置证据：`ev/R1.txt`（首行 [exit code: 1]）\n").encode("utf-8")},
     ["--replay", "--strict"],
     "F9 修复后：inline code + 注解应能解析")

case("F9_bare_path_with_backticked_note",
     {**GOOD_FILES,
      "report.md": ("### F1 裸路径 + 注解里有 inline code · 严重度：高\n"
                    "- 位置：src/real.py:1\n"
                    "- 实测：见证据文件\n"
                    "- 复现：python -c \"print('checked=1')\"\n"
                    "- 证据文件：ev/F1.txt（同 `probe.log` 那份）\n"
                    "- 反向前置：python -c \"import sys;sys.exit(0)\"\n"
                    "- 反向前置证据：`ev/R1.txt`（首行 [exit code: 1]）\n").encode("utf-8")},
     [],
     "F9 修复的新问题：注解里的 inline code 被当成路径，合法报告是否被误杀")

case("RED_same_as_repro_default_strict",
     dict(red_report("同上", 'python -c "print(\'checked=1\')"',
                     b"[exit code: 0]\nchecked=1\n")),
     ["--strict"],
     "「同上」默认档：应退 0（这是本轮新增支持的目标场景）")

case("RED_same_as_repro_pre_fix",
     dict(red_report("同上", 'python -c "print(\'checked=1\')"',
                     b"[exit code: 0]\nchecked=1\n")),
     ["--pre-fix"],
     "「同上」在 --pre-fix 下：真正被执行的命令是什么")

case("RED_same_as_repro_replay",
     dict(red_report("同上", 'python -c "print(\'checked=1\')"',
                     b"[exit code: 0]\nchecked=1\n")),
     ["--replay"],
     "「同上」在 --replay 下：合法发现是否被判「修完之后仍然失败」")


def main():
    root = tempfile.mkdtemp(prefix="fer-probe-r4-")
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "transcript.txt")
    out = open(out_path, "w", encoding="utf-8", newline="\n")
    out.write("fixture root: " + root + "\n")
    print("writing transcript to " + out_path)
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # 子进程门禁的 stderr 在本机是 GBK（见 R4-stderr-encoding.txt），这里统一
    # 让它输出 UTF-8，好让证据文件里的中文是原样可读的；编码本身另有专项证据。
    env["PYTHONUTF8"] = "1"
    out.write("(子进程带 PYTHONUTF8=1，编码问题见 R4-stderr-encoding.txt)\n")
    try:
        for name, files, extras, note in CASES:
            case_dir = os.path.join(root, name)
            os.makedirs(case_dir, exist_ok=True)
            for relative, payload in files.items():
                path = os.path.join(case_dir, relative)
                parent = os.path.dirname(path)
                if parent and not os.path.isdir(parent):
                    os.makedirs(parent, exist_ok=True)
                with open(path, "wb") as fh:
                    fh.write(payload)
            report = os.path.join(case_dir, "report.md")
            argv = [sys.executable, GATE] + extras + [report]
            proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  env=env)
            out.write("\n### " + name + ("  -- " + note if note else "") + "\n")
            out.write("$ python check_review_report.py " + " ".join(extras) + " <report.md>\n")
            out.write("gate exit = " + str(proc.returncode) + "\n")
            out.write("--- stdout ---\n")
            out.write(proc.stdout.decode("utf-8", "replace"))
            out.write("--- stderr ---\n")
            out.write(proc.stderr.decode("utf-8", "replace"))
            out.write("--- end ---\n")
            print("  " + name + " -> gate exit " + str(proc.returncode))
    finally:
        out.close()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
