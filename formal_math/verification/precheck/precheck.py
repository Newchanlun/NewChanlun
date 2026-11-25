#!/usr/bin/env python3
"""#2312 第一片：formal_math 合入前的纯静态预检，只读 git 对象。规则与信任前提见同目录 README.md。
用法：precheck.py [--trusted-change-approved] <仓库> <基线提交> <被审提交> <分支名>；退出码 0 绿、1 红、2 无法判定。"""
import os
import re
import subprocess
import sys

FLAG = b"--trusted-change-approved"
FM_ROOT, FM = b"formal_math", b"formal_math/"
GATE_DIR = FM + b"verification"
TRUSTED_FILES = (FM + b"lakefile.toml", FM + b"lake-manifest.json", FM + b"lean-toolchain",
                 b"scripts/fm_env.sh", b".github/workflows/formal-math.yml")
TRUSTED = TRUSTED_FILES + (GATE_DIR,)
TRUSTED_SURFACE = TRUSTED_FILES + (GATE_DIR + b"/",)
GOVERNED = (FM_ROOT,) + tuple(p for p in TRUSTED_FILES if not p.startswith(FM))
ROLES = {
    b"decl": tuple(FM + p for p in (
        b"Chan/Defs/", b"Chan/Hypotheses/", b"Chan/Audit/Literal/", b"Chan/Proxy/", b"ChanChallenge/",
        b"sources/", b"blueprint/", b"statement-lock.json", b"formalization.yaml", b"garbage-signoffs.yaml",
        b"HISTORY.md")),
    b"proof": tuple(FM + p for p in (
        b"Chan/Thm/", b"Chan/Proofs/", b"Chan/Exec/", b"Chan/Final/", b"Chan/Final.lean", b"Chan.lean",
        b"ChanTest/", b"ChanDyn/", b"ChanExplore/", b"ChanExplore.lean")),
    b"audit": tuple(FM + p for p in (
        b"Chan/Audit/Math/", b"Chan/Audit/Separation/", b"Chan/Audit/Cases/", b"ChanTest/")),
    b"infra": TRUSTED_SURFACE + (FM + b"README.md",),
}
TREE, BLOB = b"tree", b"blob"
CONTENT_ROOTS = (b"Chan", b"ChanTest", b"ChanChallenge", b"ChanDyn", b"ChanExplore")
TOP = dict.fromkeys(CONTENT_ROOTS + (b"verification", b"sources", b"blueprint"), TREE)
TOP.update(dict.fromkeys((b"Chan.lean", b"ChanExplore.lean", b"lakefile.toml", b"lake-manifest.json",
                          b"lean-toolchain", b"README.md", b"HISTORY.md", b"formalization.yaml",
                          b"statement-lock.json", b"garbage-signoffs.yaml"), BLOB))
WORD = rb"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*"
BRANCH = re.compile(rb"(decl|proof|audit|infra)/" + WORD + rb"(?:/" + WORD + rb")*")
SEGMENT = re.compile(rb"[A-Za-z0-9_][A-Za-z0-9_.-]*")
MODULE = re.compile(rb"[A-Za-z][A-Za-z0-9_]*")
OID = re.compile(rb"[0-9a-f]{40}|[0-9a-f]{64}")
TREE_ENTRY = re.compile(rb"([0-7]{6}) (blob|tree|commit) ([0-9a-f]{40}|[0-9a-f]{64})\t(.+)", re.S)
RAW_META = re.compile(rb":[0-7]{6} [0-7]{6} [0-9a-f]{40,64} [0-9a-f]{40,64} ([ADMT])")
ENV = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C", "GIT_NO_REPLACE_OBJECTS": "1",
       "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_GRAFT_FILE": os.devnull,
       "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}


class Fault(Exception):
    """运行故障或无法判定：args = (规则码, 对象, 说明)。"""


