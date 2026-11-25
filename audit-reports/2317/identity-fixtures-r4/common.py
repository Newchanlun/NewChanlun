"""固定审查输入；只在调用者给定的 AgentStorage 临时目录内创建夹具仓库。"""
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

SRC = Path(__file__).resolve().parents[3]
REV = "b5492c8d7031e7f2e621152a8787bb6ffac32c92"
A, B = "formal_math/sources/admit", "docs/chanlun/text/blog"
G = "formal_math/verification/gate11/"
CHECK, SELF, PIN = (G + n for n in ("check_admit_identity.py", "selftest_identity.py", "admit_identity.pin"))
ENV = dict(os.environ, GIT_AUTHOR_NAME="Review", GIT_COMMITTER_NAME="Review",
           GIT_AUTHOR_EMAIL="review@example.invalid", GIT_COMMITTER_EMAIL="review@example.invalid")


def box():
    d = Path(ENV["TMPDIR"]).resolve()
    if Path("/Volumes/AgentStorage") not in d.parents:
        raise ValueError("TMPDIR 必须是 /Volumes/AgentStorage 下的专用子目录")
    return Path(tempfile.mkdtemp(dir=d, prefix="r4-"))


def git(repo, *args, data=None):
    return subprocess.run(["git", "-C", repo, *args], env=ENV, input=data,
                          stdout=subprocess.PIPE, check=True).stdout


def project(parent):
    repo = parent / "projection"
    repo.mkdir()
    paths = [A, B, CHECK, SELF, PIN, ".gitattributes"]
    payload = git(SRC, "archive", "--format=tar", REV, "--", *paths)
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        archive.extractall(repo, filter="data")
    git(repo, "init", "-q")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "add", "-f", ".")
    git(repo, "commit", "-qm", "projection")
    assert git(repo, "ls-tree", "HEAD", *paths) == git(SRC, "ls-tree", REV, *paths)
    return repo


def run(repo, *args, **kw):
    return subprocess.run([sys.executable, "-I", *args], cwd=repo,
                          **({"env": ENV, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE} | kw))
