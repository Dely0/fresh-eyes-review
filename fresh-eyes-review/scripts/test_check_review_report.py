#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression suite for check_review_report.py.

Every case is a bug that was actually found in a real review, or the safety net
that keeps a fix from over-reaching. Fixtures are generated here rather than read
from disk, so the suite is self-contained and can run anywhere.

Usage:
    python test_check_review_report.py

Exit codes:
    0  every assertion holds
    1  at least one assertion failed (the gate does not behave as documented)

Each case declares the exit code the gate MUST return. A red case means the gate
is wrong, not the test. Add a new rule to the gate? Add a case here that goes red
first.
"""

import os
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "check_review_report.py")

GOOD = """### F1 判重在生产上从没问过模型 · 严重度：高
- 位置：src/dedupe.py:139
- 复现：python src/dedupe.py --check
- 实测：checked=1 same=0 attached=0 calls=0
- 影响：静默失效，功能从未生效
- 建议修法：字段容忍缺失
"""

WARN_ONLY = """### F1 没写严重度的问题
- 位置：src/app.py:1
- 复现：python src/app.py --check
- 实测：exit=0
"""

# 证据文件路径相对报告所在目录
REPLAY_OK = """### F1 备份清理会误删导出目录 · 严重度：高
- 位置：scripts/backup.py:44
- 复现：echo cleaned=0 kept=1
- 证据文件：ev/F1.txt
- 实测：cleaned=0 kept=1
- 影响：人工导出的目录被整目录删除
- 建议修法：清理前按前缀白名单过滤
"""

EV_OK = b"[exit code: 0]\ncleaned=0 kept=1\n"


def replay_report(command, evidence_path="ev/F1.txt", observed="见证据文件"):
    return (
        "### F1 重放用例 · 严重度：高\n"
        "- 位置：scripts/backup.py:44\n"
        "- 复现：" + command + "\n"
        "- 证据文件：" + evidence_path + "\n"
        "- 实测：" + observed + "\n"
        "- 影响：误删\n"
    ).encode("utf-8")


CASES = [
    # --- 基础格式 ---------------------------------------------------------
    ("good", {"report.md": GOOD.encode("utf-8")}, [], 0,
     "安全网：完全合规的报告必须通过"),
    ("missing_observed", {"report.md": GOOD.replace(
        "- 实测：checked=1 same=0 attached=0 calls=0\n", "").encode("utf-8")}, [], 1,
     "既没有实测也没有证据文件必须被拦"),

    # --- F1 块边界不得泄漏到尾部小节 ---------------------------------------
    ("tail_leak", {"report.md": (
        "### F1 末条发现一个字段都没写 · 严重度：高\n\n"
        "## 未能验证\n"
        "- 位置：src/a.py:1\n"
        "- 复现：python src/a.py --check\n"
        "- 实测：未能执行：没有网络\n"
    ).encode("utf-8")}, [], 1,
     "尾部小节的字段不得替末条发现补齐（假阴性）"),
    ("mid_leak", {"report.md": (
        "### F1 缺字段的发现 · 严重度：高\n\n"
        "### F2 这条是好的 · 严重度：高\n"
        "- 位置：src/a.py:1\n- 复现：python src/a.py --check\n- 实测：exit=0\n\n"
        "## 未能验证\n- 实测：未能执行：没网\n"
    ).encode("utf-8")}, [], 1,
     "中间小节的字段不得算到前一条发现头上"),

    # --- F2 「未发现问题」必须独占一行 -------------------------------------
    ("none_standalone", {"report.md": "审完了。未发现问题。\n".encode("utf-8")}, [], 0,
     "独占一行的结论句应当被接受"),
    ("prose_none_word", {"report.md": "重跑之后无问题。\n".encode("utf-8")}, [], 1,
     "正文里出现「无问题」子串不能翻成通过（假阴性）"),
    ("prose_no_blocks", {"report.md": "我读了代码，整体还行。\n".encode("utf-8")}, [], 1,
     "散文式报告不算报告"),
    ("bad_block_plus_none", {"report.md": (
        "### F1 缺证据 · 严重度：高\n- 位置：src/a.py:1\n"
        "- 复现：python src/a.py --check\n\n未发现问题\n"
    ).encode("utf-8")}, [], 1,
     "有发现块时，结论句不能覆盖发现块的失败"),
    ("empty_file", {"report.md": b""}, [], 1, "空报告必须失败"),

    # --- F3 编码 -----------------------------------------------------------
    ("gbk_good", {"report.md": GOOD.encode("gb18030")}, [], 0,
     "GBK 落盘的合规报告不该被误杀"),
    ("utf16_good", {"report.md": GOOD.encode("utf-16")}, [], 0,
     "UTF-16 BOM 的合规报告不该被误杀"),
    ("undecodable", {"report.md": b"\xff\xff\xff\xff"}, [], 2,
     "解码失败属于读取错误，必须退 2 而不是 1"),

    # --- F4/F5 标签与多行值 ------------------------------------------------
    ("bold_labels", {"report.md": (
        "### F1 加粗标签也要认 · 严重度：中\n"
        "- **位置**：`scripts/check_review_report.py`:65\n"
        "- **复现**：`python scripts/x.py --dry-run`\n"
        "- **实测**：`exit=0`\n"
    ).encode("utf-8")}, [], 0,
     "`- **位置**：…` 是模板允许的写法，不该误杀"),
    ("ascii_labels", {"report.md": (
        "### F1 ascii labels · severity: high\n"
        "- location: src/a.py:1\n"
        "- reproduce: python src/a.py --check\n"
        "- observed: exit=0\n"
    ).encode("utf-8")}, [], 0, "ASCII 字段名同样合法"),
    ("value_next_line", {"report.md": (
        "### F1 多行证据 · 严重度：高\n"
        "- 位置：scripts/backup.py:44\n"
        "- 复现：\n"
        "  python scripts/backup.py --out /tmp/bk --keep 1\n"
        "- 实测：\n"
        "  ```\n"
        "  md-snapshots 被整目录删除\n"
        "  exit=0\n"
        "  ```\n"
        "- 影响：误删人工导出的目录\n"
    ).encode("utf-8")}, [], 0, "多行命令与围栏输出是自然写法，不该误杀"),
    ("value_next_line_traceback", {"report.md": (
        "### F1 粘贴的报错里带冒号 · 严重度：高\n"
        "- 位置：src/a.py:1\n"
        "- 复现：python src/a.py --check\n"
        "- 实测：\n"
        "  ```\n"
        "  Traceback (most recent call last):\n"
        "  ValueError: bad input\n"
        "  ```\n"
    ).encode("utf-8")}, [], 0,
     "围栏里的 `ValueError: …` 不得被当成新字段而截断值"),

    # --- F6 废话不算证据 ---------------------------------------------------
    ("junk_values", {"report.md": (
        "### F1 问题 · 严重度：高\n"
        "- 位置：src/a.py:1\n- 复现：见上\n- 实测：无\n"
    ).encode("utf-8")}, [], 1, "「见上」「无」这类填充词不算证据"),
    ("warn_only_default", {"report.md": WARN_ONLY.encode("utf-8")}, [], 0,
     "默认档：提醒不影响退出码"),
    ("warn_only_strict", {"report.md": WARN_ONLY.encode("utf-8")}, ["--strict"], 1,
     "--strict 档：提醒也应让门禁失败"),

    # --- F9 「未能执行」的原因阈值 -----------------------------------------
    ("cannot_run_short_reason", {"report.md": (
        "### F1 跑不了但给了原因 · 严重度：中\n"
        "- 位置：docs/upgrade.md\n"
        "- 复现：重启服务后观察启动行的配置键\n"
        "- 实测：未能执行：没网\n"
    ).encode("utf-8")}, [], 0, "给了原因（哪怕两个字）就不该判「没给原因」"),
    ("cannot_run_no_reason", {"report.md": (
        "### F1 跑不了也没说原因 · 严重度：中\n"
        "- 位置：src/a.py:1\n- 复现：python src/a.py --check\n- 实测：未能执行\n"
    ).encode("utf-8")}, [], 1, "只写「未能执行」而不给原因必须被拦"),

    # --- 证据文件（静态校验） ----------------------------------------------
    ("evidence_ok", {"report.md": REPLAY_OK.encode("utf-8"), "ev/F1.txt": EV_OK}, [], 0,
     "证据文件存在且格式正确应当通过"),
    ("evidence_missing", {"report.md": replay_report("echo ok")}, [], 1,
     "指向不存在的证据文件必须被拦（悬空指针比没有更糟）"),
    ("evidence_no_marker", {"report.md": REPLAY_OK.encode("utf-8"),
                            "ev/F1.txt": b"cleaned=0 kept=1\n"}, [], 1,
     "证据文件首行必须是 [exit code: N]"),
    ("evidence_empty_body", {"report.md": REPLAY_OK.encode("utf-8"),
                             "ev/F1.txt": b"[exit code: 0]\n"}, [], 1,
     "证据文件只有退出码、没有输出内容必须被拦"),

    # --- 重放档 -------------------------------------------------------------
    ("replay_reproduced", {"report.md": REPLAY_OK.encode("utf-8"), "ev/F1.txt": EV_OK},
     ["--replay"], 0, "重跑输出与证据文件一致时必须通过"),
    ("replay_differs", {"report.md": REPLAY_OK.encode("utf-8"),
                        "ev/F1.txt": b"[exit code: 0]\ncleaned=9 kept=9\n"},
     ["--replay"], 1, "重跑输出与证据文件不一致必须被拦"),
    ("replay_exit_mismatch", {"report.md": REPLAY_OK.encode("utf-8"),
                              "ev/F1.txt": b"[exit code: 3]\ncleaned=0 kept=1\n"},
     ["--replay"], 1, "退出码不一致必须被拦"),
    ("replay_normalized", {
        "report.md": replay_report("echo done at 2026-09-16T00:00:00Z in 12ms"),
        "ev/F1.txt": b"[exit code: 0]\ndone at 2025-01-01T11:11:11Z in 999ms\n"},
     ["--replay"], 0, "易变内容（时间戳/耗时）归一化后一致应当通过"),
    ("replay_refused", {
        "report.md": replay_report("rm -rf build/ --dry-run"),
        "ev/F1.txt": b"[exit code: 0]\nremoved\n"},
     ["--replay"], 1, "命中拒绝表的命令不得执行，按不合格处理"),
    ("replay_timeout", {
        "report.md": replay_report('python -c "import time;time.sleep(30)"'),
        "ev/F1.txt": b"[exit code: 0]\nnever\n"},
     ["--replay", "--timeout", "1"], 1, "重跑超时必须被拦"),
    ("replay_requires_evidence_file", {"report.md": GOOD.encode("utf-8")},
     ["--replay"], 1, "重放档下只有内联实测、没有证据文件的条目不满足重放前提"),
    ("replay_none_declared", {"report.md": "未发现问题\n".encode("utf-8")},
     ["--replay"], 0, "声明未发现问题时重放档也应通过"),

    # --- 用法 ---------------------------------------------------------------
    ("unknown_option", {"report.md": GOOD.encode("utf-8")}, ["--nope"], 2,
     "未知选项退 2"),
]


def run_case(root, name, files, extras):
    case_dir = os.path.join(root, name)
    os.makedirs(case_dir, exist_ok=True)
    for relative, payload in files.items():
        path = os.path.join(case_dir, relative)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(payload)
    report = os.path.join(case_dir, "report.md")
    command = [sys.executable, GATE] + extras + [report]
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode, proc.stdout, proc.stderr


def main():
    root = tempfile.mkdtemp(prefix="fresh-eyes-review-tests-")
    red = 0
    total = 0
    try:
        for name, files, extras, expected, why in CASES:
            total += 1
            try:
                code, out, err = run_case(root, name, files, extras)
            except Exception as error:  # pragma: no cover - harness failure
                red += 1
                print("[ RED ] " + name + "  跑不起来: " + str(error))
                continue
            if code == expected:
                print("[GREEN] " + name + "  exit=" + str(code))
            else:
                red += 1
                text = (out + err).decode("utf-8", "replace").strip().splitlines()
                tail = text[-1] if text else "(无输出)"
                print("[ RED ] " + name + "  期望 exit=" + str(expected)
                      + "，实得 exit=" + str(code))
                print("        为什么该红: " + why)
                print("        末行输出: " + tail)

        total += 1
        missing = os.path.join(root, "does-not-exist.md")
        proc = subprocess.run([sys.executable, GATE, missing],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode == 2:
            print("[GREEN] missing_file  exit=2")
        else:
            red += 1
            print("[ RED ] missing_file  期望 exit=2，实得 exit=" + str(proc.returncode))

        total += 1
        proc = subprocess.run([sys.executable, GATE],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode == 2:
            print("[GREEN] no_args  exit=2")
        else:
            red += 1
            print("[ RED ] no_args  期望 exit=2，实得 exit=" + str(proc.returncode))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("")
    print("共 " + str(total) + " 条断言，变红 " + str(red) + " 条。")
    if red:
        print("结论：门禁的行为与文档不符 —— 先修脚本，不要依赖它的退出码。")
        return 1
    print("结论：全绿 —— 门禁行为与断言一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
