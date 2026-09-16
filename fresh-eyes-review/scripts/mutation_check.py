#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Directed mutation testing for check_review_report.py.

WHY THIS EXISTS
---------------
A regression suite that passes proves the gate behaves as documented *on the
cases it exercises*. It does not prove the cases exercise the rules. Two real
defects in this project had exactly that shape:

  * `--strict` counted warnings before merging the pre-fix warnings, so a
    whole class of warnings never reached the exit code -- and the assertion
    that covered it went green on an unrelated warning.
  * The `--falsify` cluster was pinned by no assertion at all: deleting the
    rule kept the suite green, because the fixture was missing its report file
    and exited through the "cannot read report" branch instead.

Both were found by mutation -- deleting the rule and checking that something
goes red. So: **whenever you add or change a rule, add a mutation here and make
sure it is caught.** A mutation that survives means the rule is decoration.

Usage:
    python mutation_check.py            # run every mutation, full suite
    python mutation_check.py --quick    # only the cases each mutation needs

`--quick` runs the affected cases via the suite's `--only`, which is what you
want while iterating; the full suite is the final check before committing.
Exit code 0 when every mutation is caught, 1 otherwise.
"""

import io
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
SUITE = os.path.join(HERE, "test_check_review_report.py")


def _c(code, anchor, replacement, covers):
    return {"code": code, "anchor": anchor, "replacement": replacement,
            "covers": tuple(covers)}


MUTATIONS = (
    _c("M1 --falsify 不再要求 --handoff",
       "if falsify and handoff is None:", "if False and handoff is None:",
       ["falsify_requires_handoff_flag", "falsify_ok"]),
    _c("M2 对抗性复审缺小节不再算问题",
       'problems.append("对抗性复审报告缺少小节：「## " + section + "」"',
       'pass  # 缺小节检查已删',
       ["falsify_no_verdict_headings", "falsify_ok"]),
    _c("M3 判定标注不再检查",
       'warnings.append("判定条目没有标注（「· 严重度：」或「· 判定：」）："',
       'pass  # 标注检查已删',
       ["falsify_unmarked_claim", "falsify_ok"]),
    _c("M4 「未决」不再是必需段",
       'FALSIFY_SECTIONS = ("我确认成立的", "我驳倒的", "未决")',
       'FALSIFY_SECTIONS = ("我确认成立的", "我驳倒的")',
       ["falsify_missing_undecided_section", "falsify_ok"]),
    _c("M5 交接文档只需「范围」一节",
       'HANDOFF_REQUIRED_SECTIONS = ("范围", "已定取舍")',
       'HANDOFF_REQUIRED_SECTIONS = ("范围",)',
       ["handoff_only_scope_no_tradeoffs_section", "handoff_ok"]),
    _c("M6 取舍出处不再检查",
       "if provenance_of(stripped) is None:",
       "if False and provenance_of(stripped) is None:",
       ["handoff_missing_provenance", "handoff_ok"]),
    _c("M7 空取舍小节不再算问题",
       'problems.append("「## 已定取舍」下没有任何条目 —— 空小节和「别管」是一回事")',
       'pass  # 空小节检查已删',
       ["handoff_no_tradeoffs", "handoff_ok"]),
    _c("M8 反向前置太短不再拦",
       "if len(text) < 8:", "if len(text) < 1:",
       ["red_command_too_short"]),
    _c("M9 反向前置证据记成 exit 0 不再判不合格",
       "if code == 0:", "if False and code == 0:",
       ["red_exit_zero", "red_exit_nonzero"]),
    _c("M10 位置可核实性不再检查",
       "location_warning = check_location_path(location, workdir)",
       "location_warning = None",
       ["location_missing_file_strict", "location_line_out_of_range"]),
    _c("M11 证据路径注解解析退化为 strip_ticks",
       "def extract_path(value):\n    \"\"\"Pull the path out of an evidence pointer.",
       "def extract_path(value):\n    return strip_ticks(value)\n\n\ndef _unused_extract_path(value):\n    \"\"\"Pull the path out of an evidence pointer.",
       ["evidence_path_with_annotation"]),
    _c("M12 「同上」简写不再解析",
       'if normalized.startswith(("同上", "同前")):',
       "if False:",
       ["red_same_as_repro"]),
    _c("M13 模式开关失效：声明首轮也能跑 --falsify",
       "if falsify and mode != \"adversarial\":",
       "if False:",
       ["falsify_requires_adversarial_mode", "falsify_with_adversarial_mode"]),
    # 注意：`if mode is None:` 那一支**故意不做成变异**。删掉它行为等价 ——
    # mode 为 None 时会落到 `mode != "adversarial"` 上，照样拦下。它只影响报错
    # 文案，不影响判定，所以不存在「删掉它套件应变红」这回事。
    _c("M15 小节扫描不再跳围栏",
       "lines, _fenced = strip_fences(markdown)\n    headings = [line.strip().lstrip(\"#\").strip() for line in lines\n                if line.strip().startswith(\"##\")]\n    for section in FALSIFY_SECTIONS:",
       "lines, _fenced = markdown.splitlines(), []\n    headings = [line.strip().lstrip(\"#\").strip() for line in lines\n                if line.strip().startswith(\"##\")]\n    for section in FALSIFY_SECTIONS:",
       ["falsify_sections_only_in_fence"]),
    _c("M16 编号正则退回词边界（不认中文相邻）",
       'FINDING_REF_RE = re.compile(r"\\bF\\d+(?![0-9])")',
       'FINDING_REF_RE = re.compile(r"\\bF\\d+\\b")',
       ["falsify_finding_ref_adjacent_cjk"]),
    _c("M17 证据路径注解解析退回「取第一段反引号」",
       "            before = parts[index - 1].strip()",
       "            return candidate\n            before = parts[index - 1].strip()",
       ["evidence_path_note_has_ticks"]),
)


def run_suite(gate_dir, only, quick):
    command = [sys.executable, os.path.join(gate_dir, "test_check_review_report.py")]
    if quick:
        command.append("--skip-harness")
        for name in only:
            command += ["--only", name]
    env = dict(os.environ)
    # Force UTF-8 for the child: on a cp936 console the suite's stderr assertions
    # read mojibake otherwise, and a mutation would look uncaught.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(command, cwd=gate_dir, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.stdout.decode("utf-8", "replace")
    summary = [line for line in out.splitlines() if "条断言" in line]
    reds = [line.strip() for line in out.splitlines() if "[ RED ]" in line]
    return proc.returncode, (summary[-1] if summary else "(无汇总行)"), reds


def main():
    quick = "--quick" in sys.argv[1:]
    source = io.open(GATE, encoding="utf-8").read()
    print("模式：" + ("--quick（只跑受影响的用例）" if quick else "全量套件"))
    print("")
    print("%-44s %-28s %s" % ("变异", "套件结果", "判定"))
    print("-" * 96)

    caught = 0
    misses = []
    for mutation in MUTATIONS:
        anchor = mutation["anchor"]
        if anchor not in source:
            print("%-44s %-28s %s" % (mutation["code"], "锚点未找到", "!! 变异无效"))
            misses.append(mutation["code"] + "（锚点失效，请更新本脚本）")
            continue
        work = tempfile.mkdtemp(prefix="fer-mut-")
        try:
            io.open(os.path.join(work, "check_review_report.py"), "w",
                    encoding="utf-8", newline="\n").write(
                source.replace(anchor, mutation["replacement"], 1))
            io.open(os.path.join(work, "test_check_review_report.py"), "w",
                    encoding="utf-8", newline="\n").write(
                io.open(SUITE, encoding="utf-8").read())
            code, summary, reds = run_suite(work, mutation["covers"], quick)
            if code != 0:
                caught += 1
                print("%-44s %-28s %s" % (mutation["code"], summary, "✅ 拦下"))
            else:
                misses.append(mutation["code"])
                print("%-44s %-28s %s" % (mutation["code"], summary, "❌ 没咬住"))
                for line in reds[:3]:
                    print("      " + line)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    print("")
    print("拦下 %d / %d" % (caught, len(MUTATIONS)))
    if misses:
        print("以下变异存活，说明对应规则没被断言钉住：")
        for miss in misses:
            print("  - " + miss)
        return 1
    print("全部变异都被拦下 —— 这些规则确实被断言钉住了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