def git(repo, *args, ok=(0,)):
    """git 的标准错误原样透传；退出码不在 ok 内即运行故障。"""
    argv = [b"git", b"-C", repo, b"-c", b"advice.graftFileDeprecated=false", *args]
    try:
        p = subprocess.run(argv, env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    except OSError as e:
        raise Fault("GIT", b"git", "%s: %s" % (type(e).__name__, e.strerror))
    if p.returncode not in ok:
        raise Fault("GIT", args[0], "git 退出 %d" % p.returncode)
    return p.returncode, p.stdout


def commit(repo, rev):
    rc, out = git(repo, b"rev-parse", b"--verify", b"--quiet", b"--end-of-options", rev + b"^{commit}", ok=(0, 1))
    if rc or not OID.fullmatch(out.strip()):
        raise Fault("BAD_REV", rev, "解析不出提交")
    return out.strip()


def tree_at(repo, rev):
    """整棵树 {路径: (模式, 类型, 对象)}，目录节点也在内；同一目录的条目须按 git 顺序严格递增。"""
    entries, last = {}, {}
    for rec in git(repo, b"ls-tree", b"-r", b"-t", b"-z", b"--full-tree", rev)[1].split(b"\0")[:-1]:
        m = TREE_ENTRY.fullmatch(rec)
        if not m:
            raise Fault("GIT", b"ls-tree", "输出无法解读")
        mode, kind, oid, path = m.groups()
        parent, _, name = path.rpartition(b"/")
        key = name + b"/" if kind == TREE else name
        if parent in last and key <= last[parent]:
            raise Fault("BAD_TREE", path, "树条目重复或未按 git 顺序排列")
        last[parent], entries[path] = key, (mode, kind, oid)
    return entries


def changes(repo, base, head):
    """第 3 条：提交对提交的原始差异 [(路径, 状态)]，含删除与模式变化，关闭重命名检测。"""
    fields = git(repo, b"diff-tree", b"-r", b"-z", b"--no-renames", b"--raw", base, head)[1].split(b"\0")
    if fields[-1] != b"" or len(fields) % 2 != 1:
        raise Fault("GIT", b"diff-tree", "输出无法解读")
    result = []
    for meta, path in zip(fields[0:-1:2], fields[1::2]):
        m = RAW_META.fullmatch(meta)
        if not m or not path:
            raise Fault("GIT", b"diff-tree", "输出无法解读")
        result.append((path, m.group(1).decode()))
    return result


def within(path, rules):
    return any(path.startswith(r) if r.endswith(b"/") else path == r for r in rules)


def shape(tree, red):
    """第 6 条：被审提交整棵 formal_math/ 的形状，目录节点也在内。"""
    root = tree.get(FM_ROOT)
    if root and root[0] != b"040000":
        red("MODE", FM_ROOT, "formal_math 必须是目录，实为 %s" % root[0].decode())
    entries = [(path[len(FM):], mode, kind) for path, (mode, kind, _) in tree.items() if path.startswith(FM)]
    parents = {rel.rpartition(b"/")[0] for rel, _, _ in entries}
    seen = {}
    for rel, mode, kind in entries:
        path, parts = FM + rel, rel.split(b"/")
        if mode not in (b"100644", b"040000"):
            red("MODE", path, "只许 100644 普通文件与目录，实为 %s %s" % (mode.decode(), kind.decode()))
            continue
        if kind == TREE and rel not in parents:
            red("EMPTY_TREE", path, "提交里记录了空子树")
        if not all(SEGMENT.fullmatch(s) for s in parts):
            red("PATH_GRAMMAR", path, "路径段不合 ASCII 白名单文法")
            continue
        twin = seen.setdefault(rel.lower(), rel)
        if twin != rel:
            red("PATH_GRAMMAR", path, "与 %s 只差大小写" % twin.decode())
        if len(parts) == 1:
            if TOP.get(rel) != kind:
                red("TOP_LEVEL", path, "formal_math 顶层不许此名字或此类型")
        elif parts[0] in CONTENT_ROOTS:
            name = parts[-1]
            stem = name if kind == TREE else name[:-5] if name.endswith(b".lean") else b""
            if not MODULE.fullmatch(stem):
                red("CONTENT_SHAPE", path, "内容根下只许模块名文法的目录与 .lean 文件")


def check(repo, base, head, branch, approved, red):
    base, head = commit(repo, base), commit(repo, head)
    if git(repo, b"merge-base", b"--is-ancestor", base, head, ok=(0, 1))[0]:
        raise Fault("NOT_ANCESTOR", base, "基线不是被审提交的祖先")
    m = BRANCH.fullmatch(branch)
    role = m.group(1) if m else None
    diff, old, new = changes(repo, base, head), tree_at(repo, base), tree_at(repo, head)
    if all(old.get(p) == new.get(p) for p in GOVERNED):
        return head, role
    if role is None:
        red("BRANCH_ROLE", branch, "分支名解析不出角色，却改了 formal_math 或受信文件")
    else:
        for path, status in diff:
            if not within(path, ROLES[role]):
                red("PATH_SCOPE", path, "%s 角色不得改此路径（%s）" % (role.decode(), status))
        if role == b"infra" and not approved and any(within(p, TRUSTED_SURFACE) for p, _ in diff):
            red("TRUST_UNAPPROVED", branch, "改了受信文件，调用方未给放行开关")
    shape(new, red)
    for path in GOVERNED[1:]:
        if new.get(path) and new[path][0] != b"100644":
            red("MODE", path, "受信文件只许 100644，实为 %s" % new[path][0].decode())
    if role != b"infra":
        for path in TRUSTED:
            if old.get(path) != new.get(path):
                red("TRUSTED_DRIFT", path, "与基线不是同一对象（含模式）")
    return head, role


def emit(fd, kind, code, obj, msg):
    """按 UTF-8 字节直接写文件描述符，路径里的空白、反斜杠与非 ASCII 字节转义成 \\xNN；写不出时返回该错误。"""
    shown = b"".join(bytes([c]) if 0x21 <= c < 0x7F and c != 0x5C else b"\\x%02x" % c for c in obj) or b"-"
    data = b"PRECHECK %s %s %s %s\n" % (kind, code.encode(), shown, msg.encode("utf-8"))
    try:
        while data:
            data = data[os.write(fd, data):]
    except OSError as e:
        return e


def main(argv):
    args = [os.fsencode(a) for a in argv[1:]]
    approved, args = (True, args[1:]) if args[:1] == [FLAG] else (False, args)
    reds, fault, head, role = set(), None, b"", None
    try:
        if len(args) != 4 or any(not a or a.startswith(b"-") for a in args[:3]) or args[3].startswith(b"-"):
            raise Fault("USAGE", b"-", "用法：[%s] <仓库> <基线> <被审> <分支名>" % FLAG.decode())
        head, role = check(*args, approved, lambda code, obj, msg: reds.add((code, obj, msg)))
    except Fault as f:
        fault = f.args
    except Exception as e:  # 意外一律归入无法判定，不落成 1
        fault = ("INTERNAL", b"-", type(e).__name__)
    for code, obj, msg in sorted(reds):
        emit(1, b"RED", code, obj, msg)
    if fault is None and not reds:
        err = emit(1, b"GREEN", "OK", head, "role=" + (role.decode() if role else "-"))
        if err is None:
            return 0
        fault = ("OUTPUT", b"stdout", "绿行写不出：%s" % (err.strerror or type(err).__name__))
    if fault:
        emit(2, b"FAULT", *fault)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
