#!/usr/bin/env python3
"""precheck.py 的自测：在临时目录（跟随 TMPDIR）现造 git 仓库，逐例断言退出码与规则码集合。

用法：selftest.py            跑全部用例，全过退 0，否则退 1
      selftest.py --mutants  先断言未改弱的副本全过，再断言 MUTANTS 里每种弱化各自被至少一例抓住
输出一律按 UTF-8 字节写文件描述符，不经 print。
"""
import functools
import hashlib
import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PRECHECK = os.path.join(HERE, "precheck.py")
LINE = re.compile(rb"^PRECHECK (\S+) (\S+) ", re.M)
FM = "formal_math/"
GENV = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_AUTHOR_DATE": "@0 +0000",
        "GIT_COMMITTER_DATE": "@0 +0000"}
# 子进程用可编码的环境跑；ASCII 用例另设。
RUN_ENV = {"PATH": GENV["PATH"], "LC_ALL": "C.UTF-8"}


def out(text):
    data = text.encode("utf-8")
    while data:
        data = data[os.write(1, data):]


def git(repo, *args, data=None):
    p = subprocess.run(["git", "-C", repo, *args], input=data, env=GENV, capture_output=True, check=True)
    return p.stdout


class Repo:
    """用底层命令造树与提交，能造出空子树、子模块、符号链接、怪名字。"""

    def __init__(self, path):
        self.path = path
        os.makedirs(path)
        git(path, "init", "-q")

    def blob(self, data):
        return git(self.path, "hash-object", "-w", "--stdin", data=data).strip()

    def entry(self, value):
        """(原始模式, 类型, 对象)。dict 是子树；list 是按给定顺序原样写的子树（可重复、乱序、名字含 /）；
        (模式, 内容) 按给定的原始模式写，内容是 dict/list 时为子树，模式 160000 时内容是提交对象名。"""
        if isinstance(value, Body):
            return b"40000", b"tree", git(self.path, "hash-object", "-t", "tree", "-w", "--literally", "--stdin",
                                          data=bytes(value)).strip()
        if isinstance(value, tuple):
            mode, inner = value
            if mode == b"160000":
                return mode, b"commit", inner
            return (mode,) + (self.entry(inner)[1:] if isinstance(inner, (dict, list)) else (b"blob", self.blob(inner)))
        if isinstance(value, dict):
            return b"40000", b"tree", self.raw([(n, value[n]) for n in sorted(value, key=lambda n: gitkey(n, value[n]))])
        if isinstance(value, list):
            return b"40000", b"tree", self.raw(value)
        return b"100644", b"blob", self.blob(value)

    def raw(self, items):
        """直接写树对象的原始字节，不经 mktree 的整理。"""
        body = b"".join(b"%s %s\0%s" % (e[0], n, bytes.fromhex(e[2].decode()))
                        for e, n in ((self.entry(v), n) for n, v in items))
        return git(self.path, "hash-object", "-t", "tree", "-w", "--literally", "--stdin", data=body).strip()

    def commit(self, files, parent=None):
        """files: {路径: 值}；键 b"" 给出根树的原始条目表，值为 KEEP 的条目取自其余路径拼出的子树。"""
        spec, root = {}, files.get(b"")
        for path, value in files.items():
            if path:
                node, parts = spec, path.split(b"/")
                for part in parts[:-1]:
                    node = node.setdefault(part, {})
                node[parts[-1]] = value
        tree = self.raw([(n, keep(v, spec.get(n))) for n, v in root]) if root else self.entry(spec)[2]
        args = ["commit-tree", tree.decode(), "-m", "c"] + (["-p", parent] if parent else [])
        return git(self.path, *args).strip().decode()


KEEP = object()


class Body(bytes):
    """树对象的原始字节，原样写入，用来造截断、空名、错位模式等无法逐条构造的树。"""


def keep(value, original):
    """KEEP 取原值；(模式, KEEP) 取原值并换成给定的原始模式。"""
    if value is KEEP:
        return original
    return (value[0], original) if isinstance(value, tuple) and value[1] is KEEP else value


def gitkey(name, value):
    tree = isinstance(value, (dict, list)) or isinstance(value, tuple) and isinstance(value[1], (dict, list))
    return name + b"/" if tree else name


def b(s):
    return s.encode("utf-8") if isinstance(s, str) else s


BASE = {b(k): b(v) for k, v in {
    FM + "lakefile.toml": "name = \"Chan\"\n", FM + "lake-manifest.json": "{}\n", FM + "lean-toolchain": "v4\n",
    FM + "README.md": "r\n", FM + "HISTORY.md": "h\n", FM + "statement-lock.json": "{}\n",
    FM + "formalization.yaml": "{}\n", FM + "Chan.lean": "module\n", FM + "Chan/Defs/A.lean": "module\n",
    FM + "Chan/Thm/B.lean": "module\n", FM + "Chan/Audit/Math/C.lean": "module\n",
    FM + "ChanTest/T.lean": "module\n", FM + "ChanExplore/E.lean": "module\n",
    FM + "verification/run_gates.py": "x\n", FM + "verification/garbage-signoffs.yaml": "{}\n",
    FM + "verification/must_red/x/Bad.lean": "module\n", FM + "sources/s.md": "s\n",
    "scripts/fm_env.sh": "e\n", ".github/workflows/formal-math.yml": "w\n", ".github/workflows/ci.yml": "c\n",
    "rust/lib.rs": "r\n", "README.md": "r\n"}.items()}
X = b"changed\n"
EXEC, LINK, EMPTY = (b"100755", b"module\n"), (b"120000", b"B.lean"), {}
F = FM.encode()
GITLINK = (b"160000", b"1" * 40)

MOD = b"module\n"
TRUSTED_LIST = [F + b"lakefile.toml", F + b"lake-manifest.json", F + b"lean-toolchain", b"scripts/fm_env.sh",
                b".github/workflows/formal-math.yml"]


def as_raw(prefix, override):
    """把 BASE 里 prefix 目录改成按 git 顺序原样写的树，override 覆盖或追加其直接子条目（值为 None 删除）。"""
    sub = {}
    for k, v in BASE.items():
        if k.startswith(prefix + b"/"):
            node, parts = sub, k[len(prefix) + 1:].split(b"/")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = v
    sub.update({n: keep(v, sub.get(n)) for n, v in override.items()})
    items = sorted(((n, v) for n, v in sub.items() if v is not None), key=lambda e: gitkey(*e))
    return {**{k: None for k in BASE if k.startswith(prefix + b"/")}, prefix: items}


