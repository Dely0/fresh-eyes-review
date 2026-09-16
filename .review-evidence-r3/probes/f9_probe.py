# -*- coding: utf-8 -*-
"""Evidence probe: the handoff document's acceptance criterion 5 says
"改动前的 53 条断言全部保持通过" (53 assertions before the change).

Exports the HEAD revision of the gate + suite into a temp dir and runs it, so
the pre-change assertion total is measured rather than assumed. Exits 1 when
HEAD does not self-report 53.
"""
import os, re, subprocess, sys, tempfile

REPO = r"C:\Users\dupenglai\.dsh\tmp\fer-repo"
BASE = "593532b25d1b14cd85b73e7a4c65a27e23a76cbf"


def show(path):
    proc = subprocess.run(["git", "show", BASE + ":" + path], cwd=REPO, capture_output=True)
    if proc.returncode != 0:
        print("git show failed for " + path + ": " + proc.stderr.decode("utf-8", "replace"))
        sys.exit(2)
    return proc.stdout


def suite_total(directory):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, os.path.join(directory, "test_check_review_report.py")],
        cwd=directory, capture_output=True, env=env)
    text = proc.stdout.decode("utf-8", "replace")
    totals = [l for l in text.splitlines() if l.startswith("共 ")]
    print(os.path.basename(directory) + " -> exit " + str(proc.returncode)
          + " | " + (totals[-1] if totals else "(no total line)"))
    return proc.returncode, (totals[-1] if totals else "")


def main():
    old = tempfile.mkdtemp(prefix="fer-f9-head-")
    open(os.path.join(old, "check_review_report.py"), "wb").write(
        show("fresh-eyes-review/scripts/check_review_report.py"))
    open(os.path.join(old, "test_check_review_report.py"), "wb").write(
        show("fresh-eyes-review/scripts/test_check_review_report.py"))
    rc_old, total_old = suite_total(old)

    new = tempfile.mkdtemp(prefix="fer-f9-new-")
    for name in ("check_review_report.py", "test_check_review_report.py"):
        src = open(os.path.join(REPO, "fresh-eyes-review", "scripts", name), "rb").read()
        open(os.path.join(new, name), "wb").write(src)
    rc_new, total_new = suite_total(new)

    m = re.search(r"共 (\d+) 条", total_old)
    old_count = int(m.group(1)) if m else -1
    print("")
    print("交接文档写的「改动前」= 53 条；HEAD(" + BASE[:7] + ") 实测 = "
          + str(old_count) + " 条；工作区 = " + total_new)

    measured_old = subprocess.run(
        [sys.executable, os.path.join(old, "test_check_review_report.py")],
        capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    print("HEAD 套件自报行：" + [l for l in measured_old.stdout.decode("utf-8", "replace").splitlines()
                                if l.startswith("共 ")][-1])

    if old_count == 53:
        print("F9_COUNT_MATCHES")
        return 0
    print("F9_COUNT_MISMATCH: 交接文档的验收标准 5 写「改动前的 53 条断言」，"
          "而基线提交实测自报 " + str(old_count) + " 条 —— 这个基准在仓库里不存在")
    return 1


sys.exit(main())
