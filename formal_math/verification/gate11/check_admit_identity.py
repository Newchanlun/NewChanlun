#!/usr/bin/env python3
"""门禁 11 阻断检查：入库准入材料与语料的身份（#2317）。

只回答一个问题：给定提交里的 `formal_math/sources/admit/` 与
`docs/chanlun/text/blog/`，是否就是过审时的那一份。只读 git 对象，不读工作区文件。
内容相同，过审时核实过的性质（790 行、重建零差分等）即随之成立，本脚本不再重算。

退出码：0 相符；1 不符；2 无法运行。调用方只应把 0 当作通过。只用标准库，`python3 -I` 运行。
"""
import argparse
import hashlib
import os
import subprocess
import sys

ADMIT = "formal_math/sources/admit"
BLOG = "docs/chanlun/text/blog"
CORPUS_BASELINE = "b6a35574ed6db3625da6d18f4e11c8976874ba66b0e888362e1769483f0c0a0d"
HERE = os.path.dirname(os.path.abspath(__file__))
PIN_PATH = "formal_math/verification/gate11/admit_identity.pin"
ENV = dict(os.environ, GIT_NO_REPLACE_OBJECTS="1", LC_ALL="C")


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], check=True,
                          stdout=subprocess.PIPE, env=ENV).stdout


def ls_tree(root, rev, *args):
    out = []
    for rec in git(root, "ls-tree", "-z", "--full-tree", *args).split(b"\0"):
        if rec:
            meta, path = rec.split(b"\t", 1)
            mode, typ, oid = meta.decode("ascii").split(" ")
            out.append((path, mode, typ, oid))
    return out


def tree(root, rev, prefix):
    """给定提交里 prefix 目录下的全部条目：[(路径字节串, 模式, 类型, 内容 sha256)]，按路径字节序。

    prefix 自身必须是目录；目录节点也在核对之列：只许出现文件路径实际需要的祖先目录，
    所以提交里记录的空子树、子模块、符号链接都会报出。类型不合格的条目不读内容。
    """
    pre = prefix.encode()
    top = ls_tree(root, rev, rev, "--", prefix)
    if [(p, t) for p, _, t, _ in top] != [(pre, "tree")]:
        raise ValueError("提交里 %s 不是目录" % prefix)
    out, dirs = [], set()
    for path, mode, typ, oid in ls_tree(root, rev, "-r", "-t", rev, "--", prefix + "/"):
        if not path.startswith(pre + b"/"):
            if typ != "tree" or not (pre + b"/").startswith(path + b"/"):
                raise ValueError("意外条目：%s %s %r" % (mode, typ, path))
        elif typ == "tree":
            dirs.add(path)
        elif typ == "blob" and mode == "100644":
            out.append((path, mode, typ, hashlib.sha256(git(root, "cat-file", "blob", oid)).hexdigest()))
        else:
            raise ValueError("非普通文件：%s %s %r" % (mode, typ, path))
    need = set()
    for path, _, _, _ in out:
        while b"/" in path:
            path = path.rsplit(b"/", 1)[0]
            if path.startswith(pre + b"/"):
                need.add(path)
    if dirs != need:
        raise ValueError("提交里有不含文件的目录：%r" % sorted(dirs ^ need))
    out.sort()
    return out


def pin_text(entries):
    """钉选文件的规范形式：每行 `模式 sha256 路径`，路径相对仓库根，按字节序，末尾换行。"""
    lines = []
    for path, mode, typ, digest in entries:
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


def emit(fd, data):
    """直接按 UTF-8 字节写文件描述符，不经 Python 的文本层与缓冲：与 locale 无关，写失败当场抛 OSError。"""
    if isinstance(data, str):
        data = (data + "\n").encode("utf-8", "backslashreplace")
    while data:
        data = data[os.write(fd, data):]


def note(text):
    """写标准错误；诊断写不出不改变结论。"""
    try:
        emit(2, text)
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--root", default=None)
    ap.add_argument("--rev", default="HEAD")
    ap.add_argument("--print-pin", action="store_true")
    a = ap.parse_args()
    bad = []
    try:
        root = a.root
        if root is None:
            top = git(HERE, "rev-parse", "--show-toplevel")
            root = os.fsdecode(top[:-1] if top.endswith(b"\n") else top)
        rev = git(root, "rev-parse", "--verify", a.rev + "^{commit}").decode().strip()
        if a.print_pin:
            emit(1, pin_text(tree(root, rev, ADMIT)))
            return 0
        # 钉选取自同一提交的 git 对象，不读检出的文件：检出时的换行转换不影响比对。
        pinned = git(root, "cat-file", "blob", rev + ":" + PIN_PATH)
        try:
            admit = tree(root, rev, ADMIT)
            if pin_text(admit) != pinned:
                bad.append("提交 %s 的 %s 与钉选 admit_identity.pin 不同" % (rev[:10], ADMIT))
        except ValueError as e:
            bad.append(str(e))
        try:
            blog = tree(root, rev, BLOG)
            fp = corpus_fingerprint(blog)
            if fp != CORPUS_BASELINE:
                bad.append("语料指纹 %s 不等于基线" % fp)
        except ValueError as e:
            bad.append(str(e))
        if not bad:
            # 成功提示写不出去就不算通过：调用方拿不到绿行时不应得到 0。
            emit(1, "GATE11 身份检查 GREEN：提交 %s，准入材料 %d 个文件与钉选相同，语料 %d 个文件指纹等于基线"
                 % (rev[:10], len(admit), len(blog)))
            return 0
    except (OSError, subprocess.CalledProcessError, ValueError) as e:
        # 运行故障：已经查出的不符照样报出，退 2。
        for b in bad:
            note("RED " + b)
        note("无法运行：%s" % e)
        return 2
    for b in bad:
        note("RED " + b)
    return 1


if __name__ == "__main__":
    sys.exit(main())
