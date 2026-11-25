"""规范化、逐级目录诊断、关联工作树及浅合并检出。"""
import os
import subprocess
import sys
import unicodedata
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import A, B, BASE, CHECK, SELF, SRC, box, compact, gate, git, run, summary

def move_as_link(c, rel):
    src = c / rel
    dst = c.parent / "original"
    src.rename(dst)
    src.symlink_to(dst, target_is_directory=True)
    summary("目录链接 " + rel, gate(c))
    src.rename(c.parent / ("retained-link-" + src.name))
    dst.rename(src)

def leaf_spelling(c):
    src = c / A / "SPEC.md"
    different = src.with_name("spec.md")
    held = c.parent / "held-spelling"
    src.rename(held)
    held.rename(different)
    r = gate(c)
    lines = summary("叶文件硬盘拼写改变", r, limit=2)
    assert r.returncode == 1 and any("缺文件" in x for x in lines)
    different.rename(held)
    held.rename(src)

def closed_output(c):
    for opts in ([], ["--print-pin"]):
        read_end, write_end = os.pipe()
        os.close(read_end)
        try:
            r = subprocess.run([sys.executable, "-IB", SRC / CHECK, "--root", ".", *opts], cwd=c,
                               stdout=write_end, stderr=subprocess.PIPE)
        finally:
            os.close(write_end)
        print("下游已关闭 stdout", opts, r.returncode, r.stderr.decode().splitlines()[-1:])

if __name__ == "__main__":
    d = box()
    c = compact(d)
    for name in ("Ä", "Mixed"):
        (d / name).touch()
    print("APFS 名字等价：大小写", (d / "mixed").exists(), "规范分解", (d / "A\u0308").exists())
    names = [os.fsdecode(n) for n in git(SRC, "ls-tree", "-rz", "--name-only", BASE, "--", A, B).split(b"\0") if n]
    print("受检路径总数、NFC 与 NFD 有别数：", len(names),
          sum(unicodedata.normalize("NFC", n) != unicodedata.normalize("NFD", n) for n in names))
    for precompose in ("true", "false"):
        git(c, "config", "core.precomposeunicode", precompose)
        summary("core.precomposeunicode=" + precompose, gate(c))
    leaf_spelling(c)
    summary("相对路径指向真实的完整关联工作树", gate(d, "--rev", BASE, root=os.path.relpath(SRC, d)))
    # 只在独立克隆/投影内建立别名与关联检出。
    linked = d / "ending-newline\n"
    git(c, "worktree", "add", "-q", "--detach", linked, "HEAD")
    summary("换行结尾、关联分离工作树、自动定位", run(linked, sys.executable, "-IB", CHECK))
    summary("同一路径的原版自测", run(linked, sys.executable, "-IB", SELF), limit=2)
    for path in (B, "formal_math/sources"):
        move_as_link(c, path)
    folder = c / A
    folder.rename(d / "missing")
    summary("整个磁盘前缀缺失", gate(c))
    (d / "missing").rename(folder)
    other = git(c, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "side").strip()
    peer = git(c, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "main").strip()
    merge = git(c, "commit-tree", "HEAD^{tree}", "-p", other, "-p", peer, "-m", "merge").strip()
    git(c, "branch", "pr-merge", merge)
    shallow = d / "shallow"
    git(d, "clone", "-q", "--depth=1", "--branch=pr-merge", c.as_uri(), shallow)
    git(shallow, "switch", "-q", "--detach", "HEAD")
    raw = git(shallow, "cat-file", "-p", "HEAD")
    print("shallow=", git(shallow, "rev-parse", "--is-shallow-repository").strip(),
          "parents=", sum(x.startswith(b"parent ") for x in raw.splitlines()),
          "history=", git(shallow, "rev-list", "--count", "HEAD").strip())
    summary("浅克隆双亲合并提交、分离 HEAD", gate(shallow))
    closed_output(c)
    blob = git(c, "rev-parse", "HEAD:" + A + "/SPEC.md").decode().strip()
    obj = c / ".git/objects" / blob[:2] / blob[2:]
    obj.rename(d / "saved-object")
    result = gate(c, "--no-worktree")
    lines = summary("对象库读取失败", result, limit=3)
    print("最后一行", lines[-1])
