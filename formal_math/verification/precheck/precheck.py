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
OUTSIDE = tuple(p for p in TRUSTED_FILES if not p.startswith(FM))
ANCESTORS = {p[:i] for p in OUTSIDE for i in range(len(p)) if p[i:i + 1] == b"/"}
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
FILE_MODE, TREE_MODE = b"100644", b"40000"  # 树对象里实际记录的模式串，目录不带前导 0
CONTENT_ROOTS = (b"Chan", b"ChanTest", b"ChanChallenge", b"ChanDyn", b"ChanExplore")
TOP = dict.fromkeys(CONTENT_ROOTS + (b"verification", b"sources", b"blueprint"), TREE)
TOP.update(dict.fromkeys((b"Chan.lean", b"ChanExplore.lean", b"lakefile.toml", b"lake-manifest.json",
                          b"lean-toolchain", b"README.md", b"HISTORY.md", b"formalization.yaml",
                          b"statement-lock.json", b"garbage-signoffs.yaml"), BLOB))
LAKE_NAMES = {b"lakefile.toml", b"lakefile.lean", b"lake-manifest.json", b"lean-toolchain", b".lake"}
LAKE_ALLOWED = set(TRUSTED_FILES[:3]) | {GATE_DIR + b"/auditor/" + n for n in (
    b"lakefile.toml", b"lake-manifest.json", b"lean-toolchain")}
WORD = rb"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*"
BRANCH = re.compile(rb"(decl|proof|audit|infra)/" + WORD + rb"(?:/" + WORD + rb")*")
SEGMENT = re.compile(rb"[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*")
MODULE = re.compile(rb"[A-Za-z][A-Za-z0-9_]*")
OID = re.compile(rb"[0-9a-f]{40}|[0-9a-f]{64}")
ENTRY = re.compile(rb"([0-7]{1,6}) ([^\0/]+)\0")
ENV = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C", "GIT_NO_REPLACE_OBJECTS": "1",
       "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_GRAFT_FILE": os.devnull,
       "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}


class Fault(Exception):
    """运行故障或无法判定：args = (故障码, 对象, 说明)。"""


def git(repo, *args, ok=(0,), data=b""):
    """git 的标准错误原样透传；退出码不在 ok 内即运行故障。"""
    argv = [b"git", b"-C", repo, b"-c", b"advice.graftFileDeprecated=false", *args]
    try:
        p = subprocess.run(argv, env=ENV, input=data, stdout=subprocess.PIPE)
    except OSError as e:
        raise Fault("GIT", b"git", "%s: %s" % (type(e).__name__, e.strerror))
    if p.returncode not in ok:
        raise Fault("GIT", args[0], "git 退出 %d" % p.returncode)
    return p.returncode, p.stdout


def resolve(repo, rev, kind):
    rc, out = git(repo, b"rev-parse", b"--verify", b"--quiet", b"--end-of-options", rev + kind, ok=(0, 1))
    if rc or not OID.fullmatch(out.strip()):
        raise Fault("BAD_REV", rev, "解析不出提交")
    return out.strip()


def is_tree(mode):
    return int(mode, 8) & 0o170000 == 0o040000


def objects(repo, oids):
    """cat-file --batch 一次读一批对象的原始字节：{对象: (类型, 内容)}；头行、长度与结尾换行逐一核对。"""
    oids, found, pos = sorted(set(oids)), {}, 0
    data = git(repo, b"cat-file", b"--batch", data=b"".join(o + b"\n" for o in oids))[1]
    for oid in oids:
        nl = data.find(b"\n", pos)
        head = data[pos:nl].split(b" ") if nl >= 0 else []
        if len(head) != 3 or head[0] != oid or not head[2].isdigit():
            raise Fault("GIT", oid, "cat-file 输出无法解读或对象缺失")
        end = nl + 1 + int(head[2])
        if data[end:end + 1] != b"\n":
            raise Fault("GIT", oid, "cat-file 输出长度不符")
        found[oid], pos = (head[1], data[nl + 1:end]), end + 1
    if pos != len(data):
        raise Fault("GIT", b"cat-file", "cat-file 输出有多余字节")
    return found


def managed(path):
    return path == FM_ROOT or path.startswith(FM) or path in OUTSIDE or path in ANCESTORS