def root_raw(insert, before=True):
    """根树原样写：在 formal_math 条目前（或后）插一条同名条目。"""
    names = sorted({k.split(b"/")[0] for k in BASE}, key=lambda n: n + b"/" if n != b"README.md" else n)
    items = []
    for n in names:
        if n == F[:-1] and before:
            items.append((n, insert))
        items.append((n, KEEP))
        if n == F[:-1] and not before:
            items.append((n, insert))
    return items


# 一个 blob，内容恰好是合法的树对象字节（含一条指向 MOD 的 A.lean），用来区分「按类型读」与「按内容猜」。
TREE_LIKE_BLOB = b"100644 A.lean\0" + hashlib.sha1(b"blob %d\0" % len(MOD) + MOD).digest()
def root_edit(name, value):
    """根树原样写，只把 name 那一条换成 value。"""
    return {b"": [(n, value if n == name else KEEP) for n, v in root_raw(None) if v is KEEP]}


NO_FM_ENV = {b"scripts/fm_env.sh": None, b"scripts/other.sh": b"o\n"}
WF_040755 = as_raw(b".github", {b"workflows": (b"040755", KEEP)})
NO_FM = {k: None for k in BASE if k.startswith(F)}
SUB_DUP = [(b"B.lean", MOD), (b"Sub", None), (b"Sub.lean", MOD), (b"Sub", {b"E.lean": MOD})]


def b1a(value):
    return {F + b"Chan/Thm/B.lean": None, F + b"Chan/Thm": [(n, value if v is None else v) for n, v in SUB_DUP]}


