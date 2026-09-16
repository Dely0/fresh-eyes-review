#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Why the regression suite is RED under the documented command.

The gate reconfigures sys.stdout to UTF-8 but not sys.stderr, so its Chinese
stderr messages land in the console locale (cp936 here). The suite decodes the
child's stderr as UTF-8; the one assertion that checks Chinese stderr text
(`falsify_requires_handoff_flag`, added by the F4 fix) then cannot find it.

Transcript is written to the path given as argv[1] in UTF-8.
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = r"C:\Users\dupenglai\.dsh\tmp\fer-repo"
GATE = os.path.join(REPO, "fresh-eyes-review", "scripts", "check_review_report.py")

out_path = sys.argv[1]
out = open(out_path, "w", encoding="utf-8", newline="\n")


def say(line=""):
    out.write(line + "\n")


root = tempfile.mkdtemp(prefix="fer-enc-r4-")
falsify_report = os.path.join(root, "falsify.md")
open(falsify_report, "w", encoding="utf-8").write(
    "### 对抗性复审\n\n## 我确认成立的\n- F1 x · 判定：成立\n")

replay_dir = os.path.join(root, "replay")
os.makedirs(os.path.join(replay_dir, "ev"), exist_ok=True)
open(os.path.join(replay_dir, "report.md"), "w", encoding="utf-8").write(
    "### F1 回声 · 严重度：高\n"
    "- 位置：src/a.py:1\n"
    "- 复现：python -c \"print('checked=1')\"\n"
    "- 证据文件：ev/F1.txt\n"
    "- 实测：见证据文件\n")
open(os.path.join(replay_dir, "src_a.py"), "w", encoding="utf-8")
os.makedirs(os.path.join(replay_dir, "src"), exist_ok=True)
open(os.path.join(replay_dir, "src", "a.py"), "w", encoding="utf-8").write("x = 1\n")
open(os.path.join(replay_dir, "ev", "F1.txt"), "wb").write(b"[exit code: 0]\nchecked=1\n")

env = dict(os.environ)
env["PYTHONDONTWRITEBYTECODE"] = "1"
env.pop("PYTHONUTF8", None)
env.pop("PYTHONIOENCODING", None)

say("== 1. 门禁 --falsify（缺 --handoff）写到 stderr 的原始字节 ==")
proc = subprocess.run([sys.executable, GATE, "--falsify", falsify_report],
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
say("gate exit = " + str(proc.returncode))
say("stderr raw bytes = " + repr(proc.stderr))
say("期望子串 " + repr("必须同时给出 --handoff"))
say("  按 UTF-8 解码后包含它吗（测试脚本就是这么读的）："
    + str("必须同时给出 --handoff" in proc.stderr.decode("utf-8", "replace")))
say("  按 GB18030 解码后包含它吗（本机控制台就是这么读的）："
    + str("必须同时给出 --handoff" in proc.stderr.decode("gb18030", "replace")))
say("  按 UTF-8 解码后的文本（前 80 字符）："
    + proc.stderr.decode("utf-8", "replace")[:80].replace("\r", "\\r").replace("\n", "\\n"))

say("")
say("== 2. 同一进程里 stdout 与 stderr 的编码不一致 ==")
say("门禁在 import 时只对 sys.stdout 调了 reconfigure(encoding='utf-8')。")
say("让它打印一个 GBK 编不出来的字符 ▶（[OK/▶ ] 标签），看它死在哪个流上：")
proc2 = subprocess.run([sys.executable, GATE, "--replay", os.path.join(replay_dir, "report.md")],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
say("gate exit = " + str(proc2.returncode))
say("stdout raw bytes = " + repr(proc2.stdout))
say("  注意 stdout 里的 '\\xe2\\x96\\xb6' 就是 UTF-8 的 ▶ —— stdout 是 UTF-8。")
say("stderr raw bytes = " + repr(proc2.stderr))

say("")
say("== 3. 被重定向到文件时，stderr 的中文是乱码 ==")
errfile = os.path.join(root, "err.bin")
with open(errfile, "wb") as fh:
    subprocess.run([sys.executable, GATE, "--falsify", falsify_report],
                   stdout=subprocess.DEVNULL, stderr=fh, env=env)
raw = open(errfile, "rb").read()
say("stderr 文件按 UTF-8 读（CI 日志、测试脚本的做法）：")
say("  " + raw.decode("utf-8", "replace").strip())
say("stderr 文件按 GB18030 读（本机控制台的做法）：")
say("  " + raw.decode("gb18030", "replace").strip())

out.close()
shutil.rmtree(root, ignore_errors=True)
print("written: " + out_path)
