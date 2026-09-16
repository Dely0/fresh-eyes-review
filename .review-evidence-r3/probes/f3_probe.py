# -*- coding: utf-8 -*-
"""Evidence probe: the four `--falsify` rules are not pinned by the regression
suite.

The suite's only construction that aims at the `--falsify`-needs-`--handoff`
rule omits the handoff *file itself*, so the gate's "handoff file does not
exist" path (exit 2) satisfies the assertion no matter what the rule does.
Neutralising the rule therefore leaves a fully green suite.

Prints F3_RULE_UNPINNED and exits 1 while the suite cannot detect the change.
"""
import os, re, shutil, subprocess, sys, tempfile

SRC = os.path.dirname(os.path.abspath(__file__))
REPO = r"C:\Users\dupenglai\.dsh\tmp\fer-repo\fresh-eyes-review\scripts"

ANCHOR = "    if falsify and handoff is None:"
REPLACEMENT = "    if False and falsify and handoff is None:"


def run_suite(directory):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, os.path.join(directory, "test_check_review_report.py")],
        cwd=directory, capture_output=True, env=env)
    text = proc.stdout.decode("utf-8", "replace")
    reds = [m.group(1) for m in re.finditer(r"^\[ RED \] +(\S+)", text, re.M)]
    return proc.returncode, reds


def main():
    root = tempfile.mkdtemp(prefix="fer-f3-")
    source = open(os.path.join(REPO, "check_review_report.py"), encoding="utf-8").read()
    if source.count(ANCHOR) != 1:
        print("anchor not unique: " + str(source.count(ANCHOR)))
        return 1
    open(os.path.join(root, "check_review_report.py"), "w", encoding="utf-8").write(
        source.replace(ANCHOR, REPLACEMENT))
    shutil.copy(os.path.join(REPO, "test_check_review_report.py"),
                os.path.join(root, "test_check_review_report.py"))

    rc, reds = run_suite(root)
    print("mutation: --falsify no longer requires --handoff")
    print("suite exit=" + str(rc) + " red=" + str(reds))
    if rc == 0:
        print("F3_RULE_UNPINNED: 断言 falsify_needs_handoff 仍绿（它走的是交接文档不存在的分叉），"
              "整条 --falsify 规则可以整条删掉而套件全绿")
        return 1
    print("F3_RULE_PINNED: 破坏该规则会让套件变红")
    return 0


sys.exit(main())