def inventory(repo, commit, red):
    """第 2 条：从提交的根树起逐层读原始树对象，得受管范围的清单 {路径: (原始模式, 对象)}，目录节点在内。
    读到的每一层都核对：能解析、条目名非空且不含 /、名字唯一、按 git 顺序严格递增、目录条目指向树对象。"""
    hash_len, found = len(commit) // 2, {}
    level = [(b"", resolve(repo, commit, b"^{tree}"))]
    while level:
        objs, nxt = objects(repo, [oid for _, oid in level]), []
        for path, oid in level:
            kind, body = objs[oid]
            if kind != TREE:
                red("TREE_FORM", path, "目录条目指向的不是树对象")
                continue
            names, last, pos = set(), b"", 0
            while pos < len(body):
                m = ENTRY.match(body, pos)
                if not m or m.end() + hash_len > len(body):
                    red("TREE_FORM", path, "树对象无法逐条解析（含空名或名字含 /）")
                    break
                mode, name = m.groups()
                child, pos = body[m.end():m.end() + hash_len].hex().encode(), m.end() + hash_len
                sub = path + b"/" + name if path else name
                key = name + b"/" if is_tree(mode) else name
                if name in names or key <= last:
                    red("TREE_FORM", sub, "同一目录里条目名重复或未按 git 顺序排列")
                names.add(name)
                last = max(last, key)
                if managed(sub) and sub not in found:
                    found[sub] = (mode, child)
                    if is_tree(mode):
                        nxt.append((sub, child))
        level = nxt
    return found


def within(path, rules):
    return any(path.startswith(r) if r.endswith(b"/") else path == r for r in rules)


def allowed(path, before, after, rules):
    """第 4 条：两侧都只是目录节点（或不存在）时，按目录判：落在表项之内，或是某个表项的祖先目录。"""
    if all(v is None or is_tree(v[0]) for v in (before, after)):
        return within(path + b"/", rules) or any(r.startswith(path + b"/") for r in rules)
    return within(path, rules)


def shape(tree, red):
    """第 6 条：被审提交受管清单的形状，目录节点也在内。"""
    files = [p for p, (mode, _) in tree.items() if not is_tree(mode)]
    dirs = {p for p, (mode, _) in tree.items() if is_tree(mode) and (p == FM_ROOT or p.startswith(FM))}
    for path in sorted(dirs - {f[:i] for f in files for i in range(len(f)) if f[i:i + 1] == b"/"}):
        red("EMPTY_TREE", path, "目录节点下没有任何文件")
    seen = {}
    for path, (mode, _) in tree.items():
        want = TREE_MODE if path in ANCESTORS or path == FM_ROOT else FILE_MODE if path in OUTSIDE else None
        if mode != want and (want or mode not in (FILE_MODE, TREE_MODE)):
            red("MODE", path, "原始模式为 %s，只许 100644 文件与 40000 目录" % mode.decode())
            continue
        if not path.startswith(FM):
            continue
        rel = path[len(FM):]
        parts, kind = rel.split(b"/"), TREE if mode == TREE_MODE else BLOB
        if parts[-1].lower() in LAKE_NAMES and path not in LAKE_ALLOWED:
            red("LAKE_FILE", path, "formal_math 下此位置不许出现 Lake 配置名")
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
    base, head = resolve(repo, base, b"^{commit}"), resolve(repo, head, b"^{commit}")
    if git(repo, b"merge-base", b"--is-ancestor", base, head, ok=(0, 1))[0]:
        raise Fault("NOT_ANCESTOR", base, "基线不是被审提交的祖先")
    m = BRANCH.fullmatch(branch)
    role = m.group(1) if m else None
    base_form = []
    old = inventory(repo, base, lambda *r: base_form.append(r))
    if base_form:
        raise Fault("BASE_FORM", base_form[0][1], "基线树不规范：" + base_form[0][2])
    new = inventory(repo, head, red)
    # 第 3 条：改动集合是两份清单的集合差；仓库根下受信文件的祖先目录只核对形状，不算改动。
    changed = sorted(p for p in set(old) | set(new) if p not in ANCESTORS and old.get(p) != new.get(p))
    if not changed:
        return head, role
    if role is None:
        red("BRANCH_ROLE", branch, "分支名解析不出角色，却改了 formal_math 或受信文件")
    else:
        for path in changed:
            if not allowed(path, old.get(path), new.get(path), ROLES[role]):
                status = "A" if path not in old else "D" if path not in new else "M"
                red("PATH_SCOPE", path, "%s 角色不得改此路径（%s）" % (role.decode(), status))
        if role == b"infra" and not approved and any(p == GATE_DIR or within(p, TRUSTED_SURFACE) for p in changed):
            red("TRUST_UNAPPROVED", branch, "改了受信文件，调用方未给放行开关")
    shape(new, red)
    if role != b"infra":
        for path in TRUSTED:
            if old.get(path) != new.get(path):
                red("TRUSTED_DRIFT", path, "与基线不是同一对象（含原始模式）")
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