# (名字, 改动, 分支, 放行, 期望退出码, 期望规则码[, 基线相对 BASE 的改动])。改动里 None 表示删除。
CASES = [
    ("对照：无改动", {}, "proof/x", False, 0, set()),
    ("对照：无改动，无角色分支名", {}, "main", False, 0, set()),
    # 规则 2：分支名文法
    ("proof 改 Thm", {F + b"Chan/Thm/B.lean": X}, "proof/x", False, 0, set()),
    ("proof 多级后缀", {F + b"Chan/Thm/B.lean": X}, "proof/2312-a.b/c_d", False, 0, set()),
] + [("分支名畸形 %r" % n, {F + b"Chan/Thm/B.lean": X}, n, False, 1, {"BRANCH_ROLE"}) for n in (
    "proof/", "proof", "proof/a..b", "proof/x/", "proof//x", "proofs/x", "Proof/x", "proof/x ", "proof/ x",
    "proof/x\n", "proof/.x", "proof/x.", "proof/é", "refs/heads/proof/x", "x/proof/y", "feature/x", "")] + [
    # 规则 3、4：改动集合与路径权限
    ("audit 改 Audit/Math", {F + b"Chan/Audit/Math/C.lean": X}, "audit/x", False, 0, set()),
    ("audit 改 ChanTest", {F + b"ChanTest/T.lean": X}, "audit/x", False, 0, set()),
    ("decl 改 Defs", {F + b"Chan/Defs/A.lean": X}, "decl/x", False, 0, set()),
    ("decl 改 proof 的路径", {F + b"Chan/Thm/B.lean": X}, "decl/x", False, 1, {"PATH_SCOPE"}),
    ("proof 改 decl 的路径", {F + b"Chan/Defs/A.lean": X}, "proof/x", False, 1, {"PATH_SCOPE"}),
    ("proof 删自己路径", {F + b"Chan/Thm/B.lean": None}, "proof/x", False, 0, set()),
    ("decl 删 proof 路径", {F + b"Chan/Thm/B.lean": None}, "decl/x", False, 1, {"PATH_SCOPE"}),
    ("proof 新建自己的根目录", {F + b"ChanDyn/D.lean": X}, "proof/x", False, 0, set()),
    ("R1-B5 proof 只改受管外路径", {b"rust/lib.rs": X}, "proof/x", False, 0, set()),
    ("proof 同时带受管外的改动", {F + b"Chan/Thm/B.lean": X, b"rust/lib.rs": X}, "proof/x", False, 0, set()),
    ("无角色分支改 Thm", {F + b"Chan/Thm/B.lean": X}, "feature/x", False, 1, {"BRANCH_ROLE"}),
    ("无角色分支改 fm_env.sh", {b"scripts/fm_env.sh": X}, "main", False, 1, {"BRANCH_ROLE", "TRUSTED_DRIFT"}),
    ("不碰受管路径", {b"rust/lib.rs": X, b"README.md": None}, "whatever name", False, 0, set()),
    ("不碰受管路径：ci.yml", {b".github/workflows/ci.yml": X}, "main", False, 0, set()),
    ("不碰受管路径：同名前缀兄弟", {b"scripts/fm_env.sh.bak": X, b"formal_math2/x": X}, "main", False, 0, set()),
    ("只改模式 proof", {F + b"Chan/Thm/B.lean": (b"100755", MOD)}, "proof/x", False, 1, {"MODE"}),
    ("只改模式 decl 改 proof 路径", {F + b"Chan/Thm/B.lean": (b"100755", MOD)}, "decl/x", False, 1,
     {"MODE", "PATH_SCOPE"}),
    ("只改模式 fm_env.sh infra 放行", {b"scripts/fm_env.sh": (b"100755", b"e\n")}, "infra/x", True, 1, {"MODE"}),
    ("只改模式 fm_env.sh proof", {b"scripts/fm_env.sh": (b"100755", b"e\n")}, "proof/x", False, 1,
     {"MODE", "PATH_SCOPE", "TRUSTED_DRIFT"}),
    ("同名前缀兄弟 Chan/Thm2", {F + b"Chan/Thm2/X.lean": X}, "proof/x", False, 1, {"PATH_SCOPE"}),
    ("同名前缀兄弟 ChanTestX", {F + b"ChanTestX/Y.lean": X}, "audit/x", False, 1, {"PATH_SCOPE", "TOP_LEVEL"}),
    ("同名前缀兄弟 verification-x proof", {F + b"verification-x/a.py": X}, "proof/x", False, 1,
     {"PATH_SCOPE", "TOP_LEVEL"}),
    ("同名前缀兄弟 verification-x infra", {F + b"verification-x/a.py": X}, "infra/x", True, 1,
     {"PATH_SCOPE", "TOP_LEVEL"}),
    ("受管外的同名前缀兄弟 fm_env.sh.bak 随 infra 改动", {b"scripts/fm_env.sh.bak": X, F + b"lakefile.toml": X},
     "infra/x", True, 0, set()),
    # 规则 5：受信与内容互斥、放行开关
    ("infra 改 lakefile 无放行", {F + b"lakefile.toml": X}, "infra/x", False, 1, {"TRUST_UNAPPROVED"}),
    ("infra 改 lakefile 有放行", {F + b"lakefile.toml": X}, "infra/x", True, 0, set()),
    ("infra 改门禁有放行", {F + b"verification/run_gates.py": X}, "infra/x", True, 0, set()),
    ("infra 改门禁无放行", {F + b"verification/run_gates.py": X}, "infra/x", False, 1, {"TRUST_UNAPPROVED"}),
    ("infra 改工作流有放行", {b".github/workflows/formal-math.yml": X}, "infra/x", True, 0, set()),
    ("infra 改工作流无放行", {b".github/workflows/formal-math.yml": X}, "infra/x", False, 1, {"TRUST_UNAPPROVED"}),
    ("infra 只改 README 无放行", {F + b"README.md": X}, "infra/x", False, 0, set()),
    ("infra 删受信文件有放行", {F + b"lean-toolchain": None}, "infra/x", True, 0, set()),
    ("infra 删受信文件无放行", {F + b"lean-toolchain": None}, "infra/x", False, 1, {"TRUST_UNAPPROVED"}),
    ("infra 带内容文件", {F + b"lakefile.toml": X, F + b"Chan/Thm/X.lean": X}, "infra/x", True, 1,
     {"PATH_SCOPE"}),
    ("R5-B1 有放行", {F + b"lakefile.toml": X, F + b"ChanExplore/FakeAudit.lean": X}, "infra/hijack", True, 1,
     {"PATH_SCOPE"}),
    ("R5-B1 无放行", {F + b"lakefile.toml": X, F + b"ChanExplore/FakeAudit.lean": X}, "infra/hijack", False, 1,
     {"PATH_SCOPE", "TRUST_UNAPPROVED"}),
    ("proof 改 ChanExplore", {F + b"ChanExplore/E.lean": X}, "proof/x", False, 0, set()),
    # 规则 6：整树形状
    ("R5-B2 proof", {F + b"lakefile.lean": X}, "proof/x", False, 1, {"PATH_SCOPE", "TOP_LEVEL", "LAKE_FILE"}),
    ("R5-B2 infra 放行", {F + b"lakefile.lean": X}, "infra/x", True, 1, {"PATH_SCOPE", "TOP_LEVEL", "LAKE_FILE"}),
    ("R5-B3 decl 改 manifest", {F + b"lake-manifest.json": X}, "decl/x", False, 1, {"PATH_SCOPE", "TRUSTED_DRIFT"}),
    ("R5-B3 隐藏目录下的 Lean 配置", {F + b".cfg/cli_lakefile.lean": X}, "proof/x", False, 1,
     {"PATH_SCOPE", "PATH_GRAMMAR"}),
    ("内容根下隐藏目录", {F + b"Chan/Thm/.cfg/x.lean": X}, "proof/x", False, 1, {"PATH_GRAMMAR"}),
    ("内容根下 .gitattributes", {F + b"Chan/Thm/.gitattributes": X}, "proof/x", False, 1, {"PATH_GRAMMAR"}),
    ("内容根下非模块名", {F + b"Chan/Thm/foo-bar.lean": X}, "proof/x", False, 1, {"CONTENT_SHAPE"}),
    ("内容根下 .lean 目录", {F + b"Chan/Thm/D.lean/E.lean": X}, "proof/x", False, 1, {"CONTENT_SHAPE"}),
    ("内容根下新目录", {F + b"Chan/Thm/Sub/E.lean": X}, "proof/x", False, 0, set()),
    ("名字以点结尾", {F + b"sources/foo.": X}, "decl/x", False, 1, {"PATH_GRAMMAR"}),
    ("名字含连续分隔符", {F + b"sources/a..b": X}, "decl/x", False, 1, {"PATH_GRAMMAR"}),
    ("R5-B6 提交里的符号链接（暂存区与工作树是普通文件）", {F + b"Chan/Thm/link.lean": LINK}, "proof/x", False, 1,
     {"MODE"}),
    ("符号链接在门禁目录", {F + b"verification/l": LINK}, "infra/x", True, 1, {"MODE"}),
    ("formal_math 本身是符号链接", {**NO_FM, F[:-1]: LINK}, "proof/x", False, 1,
     {"MODE", "PATH_SCOPE", "TRUSTED_DRIFT"}),
    ("formal_math 本身是普通文件", {**NO_FM, F[:-1]: X}, "proof/x", False, 1, {"MODE", "PATH_SCOPE", "TRUSTED_DRIFT"}),
    ("子模块", {F + b"Chan/Thm/Sub": GITLINK}, "proof/x", False, 1, {"MODE"}),
    ("空子树", {F + b"Chan/Thm/Empty": EMPTY}, "proof/x", False, 1, {"EMPTY_TREE"}),
    ("空子树，无角色", {F + b"Chan/Thm/Empty": EMPTY}, "main", False, 1, {"EMPTY_TREE", "BRANCH_ROLE"}),
    ("只含空子树的目录", {F + b"Chan/Thm/Outer/Inner": EMPTY}, "proof/x", False, 1, {"EMPTY_TREE"}),
    ("非 ASCII 路径", {F + "Chan/Thm/Ä.lean".encode(): X}, "proof/x", False, 1, {"PATH_GRAMMAR"}),
    ("含空格路径", {F + b"Chan/Thm/A B.lean": X}, "proof/x", False, 1, {"PATH_GRAMMAR"}),
    ("含换行路径", {F + b"Chan/Thm/A\nB.lean": X}, "proof/x", False, 1, {"PATH_GRAMMAR"}),
    ("只差大小写", {F + b"Chan/Thm/b.lean": X}, "proof/x", False, 1, {"PATH_GRAMMAR"}),
    ("受管外的换行路径", {b"docs/a\nb": X}, "main", False, 0, set()),
    ("顶层未知文件", {F + b"notes.txt": X}, "decl/x", False, 1, {"PATH_SCOPE", "TOP_LEVEL"}),
    ("顶层名字类型不符", {F + b"HISTORY.md": None, F + b"HISTORY.md/x": X}, "decl/x", False, 1,
     {"PATH_SCOPE", "TOP_LEVEL"}),
    ("decl 改 sources", {F + b"sources/new.md": X}, "decl/x", False, 0, set()),
    ("工作流文件改成可执行", {b".github/workflows/formal-math.yml": (b"100755", b"w\n")}, "infra/x", True, 1, {"MODE"}),
    ("工作流文件改成符号链接", {b".github/workflows/formal-math.yml": LINK}, "infra/x", True, 1, {"MODE"}),
    ("工作流文件改成目录", {b".github/workflows/formal-math.yml": {b"x": X}}, "infra/x", True, 1, {"MODE"}),
    ("受信文件的祖先目录改成符号链接", {b"scripts/fm_env.sh": None, b"scripts": LINK}, "infra/x", True, 1,
     {"MODE", "PATH_SCOPE"}),
    # 第 2 条：清单规范性（逐层读原始树对象）
    ("树条目重复", {F + b"Chan/Thm/B.lean": None, F + b"Chan/Thm": [(b"B.lean", X), (b"B.lean", MOD)]},
     "proof/x", False, 1, {"TREE_FORM"}),
    ("树条目乱序", {F + b"Chan/Thm/B.lean": None, F + b"Chan/Thm": [(b"Z.lean", X), (b"B.lean", MOD)]},
     "proof/x", False, 1, {"TREE_FORM"}),
    ("树条目名含斜杠", as_raw(F + b"Chan/Thm", {b"X/Y.lean": MOD}), "proof/x", False, 1, {"TREE_FORM"}),
    ("根树里有名字含斜杠的条目", {b"": [e for e in root_raw(LINK) if e[1] is KEEP] + [(b"zz/x", X)]}, "main", False, 1,
     {"TREE_FORM"}),
    ("目录条目指向非树对象", as_raw(F + b"Chan/Thm", {b"Sub": (b"40000", MOD)}), "proof/x", False, 1,
     {"TREE_FORM", "EMPTY_TREE"}),
    ("目录条目指向内容恰似树的 blob", as_raw(F + b"Chan/Thm", {b"Sub": (b"40000", TREE_LIKE_BLOB)}), "proof/x",
     False, 1, {"TREE_FORM", "EMPTY_TREE"}),
    ("非规范文件模式 100664", as_raw(F + b"Chan/Thm", {b"B.lean": (b"100664", MOD)}), "proof/x", False, 1, {"MODE"}),
    ("非规范目录模式 040000", as_raw(F + b"Chan", {b"Thm": (b"040000", {b"B.lean": MOD})}), "proof/x", False, 1,
     {"MODE"}),
    ("基线树不规范", {}, "proof/x", False, 2, {"BASE_FORM"},
     {F + b"Chan/Thm/B.lean": None, F + b"Chan/Thm": [(b"B.lean", X), (b"B.lean", MOD)]}),
    # 审阅 R1 的阻断复现形状
    ("R1-B1a 符号链接与同名目录", b1a(LINK), "proof/x", False, 1, {"TREE_FORM", "MODE"}),
    ("R1-B1a 可执行文件与同名目录", b1a((b"100755", MOD)), "proof/x", False, 1, {"TREE_FORM", "MODE"}),
    ("R1-B1a 子模块与同名目录", b1a(GITLINK), "proof/x", False, 1, {"TREE_FORM", "MODE"}),
    ("R1-B1a 非 .lean 文件与同名目录", b1a(LINK[1]), "proof/x", False, 1, {"TREE_FORM", "CONTENT_SHAPE"}),
    ("R1-B1a 门禁目录里的符号链接与同名目录", {F + b"verification/sub": [(b"Sub", LINK), (b"Sub", {b"E.py": X})]},
     "infra/x", True, 1, {"TREE_FORM", "MODE"}),
    ("R1-B1b 根上符号链接与原样 formal_math 并存 main", {b"": root_raw(LINK), b"rust/lib.rs": X}, "main", False, 1,
     {"TREE_FORM", "BRANCH_ROLE", "MODE", "TRUSTED_DRIFT"}),
    ("R1-B1b 根上符号链接与原样 formal_math 并存 proof", {b"": root_raw(LINK), b"rust/lib.rs": X}, "proof/x",
     False, 1, {"TREE_FORM", "PATH_SCOPE", "MODE", "TRUSTED_DRIFT"}),
    ("R1-B1b 反序：原样 formal_math 在前", {b"": root_raw(LINK, before=False)}, "main", False, 1, {"TREE_FORM"}),
    ("R1-B2a 新增空的 formal_math proof", {**NO_FM, F[:-1]: EMPTY}, "proof/x", False, 1, {"EMPTY_TREE"}, NO_FM),
    ("R1-B2a 新增空的 formal_math infra 无放行", {**NO_FM, F[:-1]: EMPTY}, "infra/x", False, 1, {"EMPTY_TREE"}, NO_FM),
    ("R1-B2b 删光文件留下空的 formal_math", {**NO_FM, F[:-1]: EMPTY}, "infra/x", False, 1, {"EMPTY_TREE"},
     {**NO_FM, F + b"README.md": b"r\n"}),
    ("R1-B3a infra 无放行删门禁目录里的空子树", {}, "infra/x", False, 1, {"TRUST_UNAPPROVED"},
     {F + b"verification/Empty": EMPTY}),
    ("R1-B3a proof 删门禁目录里的空子树", {}, "proof/x", False, 1, {"PATH_SCOPE", "TRUSTED_DRIFT"},
     {F + b"verification/Empty": EMPTY}),
    ("R1-B3b proof 删 decl 目录里的空子树", {}, "proof/x", False, 1, {"PATH_SCOPE"}, {F + b"Chan/Defs/Empty": EMPTY}),
    ("R1-B3c infra 无放行把门禁文件改成 100664",
     as_raw(F + b"verification", {b"run_gates.py": (b"100664", b"x\n")}), "infra/x", False, 1,
     {"TRUST_UNAPPROVED", "MODE"}),
    ("R1-B4 内容根内 lakefile.lean", {F + b"Chan/Thm/lakefile.lean": X}, "proof/x", False, 1, {"LAKE_FILE"}),
    ("R1-B4 sources 下 lakefile.lean", {F + b"sources/lakefile.lean": X}, "decl/x", False, 1, {"LAKE_FILE"}),
    ("R1-B4 blueprint 深层 lakefile.lean", {F + b"blueprint/sub/lakefile.lean": X}, "decl/x", False, 1,
     {"LAKE_FILE"}),
    ("R1-B4 门禁目录内 lakefile.lean", {F + b"verification/lakefile.lean": X}, "infra/x", True, 1, {"LAKE_FILE"}),
    ("Lake 配置名：大小写变体", {F + b"Chan/Thm/Lakefile.lean": X}, "proof/x", False, 1, {"LAKE_FILE"}),
    ("Lake 配置名：内容根下 lakefile.toml", {F + b"Chan/Thm/lakefile.toml": X}, "proof/x", False, 1,
     {"CONTENT_SHAPE", "LAKE_FILE"}),
    ("Lake 配置名：sources 下 manifest 与 toolchain", {F + b"sources/lake-manifest.json": X,
                                                     F + b"sources/lean-toolchain": X}, "decl/x", False, 1,
     {"LAKE_FILE"}),
    ("Lake 配置名：.lake 目录", {F + b"blueprint/.lake/x": X}, "decl/x", False, 1, {"LAKE_FILE", "PATH_GRAMMAR"}),
    ("Lake 配置名：门禁夹具里的 lakefile.toml", {F + b"verification/must_red/y/lakefile.toml": X}, "infra/x", True,
     1, {"LAKE_FILE"}),
    ("Lake 配置名：审计程序包的三个配置", {F + b"verification/auditor/lakefile.toml": X,
                                      F + b"verification/auditor/lake-manifest.json": X,
                                      F + b"verification/auditor/lean-toolchain": X}, "infra/x", True, 0, set()),
    ("Lake 配置名：审计程序包里的 lakefile.lean", {F + b"verification/auditor/lakefile.lean": X}, "infra/x", True,
     1, {"LAKE_FILE"}),
    ("Lake 配置名：审计程序包更深一层", {F + b"verification/auditor/sub/lakefile.toml": X}, "infra/x", True, 1,
     {"LAKE_FILE"}),
    # 为清理现存 formal_math/.gitignore 留的口子：infra 获放行可删，谁都不能新增或保留
    ("清理 .gitignore：infra 有放行删除", {}, "infra/x", True, 0, set(), {F + b".gitignore": X}),
    ("清理 .gitignore：infra 无放行删除", {}, "infra/x", False, 1, {"TRUST_UNAPPROVED"}, {F + b".gitignore": X}),
    ("清理 .gitignore：proof 删除", {}, "proof/x", False, 1, {"PATH_SCOPE", "TRUSTED_DRIFT"},
     {F + b".gitignore": X}),
    ("清理 .gitignore：proof 改别处而保留它", {F + b".gitignore": X, F + b"Chan/Thm/B.lean": X}, "proof/x", False, 1,
     {"PATH_GRAMMAR"}, {F + b".gitignore": X}),
    ("清理 .gitignore：infra 有放行改它而保留", {F + b".gitignore": b"y\n"}, "infra/x", True, 1, {"PATH_GRAMMAR"},
     {F + b".gitignore": X}),
    ("清理 .gitignore：infra 有放行新增", {F + b".gitignore": X}, "infra/x", True, 1, {"PATH_GRAMMAR"}),
    ("清理 .gitignore：decl 新增", {F + b".gitignore": X}, "decl/x", False, 1,
     {"PATH_SCOPE", "PATH_GRAMMAR", "TRUSTED_DRIFT"}),
    # 审阅 R2：受信文件的祖先目录是清单正式条目，比模式与类型，不比对象名；形状检查无条件执行
    ("R2 只改 ci.yml proof", {b".github/workflows/ci.yml": X}, "proof/x", False, 0, set()),
    ("R2 只改 ci.yml infra 无放行", {b".github/workflows/ci.yml": X}, "infra/x", False, 0, set()),
    ("R2-B1a scripts 目录模式改成 040000 main", root_edit(b"scripts", (b"040000", KEEP)), "main", False, 1,
     {"MODE", "BRANCH_ROLE"}),
    ("R2-B1a scripts 目录模式改成 40755 proof", root_edit(b"scripts", (b"40755", KEEP)), "proof/x", False, 1,
     {"MODE", "PATH_SCOPE"}),
    ("R2-B1a .github/workflows 目录模式改成 040755 proof", WF_040755, "proof/x", False, 1, {"MODE", "PATH_SCOPE"}),
    ("R2-B1a .github/workflows 目录模式改成 040755 infra 放行", WF_040755, "infra/x", True, 1, {"MODE"}),
    ("R2 基线里的祖先目录已不规范且未改", WF_040755, "main", False, 1, {"MODE"}, WF_040755),
    ("R2-B1b 受信文件不存在时 scripts 换成符号链接 main", {**NO_FM_ENV, b"scripts/other.sh": None, b"scripts": LINK},
     "main", False, 1, {"MODE", "BRANCH_ROLE"}, NO_FM_ENV),
    ("R2-B1b 受信文件不存在时 scripts 换成符号链接 proof", {**NO_FM_ENV, b"scripts/other.sh": None, b"scripts": LINK},
     "proof/x", False, 1, {"MODE", "PATH_SCOPE"}, NO_FM_ENV),
    ("R2-B1b 受信文件不存在时 scripts 换成普通文件", {**NO_FM_ENV, b"scripts/other.sh": None, b"scripts": X},
     "proof/x", False, 1, {"MODE", "PATH_SCOPE"}, NO_FM_ENV),
    ("R2-B1b 受信文件不存在时 scripts 换成子模块", {**NO_FM_ENV, b"scripts/other.sh": None, b"scripts": GITLINK},
     "proof/x", False, 1, {"MODE", "PATH_SCOPE"}, NO_FM_ENV),
    ("R2 受信文件存在时 scripts 换成符号链接 proof", {b"scripts/fm_env.sh": None, b"scripts": LINK}, "proof/x", False,
     1, {"MODE", "PATH_SCOPE", "TRUSTED_DRIFT"}),
    ("R2 受信文件存在时 .github 换成普通文件 main", {b".github/workflows/formal-math.yml": None,
                                                b".github/workflows/ci.yml": None, b".github": X}, "main", False, 1,
     {"MODE", "BRANCH_ROLE", "TRUSTED_DRIFT"}),
    ("R2-M10 门禁目录节点自身模式改成 040000 infra 无放行", as_raw(F[:-1], {b"verification": (b"040000", KEEP)}),
     "infra/x", False, 1, {"MODE", "TRUST_UNAPPROVED"}),
    ("R2-M2 树对象里对象名截断", {F + b"Chan/Thm/B.lean": None, F + b"Chan/Thm": Body(b"100644 B.lean\0" + b"\x11" * 19)},
     "proof/x", False, 1, {"TREE_FORM", "EMPTY_TREE"}),
    ("树对象里条目名为空", {F + b"Chan/Thm/B.lean": None, F + b"Chan/Thm": Body(b"100644 \0" + b"\x11" * 20)},
     "proof/x", False, 1, {"TREE_FORM", "EMPTY_TREE"}),
    ("树对象里模式七位", {F + b"Chan/Thm/B.lean": None, F + b"Chan/Thm": Body(b"1006440 B.lean\0" + b"\x11" * 20)},
     "proof/x", False, 1, {"TREE_FORM", "EMPTY_TREE"}),
    ("树对象里模式非八进制", {F + b"Chan/Thm/B.lean": None, F + b"Chan/Thm": Body(b"100684 B.lean\0" + b"\x11" * 20)},
     "proof/x", False, 1, {"TREE_FORM", "EMPTY_TREE"}),
    ("文件条目指向树对象（内容根）", as_raw(F + b"Chan/Thm", {b"X.lean": (b"100644", {b"a.lean": MOD})}), "proof/x",
     False, 1, {"TREE_FORM"}),
    ("文件条目指向树对象（sources）", as_raw(F + b"sources", {b"evil.md": (b"100644", {b"a": X})}), "decl/x", False, 1,
     {"TREE_FORM"}),
    ("Lake 配置名：例外路径是目录", {F + b"verification/auditor/lakefile.toml/x": X}, "infra/x", True, 1,
     {"LAKE_FILE"}),
    # 规则 7：内容角色下受信面逐个比对
] + [("内容角色改受信文件 %s" % p.decode(), {p: X}, "proof/x", False, 1, {"PATH_SCOPE", "TRUSTED_DRIFT"})
     for p in TRUSTED_LIST] + [
    ("内容角色带放行开关改 lakefile.toml", {F + b"lakefile.toml": X}, "proof/x", True, 1,
     {"PATH_SCOPE", "TRUSTED_DRIFT"}),
    ("内容角色带放行开关改 lean-toolchain", {F + b"lean-toolchain": X}, "decl/x", True, 1,
     {"PATH_SCOPE", "TRUSTED_DRIFT"}),
    ("proof 改门禁文件", {F + b"verification/run_gates.py": X}, "proof/x", False, 1,
     {"PATH_SCOPE", "TRUSTED_DRIFT"}),
    ("decl 改 garbage-signoffs", {F + b"verification/garbage-signoffs.yaml": X}, "decl/x", False, 1,
     {"PATH_SCOPE", "TRUSTED_DRIFT"}),
    ("audit 加必红夹具", {F + b"verification/must_red/y/N.lean": X}, "audit/x", False, 1,
     {"PATH_SCOPE", "TRUSTED_DRIFT"}),
] + [("内容角色删受信文件 %s" % p.decode(), {p: None}, "audit/x", False, 1, {"PATH_SCOPE", "TRUSTED_DRIFT"})
     for p in TRUSTED_LIST]


