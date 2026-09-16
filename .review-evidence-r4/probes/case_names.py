#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Did any of the 36 pre-change assertions get dropped or renamed?"""
import os
import re
import subprocess
import sys

REPO = r"C:\Users\dupenglai\.dsh\tmp\fer-repo"
out = open(sys.argv[1], "w", encoding="utf-8", newline="\n")
new = open(os.path.join(REPO, "fresh-eyes-review", "scripts", "test_check_review_report.py"),
           encoding="utf-8").read()
old = subprocess.run(["git", "show", "HEAD:fresh-eyes-review/scripts/test_check_review_report.py"],
                     cwd=REPO, stdout=subprocess.PIPE).stdout.decode("utf-8")


def names(src):
    i = src.index("CASES = [")
    j = src.index("\ndef run_case")
    return re.findall(r'\("([a-z0-9_]+)",', src[i:j])


n, o = names(new), names(old)
out.write("old case names  = " + str(len(o)) + "\n")
out.write("new case names  = " + str(len(n)) + "\n")
missing = [x for x in o if x not in n]
out.write("old names missing from the new suite = " + str(missing) + "\n")
added = [x for x in n if x not in o]
out.write("new case names = " + str(added) + "\n")
out.write("(suite total assertions = cases + 2 hand-written = " + str(len(n) + 2) + ")\n")
out.close()
print("written: " + sys.argv[1])
