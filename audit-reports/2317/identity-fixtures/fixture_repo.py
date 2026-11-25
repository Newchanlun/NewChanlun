"""从被审提交提取两个数据目录和三份受审文件，建最小的本地夹具仓库。"""
import os
import subprocess
import sys
from pathlib import Path

A = "formal_math/sources/admit"
B = "docs/chanlun/text/blog"
G = "formal_math/verification/gate11"
REV = "c7bd74255c0234363a968a91fa4f075038c5ba63"
CHECK = G + "/check_admit_identity.py"
FILES = [A, B, CHECK, G+"/admit_identity.pin", G+"/selftest_identity.py"]
ENV = dict(os.environ, GIT_AUTHOR_NAME="review", GIT_AUTHOR_EMAIL="review@example.invalid",
           GIT_COMMITTER_NAME="review", GIT_COMMITTER_EMAIL="review@example.invalid")


def run(root, *args, check=True, env=None, data=None):
    return subprocess.run(args, cwd=root, env=ENV | (env or {}), input=data,
                          capture_output=True, check=check)


def git(root, *args, **kw):
    return run(root, "git", *args, **kw).stdout


def seed(source, root):
    root.mkdir()
    archive = git(source, "archive", "--format=tar", REV, "--", *FILES)
    run(root, "tar", "-xf", "-", data=archive)
    git(root, "init", "-q")
    git(root, "add", "--", *FILES)
    git(root, "commit", "-qm", "基线")


def gate(script, root, *args, env=None):
    return run(root, sys.executable, "-I", str(script), "--root", str(root),
               *args, env=env, check=False)


def first(p):
    lines = (p.stdout + p.stderr).decode("utf-8", "backslashreplace").splitlines()
    return next((s for s in lines if s.startswith(("RED ", "GATE11", "无法运行"))),
                lines[0] if lines else "（无输出）")


def tmp_parent():
    parent = Path(os.environ["TMPDIR"]).resolve()
    if not parent.is_dir():
        raise SystemExit("先把 TMPDIR 指到本次审阅专用的新目录")
    return parent