def run(script, argv, env=RUN_ENV, py=(), **kw):
    kw = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, **kw}
    p = subprocess.run([sys.executable, "-I", *py, script, *argv], env=env, **kw)
    return p.returncode, p.stdout, p.stderr


def codes(stdout, stderr):
    """规则码集合。标准输出只许绿行与红行且每行都是 PRECHECK 行，标准错误里的 PRECHECK 行只许故障行；错位返回 None。"""
    outs, errs = LINE.findall(stdout), LINE.findall(stderr)
    if any(not l.startswith(b"PRECHECK ") for l in stdout.splitlines()) or \
            any(k not in (b"RED", b"GREEN") for k, _ in outs) or any(k != b"FAULT" for k, _ in errs):
        return None
    return {c.decode() for k, c in outs + errs if k != b"GREEN"}


def apply(files, edits):
    files = dict(files)
    for k, v in edits.items():
        if v is None:
            files.pop(k, None)
        else:
            files[k] = v
    return files


def build(tmp):
    assert len({c[0] for c in CASES}) == len(CASES), "用例名重复"
    repo = Repo(os.path.join(os.fsencode(tmp), "仓库 r".encode("utf-8")))  # 非 ASCII 且含空格的仓库路径
    base = repo.commit(BASE)
    heads, parents = {}, {}
    for case in CASES:
        name, edits = case[:2]
        parents[name] = repo.commit(apply(BASE, case[6])) if len(case) > 6 else base
        heads[name] = repo.commit(apply(BASE, edits), parents[name])
    # 第 3 条：暂存区与工作树里放上会被判红的东西，并用普通文件掩盖提交里的符号链接（R5-B6）。
    git(repo.path, "read-tree", base)
    for path in ("lakefile.lean", "Chan/Thm/link.lean"):
        git(repo.path, "update-index", "--add", "--cacheinfo", "100644,%s,%s" % (
            repo.blob(b"module\n").decode(), FM + path))
    os.makedirs(os.path.join(repo.path, b(FM + "Chan/Thm")))
    with open(os.path.join(repo.path, b(FM + "Chan/Thm/link.lean")), "wb") as f:
        f.write(b"module\n")
    # 缺失对象：整仓复制一份（测试仓库的对象都是松散对象），删掉绿例被审提交的根树对象。
    green = heads["proof 改 Thm"]
    repo.corrupt = os.path.join(os.path.dirname(repo.path), b"corrupt")
    shutil.copytree(repo.path, repo.corrupt)
    tree = git(repo.corrupt, "rev-parse", green + "^{tree}").strip().decode()
    os.remove(os.path.join(repo.corrupt, b".git/objects", tree[:2].encode(), tree[2:].encode()))
    # 输出被篡改的 git：cat-file --batch 的输出后面多出一个字节（真实 git 不会这样，用来锁住输出核对）。
    repo.wrapped = os.path.join(os.fsdecode(os.path.dirname(repo.path)), "wrapped-git")
    os.makedirs(repo.wrapped)
    with open(os.path.join(repo.wrapped, "git"), "w", encoding="utf-8") as f:
        f.write('#!/bin/sh\nfor a in "$@"; do [ "$a" = --batch ] && { %s "$@"; s=$?; printf x; exit $s; }; done\n'
                'exec %s "$@"\n' % ((shlex.quote(shutil.which("git")),) * 2))
    os.chmod(os.path.join(repo.wrapped, "git"), 0o755)
    return repo, base, heads, parents


