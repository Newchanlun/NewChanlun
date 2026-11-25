#!/usr/bin/env python3
"""门禁 11 阻断检查：入库准入材料与语料的身份（#2317）。

只回答一个问题：给定提交里的 `formal_math/sources/admit/` 与
`docs/chanlun/text/blog/`，是否就是过审时的那一份。
内容相同，过审时核实过的性质（790 行、重建零差分等）即随之成立，本脚本不再重算。

退出码：0 相符；1 不符；2 无法运行。只用标准库，`python3 -I` 运行。
"""
import argparse
import hashlib
import os
import stat
import subprocess
import sys

ADMIT = "formal_math/sources/admit"
BLOG = "docs/chanlun/text/blog"
CORPUS_BASELINE = "b6a35574ed6db3625da6d18f4e11c8976874ba66b0e888362e1769483f0c0a0d"
HERE = os.path.dirname(os.path.abspath(__file__))
PIN = os.path.join(HERE, "admit_identity.pin")
ENV = dict(os.environ, GIT_NO_REPLACE_OBJECTS="1", LC_ALL="C")


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], check=True,
                          stdout=subprocess.PIPE, env=ENV).stdout


def tree(root, rev, prefix):
    """给定提交里 prefix 目录下的全部条目：[(路径字节串, 模式, 类型, 内容 sha256)]，按路径字节序。"""
    out = []
    for rec in git(root, "ls-tree", "-r", "-z", "--full-tree", rev, "--", prefix + "/").split(b"\0"):
        if not rec:
            continue
        meta, path = rec.split(b"\t", 1)
        mode, typ, oid = meta.decode("ascii").split(" ")
        digest = hashlib.sha256(git(root, "cat-file", typ, oid)).hexdigest()
        out.append((path, mode, typ, digest))
    out.sort()
    return out


def pin_text(entries):
    """钉选文件的规范形式：每行 `模式 sha256 路径`，路径相对仓库根，按字节序，末尾换行。"""
    lines = []
    for path, mode, typ, digest in entries:
        if mode != "100644" or typ != "blob":
            raise ValueError("非普通文件：%s %s %r" % (mode, typ, path))
        if b"\n" in path:
            raise ValueError("路径含换行：%r" % path)
        lines.append(b"100644 " + digest.encode("ascii") + b" " + path + b"\n")
    return b"".join(lines)


def corpus_fingerprint(entries):
    """与 `cd docs/chanlun/text/blog && sha256sum *.md | sha256sum` 同值（文件名按字节序）。"""
    h = hashlib.sha256()
    for path, mode, typ, digest in entries:
        name = path[len(BLOG) + 1:]
        if mode != "100644" or typ != "blob" or b"/" in name or not name.endswith(b".md"):
            raise ValueError("语料目录里有意外条目：%s %s %r" % (mode, typ, path))
        h.update(digest.encode("ascii") + b"  " + name + b"\n")
    return h.hexdigest()


def disk_problems(root, entries, prefix):
    """工作区：prefix 下恰有这些普通文件、内容相同；不许有任何别的条目，不设例外。"""
    bad = []
    want = {os.fsdecode(p): d for p, _, _, d in entries}
    seen = set()
    for cur, dirs, files in os.walk(os.path.join(root, prefix), followlinks=False):
        for name in dirs + files:
            full = os.path.join(cur, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            st = os.lstat(full)
            if stat.S_ISDIR(st.st_mode):
                continue
            if not stat.S_ISREG(st.st_mode):
                bad.append("工作区不是普通文件：" + rel)
            elif rel not in want:
                bad.append("工作区多出文件：" + rel)
            else:
                seen.add(rel)
                with open(full, "rb") as f:
                    if hashlib.sha256(f.read()).hexdigest() != want[rel]:
                        bad.append("工作区内容与提交不同：" + rel)
    for cur, dirs, _ in os.walk(os.path.join(root, prefix), followlinks=False):
        for name in dirs:
            full = os.path.join(cur, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if os.path.islink(full):
                bad.append("工作区目录是符号链接：" + rel)
            elif not any(w.startswith(rel + "/") for w in want):
                bad.append("工作区多出目录：" + rel)
    bad += ["工作区缺文件：" + r for r in sorted(set(want) - seen)]
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--rev", default="HEAD")
    ap.add_argument("--no-worktree", action="store_true", help="只核提交，不核工作区（裸仓库用）")
    ap.add_argument("--print-pin", action="store_true", help="打印给定提交的规范钉选文本后退出")
    a = ap.parse_args()
    try:
        root = a.root or git(HERE, "rev-parse", "--show-toplevel").decode().rstrip("\n")
        rev = git(root, "rev-parse", "--verify", a.rev + "^{commit}").decode().strip()
        admit = tree(root, rev, ADMIT)
        blog = tree(root, rev, BLOG)
        if a.print_pin:
            sys.stdout.buffer.write(pin_text(admit))
            return 0
        with open(PIN, "rb") as f:
            pinned = f.read()
    except (OSError, subprocess.CalledProcessError) as e:
        print("无法运行：%s" % e, file=sys.stderr)
        return 2
    bad = []
    try:
        if pin_text(admit) != pinned:
            bad.append("提交 %s 的 %s 与钉选 admit_identity.pin 不同" % (rev[:10], ADMIT))
    except ValueError as e:
        bad.append(str(e))
    try:
        fp = corpus_fingerprint(blog)
        if fp != CORPUS_BASELINE:
            bad.append("语料指纹 %s 不等于基线" % fp)
    except ValueError as e:
        bad.append(str(e))
    if not a.no_worktree:
        bad += disk_problems(root, admit, ADMIT) + disk_problems(root, blog, BLOG)
    for b in bad:
        print("RED " + b, file=sys.stderr)
    if bad:
        return 1
    print("GATE11 身份检查 GREEN：提交 %s，准入材料 %d 个文件与钉选相同，语料 %d 个文件指纹等于基线"
          % (rev[:10], len(admit), len(blog)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
