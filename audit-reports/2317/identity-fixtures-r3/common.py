"""只读固定提交；本轮夹具的所有派生仓库都落在专用 TMPDIR。"""
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

SRC = Path(__file__).resolve().parents[3]
REV = "58627d62b25b5be91081205b82b96907d9a11330"
A, B = "formal_math/sources/admit", "docs/chanlun/text/blog"
G = "formal_math/verification/gate11/"
CHECK, SELF, PIN = (G + n for n in ("check_admit_identity.py", "selftest_identity.py", "admit_identity.pin"))
SPEC = A + "/SPEC.md"
ENV = dict(os.environ, LC_ALL="C", GIT_AUTHOR_NAME="Review", GIT_AUTHOR_EMAIL="review@example.invalid",
           GIT_COMMITTER_NAME="Review", GIT_COMMITTER_EMAIL="review@example.invalid")


def box():
    parent = Path(ENV["TMPDIR"]).resolve()
    assert parent != Path("/Volumes/AgentStorage") and parent.is_relative_to("/Volumes/AgentStorage")
    return Path(tempfile.mkdtemp(dir=parent, prefix="r3-"))


def run(cwd, *cmd, **kw):
    return subprocess.run(cmd, cwd=cwd, env=ENV, **{"capture_output": True, **kw})


def git(cwd, *args):
    p = run(cwd, "git", *args)
    if p.returncode:
        raise RuntimeError((args, p.returncode, p.stderr))
    return p.stdout


def gate(cwd, *args):
    return run(cwd, sys.executable, "-IB", CHECK, *args)


def project(parent):
    """取固定候选的两棵树和自测所需文件；创建不共享对象的微型仓库。"""
    c = parent / "projection"
    c.mkdir()
    data = git(SRC, "archive", "--format=tar", REV, "--", A, B, CHECK, SELF, PIN, ".gitattributes")
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(c, filter="data")
    git(c, "init", "-q")
    git(c, "config", "core.autocrlf", "false")
    git(c, "add", "-f", ".")
    git(c, "commit", "-qm", "projection")
    return c


def show(label, p):
    lines = (p.stderr or p.stdout or b"").decode(errors="backslashreplace").splitlines()
    print(f"{label}: rc={p.returncode}", *lines, sep="\n", flush=True)
