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


def say(text):
    """按 UTF-8 字节直接写标准输出，与 locale 无关。"""
    data = (text + "\n").encode("utf-8", "backslashreplace")
    while data:
        data = data[os.write(1, data):]


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
# 「不提交」的用例只动工作区：检查只读提交，所以必须仍绿。
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





def m_wt_noise(c):
    flip(os.path.join(c, T)); os.chmod(os.path.join(c, A, "SPEC.md"), 0o755)
    open(os.path.join(c, A, ".DS_Store"), "w").write("x")


CASES = [
    ("worktree-only-changes", m_wt_noise, False, 0, ""),
    # 钉选文件检出成 CRLF（.gitattributes），受检内容未变：必须仍绿。
    ("pin-checked-out-crlf", m_eol, False, 0, ""),
    ("empty-subtree-corpus", m_empty_corpus, False, 1, "不含文件的目录"),
    ("empty-subtree-admit", m_empty_admit, False, 1, "不含文件的目录"),
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
    # 替换引用不影响判定：提交里的对象没变，仍绿（检查器关闭了替换引用）。
    ("git-replace-object", m_replace, False, 0, ""),
    # 已明示的信任前提：表与钉选在同一次改动里一起换，本检查不拦（由路径权限与评审负责）。
    ("table-and-pin-synced", m_synced, True, 0, ""),
]


def main():
    top = git(HERE, "rev-parse", "--show-toplevel")
    root = os.fsdecode(top[:-1] if top.endswith(b"\n") else top)
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
            say("阴性对照不绿：rc=%d %s" % (rc, err)); return 1
        for i, (name, fn, do_commit, want_rc, want_sub) in enumerate(CASES):
            c = os.path.join(tmp, "c%d" % i)
            git(tmp, "clone", "-q", "--shared", base, c)
            fn(c)
            if do_commit:
                commit(c)
            rc, err = check(c)
            ok = rc == want_rc and want_sub in err
            say("%s %-26s rc=%d %s" % ("ok  " if ok else "FAIL", name, rc, err.strip().splitlines()[:1]))
            if not ok:
                fails.append(name)
            shutil.rmtree(c, ignore_errors=True)
        # 输出环境。断管用例用可编码的环境，并断言诊断确是 EPIPE；ASCII 用例断言绿行能按 UTF-8 解出。
        cmd = [sys.executable, "-I", "-X", "utf8=0", G + "/check_admit_identity.py"]
        asc = dict(ENV, LC_ALL="C", LANG="C")
        utf = dict(ENV, LC_ALL="C.UTF-8", LANG="C.UTF-8")
        r, w = os.pipe(); os.close(r)
        run = lambda extra, env, out: subprocess.run(cmd + extra, cwd=base, env=env, stdout=out, stderr=subprocess.PIPE)
        g = run([], asc, subprocess.PIPE)
        b1, b2 = run([], utf, w), run(["--print-pin"], utf, w)
        os.close(w)
        io_cases = [
            ("ascii-locale-green", g.returncode == 0 and "GREEN" in g.stdout.decode("utf-8") and "身份检查" in g.stdout.decode("utf-8")),
            ("ascii-locale-bad-rev", run(["--rev", "nope"], asc, subprocess.PIPE).returncode == 2),
            ("stdout-broken-pipe", b1.returncode == 2 and b"Broken pipe" in b1.stderr),
            ("print-pin-broken-pipe", b2.returncode == 2 and b"Broken pipe" in b2.stderr),
            ("bad-argument", run(["--bogus"], asc, subprocess.PIPE).returncode == 2),
            ("no-abbreviation", run(["--print-pi"], asc, subprocess.PIPE).returncode == 2),
            ("missing-option-value", run(["--rev"], asc, subprocess.PIPE).returncode == 2),
        ]
        for name, ok in io_cases:
            say("%s %s" % ("ok  " if ok else "FAIL", name))
            if not ok:
                fails.append(name)
    say("身份检查自测：%d 项，不符 %d" % (len(CASES) + 8, len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
