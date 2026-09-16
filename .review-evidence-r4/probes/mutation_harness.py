#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round-4 targeted mutation harness.

For each mutation: copy the gate, apply one string edit, run the regression
suite against the mutated copy (PYTHONUTF8=1 so the harness's own locale does
not confound the result), and report the summary line plus every RED case.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = r"C:\Users\dupenglai\.dsh\tmp\fer-repo"
GATE_SRC = os.path.join(REPO, "fresh-eyes-review", "scripts", "check_review_report.py")
TEST_SRC = os.path.join(REPO, "fresh-eyes-review", "scripts", "test_check_review_report.py")


def nth_replace(src, old, new, n):
    idx = -1
    for _ in range(n):
        idx = src.find(old, idx + 1)
        if idx < 0:
            raise SystemExit("pattern not found x%d: %r" % (n, old))
    return src[:idx] + new + src[idx + len(old):]


def rreplace(src, old, new, n=1):
    return src.replace(old, new, n)


MUTATIONS = [
    ("M1 falsify no longer requires --handoff",
     lambda s: rreplace(s, "if falsify and handoff is None:", "if False and handoff is None:")),
    ("M2 falsify missing-section check deleted",
     lambda s: nth_replace(s, "if not any(section in heading for heading in headings):",
                           "if False:", 2)),
    ("M3 falsify verdict-marker check deleted",
     lambda s: rreplace(s, "if not any(marker in entry for marker in FALSIFY_VERDICT_MARKERS):",
                        "if False:")),
    ("M4 'undecided' dropped from required falsify sections",
     lambda s: rreplace(s, 'FALSIFY_SECTIONS = ("我确认成立的", "我驳倒的", "未决")',
                        'FALSIFY_SECTIONS = ("我确认成立的", "我驳倒的")')),
    ("M5 falsify finding-ref check deleted",
     lambda s: rreplace(s, "if not any(FINDING_REF_RE.search(entry) for entry in entries):",
                        "if False:")),
    ("M6 handoff required-section check deleted",
     lambda s: nth_replace(s, "if not any(section in heading for heading in headings):",
                           "if False:", 1)),
    ("M7 handoff provenance check deleted",
     lambda s: rreplace(s, "if provenance_of(stripped) is None:", "if False:")),
    ("M8 red-too-short threshold 8 -> 1",
     lambda s: rreplace(s, "    if len(text) < 8:", "    if len(text) < 1:")),
    ("M9 resolve_red removed (red 'same as above' no longer resolved)",
     lambda s: rreplace(s, "    red = resolve_red(fields).strip() if raw_red is not None else \"\"",
                        "    red = (raw_red or \"\").strip()")),
    ("M10 falsify requires --handoff: message text changed (stderr pin)",
     lambda s: rreplace(s, '"--falsify 必须同时给出 --handoff：对抗性复审的对象是"',
                        '"--falsify 需要 --handoff：对抗性复审的对象是"')),
]

src0 = open(GATE_SRC, "rb").read().decode("utf-8")
root = tempfile.mkdtemp(prefix="fer-mut-r4-")
print("temp root: " + root)
env = dict(os.environ)
env["PYTHONUTF8"] = "1"
env["PYTHONDONTWRITEBYTECODE"] = "1"

for label, mutate in MUTATIONS:
    case = os.path.join(root, re.sub(r"[^A-Za-z0-9]+", "_", label))
    os.makedirs(case, exist_ok=True)
    mutated = mutate(src0)
    with open(os.path.join(case, "check_review_report.py"), "wb") as fh:
        fh.write(mutated.encode("utf-8"))
    shutil.copyfile(TEST_SRC, os.path.join(case, "test_check_review_report.py"))
    proc = subprocess.run([sys.executable, os.path.join(case, "test_check_review_report.py")],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    out = proc.stdout.decode("utf-8", "replace")
    summary = [ln for ln in out.splitlines() if ln.startswith("共 ")]
    reds = [ln for ln in out.splitlines() if ln.startswith("[ RED ]")]
    print("")
    print("=== " + label + " -> exit " + str(proc.returncode))
    print("    " + (summary[0] if summary else "(no summary)"))
    for line in reds:
        print("    " + line.strip())
    if not reds:
        print("    (no RED case -- the rule is NOT pinned)")

shutil.rmtree(root, ignore_errors=True)
