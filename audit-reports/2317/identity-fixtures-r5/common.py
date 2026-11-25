"""只在 TMPDIR 下创建私有仓库；所有源输入固定到受审提交。"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SRC = Path(__file__).resolve().parents[3]
REV = "9e2135af6a1560c0758d611c7cd3d5f6e655b1a8"
G = "formal_math/verification/gate11"
CHECK, SELF, PIN = (f"{G}/{name}" for name in
                    ("check_admit_identity.py", "selftest_identity.py", "admit_identity.pin"))
ADMIT, BLOG = "formal_math/sources/admit", "docs/chanlun/text/blog"
ENV = dict(os.environ, GIT_AUTHOR_NAME="Review", GIT_COMMITTER_NAME="Review",
           GIT_AUTHOR_EMAIL="review@example.invalid", GIT_COMMITTER_EMAIL="review@example.invalid")


def git(repo, *args, data=None):
    return subprocess.run(["git", "-C", repo, *args], env=ENV, input=data, check=True,
                          stdout=subprocess.PIPE).stdout


def sandbox():
    tmp = Path(ENV["TMPDIR"]).resolve()
    if Path("/Volumes/AgentStorage") not in tmp.parents:
        raise ValueError("请使用 /Volumes/AgentStorage 下的专用 TMPDIR")
    parent = Path(tempfile.mkdtemp(prefix="r5-", dir=tmp))
    repo = parent / "repo"
    git(parent, "clone", "-q", "--shared", "--no-checkout", str(SRC), str(repo))
    return repo


def checker(repo):
    # 无检出克隆，只提取固定版本脚本；--root 与脚本位置默认值分别测试。
    path = repo / CHECK
    path.parent.mkdir(parents=True)
    path.write_bytes(git(repo, "show", f"{REV}:{CHECK}"))
    return str(path)


def python(cwd, *args, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE):
    return subprocess.run([sys.executable, "-I", *args], cwd=cwd, env=env, stdout=stdout, stderr=stderr)
