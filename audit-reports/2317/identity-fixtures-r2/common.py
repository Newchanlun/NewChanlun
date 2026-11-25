"""固定输入，所有可写仓库都是 TMPDIR 下自己的副本。"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SRC = Path(__file__).resolve().parents[3]
BASE = "106ace51a1b6eff0e8f48d1ae5c7da573a995e8a"
A = "formal_math/sources/admit"
B = "docs/chanlun/text/blog"
G = "formal_math/verification/gate11"
PIN = G + "/admit_identity.pin"
CHECK = G + "/check_admit_identity.py"
SELF = G + "/selftest_identity.py"
SPEC = A + "/SPEC.md"
ENV = dict(os.environ, LC_ALL="C", GIT_AUTHOR_NAME="Audit", GIT_COMMITTER_NAME="Audit",
           GIT_AUTHOR_EMAIL="audit@example.invalid", GIT_COMMITTER_EMAIL="audit@example.invalid")


def box():
    tmp = Path(os.environ["TMPDIR"]).resolve()
    if not tmp.is_relative_to("/Volumes/AgentStorage") or tmp == Path("/Volumes/AgentStorage"):
        raise ValueError("请先把 TMPDIR 指向 /Volumes/AgentStorage 下专用的新目录")
    return Path(tempfile.mkdtemp(dir=tmp, prefix="fm09b-"))


def run(cwd, *args, data=None):
    return subprocess.run(args, cwd=cwd, input=data, capture_output=True, env=ENV)


def git(cwd, *args, data=None):
    r = run(cwd, "git", *args, data=data)
    r.check_returncode()
    return r.stdout


def clone(parent, name, *config, checkout=True):
    c = parent / name
    git(parent, "clone", "-q", "--no-checkout", "--shared", *config, SRC, c)
    if checkout:
        git(c, "switch", "-q", "--detach", BASE)
    return c


def gate(c, *args, root=None):
    return run(c, sys.executable, "-IB", SRC / CHECK, "--root", root or ".", *args)


def summary(label, r, *, limit=1):
    lines = (r.stderr or r.stdout).decode(errors="backslashreplace").splitlines()
    print(f"{label}: rc={r.returncode}; " + " | ".join(lines[:limit]), flush=True)
    return lines


def commit(c):
    git(c, "commit", "-qm", "independent audit fixture", "--no-verify")
    return git(c, "rev-parse", "HEAD").strip().decode()


def compact(parent):
    """投影仅保留自测需要的输入；从固定提交的文件对象逐字节导出。"""
    c = parent / "projection"
    c.mkdir()
    git(c, "init", "-q")
    for name in git(SRC, "ls-tree", "-rz", "--name-only", BASE, "--",
                    A, B, PIN, CHECK, SELF, ".gitattributes").split(b"\0"):
        if not name:
            continue
        f = c / os.fsdecode(name)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(git(SRC, "cat-file", "blob", os.fsencode(BASE + ":") + name))
    git(c, "add", "-f", ".")
    commit(c)
    return c