def special(script, repo, base, heads):
    """参数、祖先、输出环境类用例：(名字, 通过与否, 实际)。"""
    green, red = heads["proof 改 Thm"], heads["decl 改 proof 的路径"]
    r = repo.path
    results = []

    def expect(name, got, rc, want, extra=True):
        results.append((name, got[0] == rc and codes(got[1], got[2]) == want and extra, got))

    sibling = heads["proof 改 decl 的路径"]
    expect("规则 1：基线不是祖先", run(script, [r, green, sibling, "proof/x"]), 2, {"NOT_ANCESTOR"})
    expect("规则 1：基线是后代", run(script, [r, green, base, "proof/x"]), 2, {"NOT_ANCESTOR"})
    expect("规则 1：基线等于被审", run(script, [r, base, base, "proof/x"]), 0, set())
    expect("无参数", run(script, []), 2, {"USAGE"})
    expect("多余参数", run(script, [r, base, green, "proof/x", "y"]), 2, {"USAGE"})
    expect("选项缩写", run(script, ["--trusted", r, base, green, "infra/x"]), 2, {"USAGE"})
    expect("选项带值", run(script, ["--trusted-change-approved=1", r, base, green, "infra/x"]), 2, {"USAGE"})
    expect("选项重复", run(script, ["--trusted-change-approved"] * 2 + [r, base, green]), 2, {"USAGE"})
    expect("选项放在后面", run(script, [r, base, green, "infra/x", "--trusted-change-approved"]), 2, {"USAGE"})
    expect("--rev 类参数", run(script, [r, "--output=x", green, "proof/x"]), 2, {"USAGE"})
    expect("空仓库参数", run(script, ["", base, green, "proof/x"]), 2, {"USAGE"})
    expect("基线解析不出", run(script, [r, "nope", green, "proof/x"]), 2, {"BAD_REV"})
    expect("基线是树对象", run(script, [r, base + "^{tree}", green, "proof/x"]), 2, {"BAD_REV"})
    expect("被审带范围语法", run(script, [r, base, base + ".." + green, "proof/x"]), 2, {"BAD_REV"})
    expect("被审提交的根树对象缺失", run(script, [repo.corrupt, base, green, "proof/x"]), 2, {"GIT"})
    wrapped_env = {**RUN_ENV, "PATH": repo.wrapped + os.pathsep + RUN_ENV["PATH"]}
    expect("R2-M4 cat-file 输出尾随多余字节", run(script, [r, base, green, "proof/x"], env=wrapped_env), 2, {"GIT"})
    expect("仓库不存在", run(script, [r + b"/nope", base, green, "proof/x"]), 2, {"GIT"})
    rd, wr = os.pipe()
    os.close(rd)
    got = run(script, [r, base, green, "proof/x"], stdout=wr, stderr=subprocess.PIPE)
    os.close(wr)
    expect("绿例遇管道断开", (got[0], b"", got[2]), 2, {"OUTPUT"}, b"Broken pipe" in got[2])
    rd, wr = os.pipe()
    os.close(rd)
    got = run(script, [r, base, red, "decl/x"], stdout=wr, stderr=subprocess.PIPE)
    os.close(wr)
    expect("红例遇管道断开", (got[0], b"", got[2]), 1, set())
    got = subprocess.run([sys.executable, "-I", script, r, base, green, "proof/x"], env=RUN_ENV,
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, preexec_fn=lambda: os.close(1))
    expect("绿例遇标准输出关闭", (got.returncode, b"", got.stderr), 2, {"OUTPUT"},
           b"Bad file descriptor" in got.stderr)
    ascii_env = {"PATH": RUN_ENV["PATH"], "LC_ALL": "C"}
    got = run(script, [r, base, green, "proof/x"], env=ascii_env, py=("-X", "utf8=0"))
    expect("ASCII locale 绿行", got, 0, set(),
           got[1].decode("utf-8") == "PRECHECK GREEN OK %s role=proof\n" % green)
    got = run(script, [r, base, red, "decl/x"], env=ascii_env, py=("-X", "utf8=0"))
    expect("ASCII locale 红行", got, 1, {"PATH_SCOPE"}, "decl 角色不得改此路径" in got[1].decode("utf-8"))
    got = run(script, [r, base, heads["含换行路径"], "proof/x"])
    expect("红行里换行被转义", got, 1, {"PATH_GRAMMAR"}, got[1].count(b"\n") == 1 and b"A\\x0aB" in got[1])
    return results


