"""对象枚举单元测试：Git 的小型档案树中，空目录也是具名条目。无需被钉语料。"""
import importlib.util
import tempfile
from pathlib import Path
from sys import path

path.insert(0, str(Path(__file__).resolve().parent))
from fixture_repo import CHECK, git, tmp_parent

spec = importlib.util.spec_from_file_location("subject", Path.cwd()/CHECK)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)
root = Path(tempfile.mkdtemp(dir=tmp_parent()))
git(root, "init", "-q")
empty = git(root, "mktree", data=b"").strip()


def directory(name, subtree):
    record = b"040000 tree " + subtree + b"\t" + name + b"\n"
    return git(root, "mktree", data=record).strip()


sample = directory(b"samples", directory(b"archive", empty))
rev = git(root, "commit-tree", sample, "-m", "目录枚举样本").decode().strip()
stored = [p for p in git(root, "ls-tree", "-rt", "--name-only", rev, "--", "samples/").splitlines()
          if p.startswith(b"samples/")]
listed = [entry[0] for entry in subject.tree(str(root), rev, "samples")]
print("Git 对象中的条目", stored)
print("受审枚举器列出", listed)
assert stored == [b"samples/archive"]
git(root, "checkout", "-q", "--detach", rev)
print("普通检出生成 archive 目录：", (root/"samples/archive").is_dir())
raise SystemExit(int(not set(stored).issubset(listed)))
