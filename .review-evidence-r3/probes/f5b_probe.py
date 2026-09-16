# -*- coding: utf-8 -*-
"""Evidence probe: `--falsify` swallows `--replay` / `--pre-fix`.

run() returns from the mode-C branch (line ~960) before the finding-block loop
that drives replay_red / replay_finding, so `--falsify --replay` re-runs
nothing and still exits 0. The printed verdict is byte-identical to plain
`--falsify`, which is the observable proof that no replay happened.

Also prints the assertion totals of the pre-change suite (HEAD) and of the
working-tree suite, because acceptance criterion 5 says "改动前的 53 条断言".
"""
import os, subprocess, sys, tempfile

GATE = sys.argv[1]

HANDOFF = """# 审查交接文档

## 范围
- 工作目录：`C:\\work\\repo`

## 已定取舍
- 只支持 Markdown | 依据：HumanDecision：真人拍板 | 影响边界：不支持 JSON
"""

ROUND2 = """### 对抗性复审 · 目标：上一轮

## 我确认成立的
- F1 代码里那个判重分支确实从没生效过 · 严重度：高

## 我驳倒的
- F7 经复核不成立 · 判定：驳回

## 未决
- F9 无法本地验证
"""


def main():
    d = tempfile.mkdtemp(prefix="fer-f5-")
    os.makedirs(os.path.join(d, "ev"))
    open(os.path.join(d, ".review-handoff.md"), "w", encoding="utf-8").write(HANDOFF)
    open(os.path.join(d, "round2.md"), "w", encoding="utf-8").write(ROUND2)
    # this file records a reproduction that could never match; nothing re-runs it
    open(os.path.join(d, "ev", "never.txt"), "w").write(
        "[exit code: 0]\nrecorded-output-that-never-occurs\n")

    outs = {}
    for label, extra in (("plain", ["--falsify", "--strict"]),
                         ("with-replay", ["--falsify", "--replay", "--strict"]),
                         ("with-prefix", ["--falsify", "--pre-fix", "--strict"])):
        proc = subprocess.run(
            [sys.executable, GATE] + extra + ["--handoff", ".review-handoff.md", "round2.md"],
            cwd=d, capture_output=True)
        out = proc.stdout.decode("utf-8", "replace").rstrip()
        outs[label] = out
        print("$ check_review_report.py " + " ".join(extra) + " round2.md")
        print(out)
        print("gate exit=" + str(proc.returncode))
        print("")

    old = subprocess.run(
        [sys.executable, os.path.join(r"C:\Users\dupenglai\AppData\Local\Temp\fer-old-r3",
                                      "test_check_review_report.py")],
        capture_output=True)
    print("HEAD 套件自报：" + [l for l in old.stdout.decode("utf-8", "replace").splitlines()
                              if l.startswith("共 ")][-1])
    new = subprocess.run([sys.executable, os.path.join(
        r"C:\Users\dupenglai\.dsh\tmp\fer-repo\fresh-eyes-review\scripts",
        "test_check_review_report.py")], capture_output=True)
    print("工作区套件自报：" + [l for l in new.stdout.decode("utf-8", "replace").splitlines()
                               if l.startswith("共 ")][-1])

    same = outs["plain"] == outs["with-replay"] == outs["with-prefix"]
    print("F5_FALSIFY_IGNORES_REPLAY: --falsify --replay 与纯 --falsify 输出逐字节相同 = "
          + str(same) + "；没有任何一行重放/前置输出")
    return 1


sys.exit(main())