def tables(script):
    """规则 5 的结构断言：内容角色的表不碰受信面，infra 的表只有受信面加说明文档。"""
    m = load(script)
    ok = True
    for role, rules in m.ROLES.items():
        for rule in rules:
            if role == b"infra":
                ok &= rule in m.TRUSTED_SURFACE or rule == m.FM + b"README.md"
            else:
                ok &= not any(t.startswith(rule) or rule.startswith(t) for t in m.TRUSTED)
                ok &= not rule.startswith(m.GATE_DIR)
    return [("角色表互斥", bool(ok), None)]


@functools.lru_cache(maxsize=None)
def load(script):
    sys.dont_write_bytecode = True  # 不在源码目录留下 __pycache__
    spec = importlib.util.spec_from_file_location("precheck_under_test", script)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def expected_role(branch):
    """绿行里的角色按未改弱的 precheck.py 的分支文法算，不另写近似正则。"""
    m = load(PRECHECK).BRANCH.fullmatch(b(branch))
    return m.group(1) if m else b"-"


def suite(script, tmp, verbose, fixture=None):
    """fixture 是 build() 的结果；夹具仓库对预检只读，--mutants 各轮复用同一份。"""
    repo, base, heads, parents = fixture or build(tmp)
    results = []
    for name, _, branch, approved, rc, want, *_ in CASES:
        argv = [repo.path, parents[name], heads[name], b(branch)]
        got = run(script, (["--trusted-change-approved"] if approved else []) + argv)
        green_line = got[0] != 0 or got[1] == b"PRECHECK GREEN OK %s role=%s\n" % (heads[name].encode(),
                                                                                     expected_role(branch))
        results.append((name, got[0] == rc and codes(got[1], got[2]) == want and bool(green_line), got))
    results += special(script, repo, base, heads) + tables(script)
    failed = [r for r in results if not r[1]]
    if verbose:
        for name, ok, got in results:
            if not ok:
                out("FAIL %s: rc=%s\n%s%s" % (name, got and got[0], got and got[1].decode("utf-8", "replace") or "",
                                              got and got[2].decode("utf-8", "replace") or ""))
    return len(results), len(failed)


