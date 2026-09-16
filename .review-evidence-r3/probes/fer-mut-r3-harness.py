# -*- coding: utf-8 -*-
"""Targeted-mutation harness for check_review_report.py.

Copies gate + regression suite into a temp dir, applies one textual mutation at
a time, and records which assertions go RED. Read-only w.r.t. the repo.
"""
import io, os, re, shutil, subprocess, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO = r"C:\Users\dupenglai\.dsh\tmp\fer-repo\fresh-eyes-review\scripts"
ROOT = r"C:\Users\dupenglai\AppData\Local\Temp\fer-mut-r3"

MUTATIONS = [
    ("M1_drop_falsify_requires_handoff", """    if falsify and handoff is None:""",
     """    if False and falsify and handoff is None:"""),
    ("M2_drop_falsify_section_check", """    for section in FALSIFY_SECTIONS:""",
     """    for section in ():"""),
    ("M3_drop_falsify_marker_check", """            if not any(marker in stripped for marker in FALSIFY_VERDICT_MARKERS):""",
     """            if False:"""),
    ("M4_drop_unresolved_section", """FALSIFY_SECTIONS = ("我确认成立的", "我驳倒的", "未决")""",
     """FALSIFY_SECTIONS = ("我确认成立的", "我驳倒的")"""),
    ("M5_drop_handoff_section_presence", """            if any(section in heading for section in HANDOFF_REQUIRED_SECTIONS):""",
     """            if "范围" in heading:"""),
    ("M6_drop_handoff_provenance_check", """            if not any(marker in stripped for marker in PROVENANCE_MARKERS):""",
     """            if False:"""),
    ("M7_drop_handoff_entries_check", """    if entries == 0:""",
     """    if False:"""),
    ("M8_weaken_red_len", """    if len(text) < 8:""", """    if len(text) < 1:"""),
]


def main():
    if os.path.isdir(ROOT):
        shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(ROOT)

    base = os.path.join(ROOT, "base")
    os.makedirs(base)
    gate_src = os.path.join(REPO, "check_review_report.py")
    test_src = os.path.join(REPO, "test_check_review_report.py")
    shutil.copy(gate_src, os.path.join(base, "check_review_report.py"))
    shutil.copy(test_src, os.path.join(base, "test_check_review_report.py"))

    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    def run(d):
        p = subprocess.run([sys.executable, os.path.join(d, "test_check_review_report.py")],
                           cwd=d, capture_output=True, env=env)
        text = p.stdout.decode("utf-8", "replace")
        reds = [re.search(r"^\[ RED \] +(\S+)", line).group(1)
                for line in text.splitlines()
                if re.search(r"^\[ RED \] +(\S+)", line)]
        totals = [line for line in text.splitlines() if line.startswith("共 ")]
        return p.returncode, reds, (totals[-1] if totals else "(no total)")

    rc, reds, total = run(base)
    print("BASELINE exit=%d reds=%s %s" % (rc, reds, total))

    for name, old, new in MUTATIONS:
        d = os.path.join(ROOT, name)
        os.makedirs(d)
        source = open(gate_src, encoding="utf-8").read()
        if source.count(old) != 1:
            print("SKIP %s : anchor count=%d" % (name, source.count(old)))
            continue
        open(os.path.join(d, "check_review_report.py"), "w", encoding="utf-8").write(
            source.replace(old, new))
        shutil.copy(test_src, os.path.join(d, "test_check_review_report.py"))
        rc, reds, total = run(d)
        print("")
        print("MUTATION %s -> suite exit=%d" % (name, rc))
        print("  suite summary: %s" % total)
        print("  RED assertions: %s" % (reds if reds else "NONE (mutation survives)"))


main()
