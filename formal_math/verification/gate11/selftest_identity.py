#!/usr/bin/env python3
"""check_admit_identity.py 的自测：在临时克隆里逐种改动并提交，核退出码与红行。

每个用例从同一份干净克隆出发（共享对象库的克隆，用完即删；临时目录跟随 TMPDIR）；先断言未改动的克隆为绿（阴性对照）。
用法：python3 -I formal_math/verification/gate11/selftest_identity.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
A = "formal_math/sources/admit"
B = "docs/chanlun/text/blog"
G = "formal_math/verification/gate11"
T = A + "/candidate/tier1_candidate.jsonl"
ENV = dict(os.environ, LC_ALL="C", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def sh(cwd, *cmd):
    return subprocess.run(cmd, cwd=cwd, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def git(cwd, *args):
    r = sh(cwd, "git", *args)
    if r.returncode:
        raise RuntimeError("git %s: %s" % (args, r.stderr.decode()))
    return r.stdout


def check(cwd, *extra):
    r = sh(cwd, sys.executable, "-I", G + "/check_admit_identity.py", *extra)
    return r.returncode, r.stderr.decode()


def flip(path):
    with open(path, "r+b") as f:
        b = f.read(1)
        f.seek(0)
        f.write(bytes([b[0] ^ 1]))


def commit(c):
    git(c, "add", "-A", "-f", ".")
    git(c, "commit", "-q", "-m", "x", "--no-verify")


# 每个用例：(名字, 改动函数, 是否提交, 期望退出码, 红行里必须出现的子串)
def m_table(c): flip(os.path.join(c, T))
def m_symlink(c):
    p = os.path.join(c, A, "SPEC.md"); q = os.path.join(c, G, "SPEC.copy")
    shutil.copy(p, q); os.remove(p); os.symlink(os.path.relpath(q, os.path.dirname(p)), p)
def m_pycache(c):
    d = os.path.join(c, A, "__pycache__"); os.mkdir(d); open(os.path.join(d, "errata.jsonl"), "w").write("x\n")
def m_extra(c): open(os.path.join(c, A, "candidate", "extra.md"), "w").write("x\n")
def m_delete(c): os.remove(os.path.join(c, A, "SPEC.md"))
def m_mode(c): os.chmod(os.path.join(c, A, "candidate", "merge.py"), 0o755)
def m_corpus(c): flip(os.path.join(c, B, sorted(os.listdir(os.path.join(c, B)))[0]))
def m_corpus_extra(c): open(os.path.join(c, B, "999-x.md"), "w").write("x\n")
def m_corpus_sub(c):
    d = os.path.join(c, B, "sub"); os.mkdir(d); open(os.path.join(d, "a.md"), "w").write("x\n")
def m_pin_comment(c): open(os.path.join(c, G, "admit_identity.pin"), "ab").write(b"# x\n")
def m_synced(c):
    flip(os.path.join(c, T)); commit(c)
    out = sh(c, sys.executable, "-I", G + "/check_admit_identity.py", "--print-pin").stdout
    open(os.path.join(c, G, "admit_identity.pin"), "wb").write(out)
def m_replace(c):
    flip(os.path.join(c, T)); new = git(c, "hash-object", "-w", T).decode().strip()
    git(c, "checkout", "-q", "--", T)
    old = git(c, "rev-parse", "HEAD:" + T).decode().strip()
    git(c, "replace", old, new)
    os.remove(os.path.join(c, T)); git(c, "checkout", "-q", "--", T)  # 经替换引用检出，工作区拿到被换的内容


def m_eol(c):
    open(os.path.join(c, ".gitattributes"), "a").write("\n" + G + "/admit_identity.pin text eol=crlf\n")
    commit(c)
    f = os.path.join(c, G, "admit_identity.pin"); os.remove(f); git(c, "checkout", "-q", "--", f)
    assert b"\r\n" in open(f, "rb").read()


def add_empty_subtree(c, prefix, name):
    """用底层命令造一个提交：prefix 下多一个空目录节点（普通检出不会生成它）。"""
    empty = subprocess.run(["git", "mktree"], cwd=c, env=ENV, input=b"",
                           stdout=subprocess.PIPE, check=True).stdout.decode().strip()
    parts = prefix.split("/")
    def rebuild(rev_path, depth):
        listing = git(c, "ls-tree", "-z", "HEAD:" + rev_path if rev_path else "HEAD")
        recs = [r for r in listing.split(b"\0") if r]
        if depth == len(parts):
            recs.append(b"040000 tree " + empty.encode() + b"\t" + name.encode())
        else:
            child = rebuild((rev_path + "/" if rev_path else "") + parts[depth], depth + 1)
            recs = [(b"040000 tree " + child.encode() + b"\t" + parts[depth].encode())
                    if r.split(b"\t", 1)[1] == parts[depth].encode() else r for r in recs]
        return subprocess.run(["git", "mktree", "-z"], cwd=c, env=ENV, input=b"\0".join(recs) + b"\0",
                              stdout=subprocess.PIPE, check=True).stdout.decode().strip()
    top = rebuild("", 0)
    new = git(c, "commit-tree", top, "-p", "HEAD", "-m", "empty subtree").decode().strip()
    git(c, "update-ref", "HEAD", new)


def m_empty_corpus(c): add_empty_subtree(c, B, "archive")
def m_empty_admit(c): add_empty_subtree(c, A, "archive")
def m_dirty_exec(c): os.chmod(os.path.join(c, A, "candidate", "merge.py"), 0o755)
def m_dirty_root_link(c):
    src = os.path.join(c, A); dst = os.path.join(c, "formal_math", "admit-moved")
    os.rename(src, dst); os.symlink(dst, src)
def m_dirty_parent_link(c):
    src = os.path.join(c, "docs", "chanlun", "text"); dst = os.path.join(c, "docs", "text-moved")
    os.rename(src, dst); os.symlink(dst, src)


CASES = [
    # 钉选文件检出成 CRLF（.gitattributes），受检内容未变：必须仍绿。
    ("pin-checked-out-crlf", m_eol, False, 0, ""),
    ("empty-subtree-corpus", m_empty_corpus, False, 1, "不含文件的目录"),
    ("empty-subtree-admit", m_empty_admit, False, 1, "不含文件的目录"),
    ("dirty-exec-bit", m_dirty_exec, False, 1, "工作区文件带可执行位"),
    ("dirty-root-symlink", m_dirty_root_link, False, 1, "工作区路径不是目录"),
    ("dirty-parent-symlink", m_dirty_parent_link, False, 1, "工作区路径不是目录"),
    ("table-byte", m_table, True, 1, "与钉选"),
    ("symlink-same-content", m_symlink, True, 1, "非普通文件"),
    ("tracked-in-pycache", m_pycache, True, 1, "与钉选"),
    ("extra-tracked", m_extra, True, 1, "与钉选"),
    ("delete-file", m_delete, True, 1, "与钉选"),
    ("exec-bit", m_mode, True, 1, "非普通文件"),
    ("corpus-byte", m_corpus, True, 1, "语料指纹"),
    ("corpus-extra-file", m_corpus_extra, True, 1, "语料指纹"),
    ("corpus-subdir", m_corpus_sub, True, 1, "语料目录里有意外条目"),
    ("pin-comment-line", m_pin_comment, True, 1, "与钉选"),
    ("dirty-table", m_table, False, 1, "工作区内容与提交不同"),
    ("dirty-untracked-pycache", m_pycache, False, 1, "工作区多出"),
    ("dirty-symlink", m_symlink, False, 1, "工作区不是普通文件"),
    ("dirty-corpus", m_corpus, False, 1, "工作区内容与提交不同"),
    ("dirty-delete", m_delete, False, 1, "工作区缺文件"),
    ("git-replace-object", m_replace, False, 1, "工作区内容与提交不同"),
    # 已明示的信任前提：表与钉选在同一次改动里一起换，本检查不拦（由路径权限与评审负责）。
    ("table-and-pin-synced", m_synced, True, 0, ""),
]


def main():
    root = git(HERE, "rev-parse", "--show-toplevel").decode().strip()
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "base")
        git(tmp, "clone", "-q", "--shared", root, base)
        # 把当前工作区里的检查脚本带进克隆（它可能尚未提交）；钉选一律取自提交
        for f in ("check_admit_identity.py",):
            shutil.copy(os.path.join(HERE, f), os.path.join(base, G, f))
        if git(base, "status", "--porcelain"):
            commit(base)
        rc, err = check(base)
        if rc != 0:
            print("阴性对照不绿：rc=%d %s" % (rc, err)); return 1
        for i, (name, fn, do_commit, want_rc, want_sub) in enumerate(CASES):
            c = os.path.join(tmp, "c%d" % i)
            git(tmp, "clone", "-q", "--shared", base, c)
            fn(c)
            if do_commit:
                commit(c)
            rc, err = check(c)
            ok = rc == want_rc and want_sub in err
            print("%s %-26s rc=%d %s" % ("ok  " if ok else "FAIL", name, rc, err.strip().splitlines()[:1]))
            if not ok:
                fails.append(name)
            shutil.rmtree(c, ignore_errors=True)
    print("身份检查自测：%d 项，不符 %d" % (len(CASES) + 1, len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