MUTANTS = [
    ("去掉第 7 步", 'if old.get(path) != new.get(path):\n                red("TRUSTED_DRIFT"',
     'if False:\n                red("TRUSTED_DRIFT"'),
    ("去掉模式判断", "if mode != want and (want or mode not in (FILE_MODE, TREE_MODE)):", "if False:"),
    ("去掉目录节点核对（空目录）", "dirs = {p for p, (mode, _) in tree.items()", "dirs = set() & {p for p, (mode, _) in tree.items()"),
    ("目录节点的改动不过路径权限", "return within(path + b\"/\", rules) or any(", "return True or any("),
    ("角色表前缀放宽一项：infra 的门禁目录放宽为 formal_math/", 'TRUSTED_SURFACE = TRUSTED_FILES + (GATE_DIR + b"/",)',
     "TRUSTED_SURFACE = TRUSTED_FILES + (FM,)"),
    ("角色表前缀放宽一项：proof 的 Chan/Thm/ 放宽为 Chan/", 'b"Chan/Thm/", b"Chan/Proofs/"',
     'b"Chan/", b"Chan/Proofs/"'),
    ("第 7 步漏比 lean-toolchain（审阅 M2）", "TRUSTED = TRUSTED_FILES + (GATE_DIR,)",
     "TRUSTED = TRUSTED_FILES[:2] + TRUSTED_FILES[3:] + (GATE_DIR,)"),
    ("放行开关让内容角色跳过第 7 步（审阅 M7）", 'if role != b"infra":\n        for path in TRUSTED:',
     'if role != b"infra" and not approved:\n        for path in TRUSTED:'),
    ("去掉树条目重名检查", "if name in names or key <= last:", "if key <= last:"),
    ("去掉树条目次序检查", "if name in names or key <= last:", "if name in names:"),
    ("Lake 配置名只查顶层", "if parts[-1].lower() in LAKE_NAMES", "if len(parts) == 1 and parts[-1].lower() in LAKE_NAMES"),
    ("去掉大小写冲突判断（审阅 M1）", 'if twin != rel:\n            red("PATH_GRAMMAR"', 'if False:\n            red("PATH_GRAMMAR"'),
    ("祖先检查恒真（审阅 M3）", 'if git(repo, b"merge-base", b"--is-ancestor", base, head, ok=(0, 1))[0]:', "if False:"),
    ("分支名文法放宽（审阅 M4）", 'WORD = rb"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*"', 'WORD = rb"[A-Za-z0-9._-]+"'),
    ("目录条目不核对对象类型", "if kind != TREE:\n                red(", "if False:\n                red("),
    ("去掉对象名截断检查（审阅 R2-M2）", "if not m or m.end() + hash_len > len(body):", "if not m:"),
    ("去掉 cat-file 输出多余字节检查（审阅 R2-M4）", "if pos != len(data):", "if False:"),
    ("TRUST_UNAPPROVED 漏掉门禁目录节点自身（审阅 R2-M10）", "any(p == GATE_DIR or within(p, TRUSTED_SURFACE)",
     "any(within(p, TRUSTED_SURFACE)"),
    ("祖先目录不进改动集合（审阅 R2-B1）", "entry[:1] if path in ANCESTORS else entry",
     "None if path in ANCESTORS else entry"),
    ("形状检查只在清单有变化时做（审阅 R2-B1）",
     "    shape(new, red)\n    file_objects(repo, new, red)\n    base_form = []\n"
     "    old = inventory(repo, base, lambda *r: base_form.append(r))\n",
     "    file_objects(repo, new, red)\n    base_form = []\n"
     "    old = inventory(repo, base, lambda *r: base_form.append(r))\n    shape(new, red) if old != new else None\n"),
    ("去掉文件条目的 blob 类型核对", "if kinds[oid][0] != BLOB:", "if False:"),
    ("Lake 配置名例外不分文件与目录", "(kind != BLOB or path not in LAKE_ALLOWED)", "(path not in LAKE_ALLOWED)"),
]


