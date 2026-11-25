"""在独立对象库重建改过的一条目录链；直接调用固定提交的 CLI。"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import A, B, BASE, PIN, box, clone, gate, git, summary

def put(c, tree, parts, entry):
    name, *rest = parts
    old = {}
    for row in git(c, "ls-tree", "-z", tree).split(b"\0"):
        if row:
            meta, child = row.split(b"\t", 1)
            old[child] = meta
    if rest:
        sub = put(c, old[name].split()[2], rest, entry)
        old[name] = b"040000 tree " + sub
    elif entry is None:
        old.pop(name)
    else:
        old[name] = entry
    items = [v + b"\t" + k + b"\0" for k, v in old.items()]
    return git(c, "mktree", "-z", data=b"".join(items)).strip()

def altered(c, *edits):
    tree = git(c, "rev-parse", BASE + "^{tree}").strip()
    for path, entry in edits:
        tree = put(c, tree, os.fsencode(path).split(b"/"), entry)
    return git(c, "commit-tree", tree, "-p", BASE, "-m", "tree contrast").strip().decode()

def test(c, label, edit, rc, message):
    rev = altered(c, edit)
    r = gate(c, "--no-worktree", "--rev", rev)
    lines = summary(label, r, limit=2)
    assert r.returncode == rc and any(message in x for x in lines)
    return rev

if __name__ == "__main__":
    d = box()
    c = clone(d, "object-tests", checkout=False)
    git(c, "update-ref", "HEAD", BASE)
    empty = b"040000 tree " + git(c, "mktree", data=b"").strip()
    payload = git(c, "hash-object", "-w", "--stdin", data=b"irrelevant").strip()
    blob = b"100644 blob " + payload
    link = b"120000 blob " + payload
    module = b"160000 commit " + BASE.encode()
    cases = ((A, "准入"), (B, "语料"))
    for prefix, name in cases:
        target = prefix + ("/pass-a/decisions/empty" if prefix == A else "/void")
        test(c, name + "空树", (target, empty), 1, "不含文件的目录")
        for kind, item in (("缺失", None), ("文件", blob), ("符号链接", link), ("子模块", module)):
            test(c, name + "根" + kind, (prefix, item), 1, prefix + " 不是目录")
    test(c, "祖先是文件", ("docs/chanlun/text", blob), 1, B + " 不是目录")
    missing_module = b"160000 commit " + b"3" * 40
    for idx, item in enumerate((module, missing_module)):
        test(c, "子模块叶子 " + str(idx), (A + "/SPEC.md", item), 1, "非普通文件：160000 commit")
    test(c, "特殊字节位于准入目录内", (A.encode() + b"/x\t\xff.md", blob), 1, "与钉选")
    test(c, "换行位于准入文件名", (A.encode() + b"/x\ny.md", blob), 1, "路径含换行")
    rev = altered(c, (A + "-x", empty), (B + "2", empty),
                  (os.fsencode(B) + b"\t\xff", blob))
    r = gate(c, "--no-worktree", "--rev", rev)
    summary("三个前缀兄弟", r)
    assert r.returncode == 0
    for prefix, _ in cases:
        out = git(c, "ls-tree", "-r", "-t", "-z", "--full-tree", rev, "--", prefix + "/")
        paths = [r.split(b"\t", 1)[1] for r in out.split(b"\0") if r]
        ancestors = [p for p in paths if not p.startswith(prefix.encode() + b"/")]
        print("pathspec", prefix, "祖先", ancestors)
        assert all((prefix.encode() + b"/").startswith(p + b"/") for p in ancestors)
    test(c, "钉选缺失", (PIN, None), 2, "无法运行")
    test(c, "钉选是目录", (PIN, empty), 2, "无法运行")
    test(c, "钉选是子模块", (PIN, module), 2, "无法运行")
    rpin = test(c, "钉选是符号链接", (PIN, link), 1, "与钉选")
    git(c, "tag", "-a", "bad-pin", "-m", "pin contrast", rpin)
    for rev, expect in (("bad-pin", 1), ("bad-pin^", 0), (BASE, 0), (BASE[:12], 0),
                        ("HEAD", 0), ("HEAD@{0}", 0), ("HEAD^{tree}", 2), ("no-such-ref", 2)):
        r = gate(c, "--no-worktree", "--rev", rev)
        summary("rev " + rev, r)
        assert r.returncode == expect