def mutants(tmp):
    source = open(PRECHECK, encoding="utf-8").read()
    fixture = build(os.path.join(tmp, "fixture"))
    ok = True
    for i, (name, old, new) in enumerate([("未改弱的副本", "", "")] + MUTANTS):
        if old and source.count(old) != 1:
            out("MUTANT %s：改弱点在源码里不唯一或不存在\n" % name)
            ok = False
            continue
        script = os.path.join(tmp, "m%d" % i, "precheck.py")
        os.makedirs(os.path.dirname(script))
        with open(script, "w", encoding="utf-8") as f:
            f.write(source.replace(old, new) if old else source)
        total, failed = suite(script, None, verbose=not old, fixture=fixture)
        killed = failed > 0
        out("MUTANT %s：%d 例中 %d 例失败（%s）\n" % (name, total, failed, "应全过" if not old else "应被抓住"))
        ok &= killed if old else not failed
    return ok


def main(argv):
    if argv[1:] not in ([], ["--mutants"]):
        out("用法：selftest.py [--mutants]\n")
        return 2
    tmp = tempfile.mkdtemp(prefix="precheck-selftest-")
    try:
        if argv[1:]:
            ok = mutants(tmp)
        else:
            total, failed = suite(PRECHECK, tmp, verbose=True)
            out("SELFTEST %d 例，失败 %d 例\n" % (total, failed))
            ok = not failed
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out("SELFTEST %s\n" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
