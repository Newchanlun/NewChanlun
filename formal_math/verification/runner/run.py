#!/usr/bin/env python3
"""#2312 第二片：formal_math 阻断门的运行骨架。七步固定顺序，前一步不绿即停；规则与信任前提见同目录 README.md。
退出码 0 七步全绿、1 某步判红、2 无法判定（含 --until 提前停下）。"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

USAGE = ("[--trusted-change-approved] [--bootstrap-trusted-from <提交>] [--until <1-7>] --repo <仓库> "
         "--base <基线提交> --head <被审提交> --branch <分支名> --workdir <工作目录> --packages <依赖目录>")
FLAG = b"--trusted-change-approved"
OPTIONS = (b"--bootstrap-trusted-from", b"--until", b"--repo", b"--base", b"--head", b"--branch",
           b"--workdir", b"--packages")
STEPS = ("precheck", "fetch", "auditor", "headers", "shape", "build", "env")
GATE = b"formal_math/verification"
TRUSTED_CODE = (GATE + b"/runner/run.py", GATE + b"/precheck/precheck.py", GATE + b"/auditor/lakefile.toml")
CONFIGS = (b"lakefile.toml", b"lake-manifest.json", b"lean-toolchain")
CONTENT_ROOTS = (b"Chan", b"ChanTest", b"ChanChallenge", b"ChanDyn", b"ChanExplore")
CONTENT_TOP = (b"Chan.lean", b"ChanExplore.lean")
ROOT_NAMES = {r.decode() for r in CONTENT_ROOTS}
SEGMENT = re.compile(rb"[A-Za-z0-9_][A-Za-z0-9_.-]*")
MODULE = re.compile(rb"[A-Za-z][A-Za-z0-9_]*")
PACKAGE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*")
OID = re.compile(rb"[0-9a-f]{40}|[0-9a-f]{64}")
TREE_ENTRY = re.compile(rb"([0-7]{6}) (blob|tree|commit) ([0-9a-f]{40}|[0-9a-f]{64})\t(.+)", re.S)
PRECHECK_RED = re.compile(rb"PRECHECK RED ([A-Z_]+) (\S+) (.+)")
GIT_ENV = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C", "GIT_NO_REPLACE_OBJECTS": "1",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_GRAFT_FILE": os.devnull,
           "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
TIMEOUT = {"git": 600, "precheck": 600, "auditor": 3600, "headers": 600, "build": 4 * 3600, "env": 3600}


class Fault(Exception):
    """无法判定：args = (规则码, 对象, 说明)。"""


class Run:
    """一次运行的输入与中间产物；字段在各步里依次填上。"""


def show(obj):
    obj = obj if isinstance(obj, bytes) else str(obj).encode("utf-8")
    return b"".join(bytes([c]) if 0x21 <= c < 0x7F and c != 0x5C else b"\\x%02x" % c for c in obj) or b"-"


def emit(fd, *fields):
    """按 UTF-8 字节直接写文件描述符；写不出时返回该错误。"""
    data = b" ".join(f if isinstance(f, bytes) else str(f).encode("utf-8") for f in fields) + b"\n"
    try:
        while data:
            data = data[os.write(fd, data):]
    except OSError as e:
        return e


def call(argv, timeout, code, **kw):
    try:
        return subprocess.run(argv, timeout=timeout, **kw)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Fault(code, argv[0], "%s: %s" % (type(e).__name__, getattr(e, "strerror", None) or e))


def git(ctx, *args, data=None, ok=(0,)):
    argv = [b"git", b"-C", ctx.repo, b"-c", b"advice.graftFileDeprecated=false", *args]
    p = call(argv, TIMEOUT["git"], "GIT", env=GIT_ENV, input=data,
             stdin=subprocess.DEVNULL if data is None else None, stdout=subprocess.PIPE)
    if p.returncode not in ok:
        raise Fault("GIT", args[0], "git 退出 %d" % p.returncode)
    return p.returncode, p.stdout


def commit(ctx, rev):
    rc, out = git(ctx, b"rev-parse", b"--verify", b"--quiet", b"--end-of-options", rev + b"^{commit}", ok=(0, 1))
    if rc or not OID.fullmatch(out.strip()):
        raise Fault("BAD_REV", rev, "解析不出提交")
    return out.strip()


def object_at(ctx, rev, path):
    rc, out = git(ctx, b"rev-parse", b"--verify", b"--quiet", b"--end-of-options", rev + b":" + path, ok=(0, 1))
    return None if rc else out.strip()


def tree(ctx, rev, path):
    """`<提交>:<路径>` 下的全部条目 [(相对路径, 模式, 类型, 对象)]，不经检出、不读 .gitattributes。"""
    out = git(ctx, b"ls-tree", b"-r", b"-z", b"--end-of-options", rev + b":" + path)[1]
    entries = []
    for rec in out.split(b"\0")[:-1]:
        m = TREE_ENTRY.fullmatch(rec)
        if not m:
            raise Fault("GIT", b"ls-tree", "输出无法解读")
        mode, kind, oid, rel = m.groups()
        entries.append((rel, mode, kind, oid))
    return entries


def blobs(ctx, oids):
    """`cat-file --batch` 按对象名取原始字节，不做任何过滤或换行转换。"""
    uniq = sorted(set(oids))
    out = git(ctx, b"cat-file", b"--batch", data=b"".join(o + b"\n" for o in uniq))[1]
    result, pos = {}, 0
    for oid in uniq:
        end = out.find(b"\n", pos)
        head = out[pos:end].split(b" ")
        if end < 0 or len(head) != 3 or head[0] != oid or head[1] != b"blob" or not head[2].isdigit():
            raise Fault("GIT", oid, "cat-file 输出无法解读")
        size = int(head[2])
        result[oid], pos = out[end + 1:end + 1 + size], end + 2 + size
        if out[pos - 1:pos] != b"\n":
            raise Fault("GIT", oid, "cat-file 输出无法解读")
    if pos != len(out):
        raise Fault("GIT", b"cat-file", "输出多出字节")
    return result


def write_files(root, files):
    """逐个新建文件，模式固定 0644、目录 0755；已存在或遇到符号链接即失败。"""
    made = set()
    for rel, data in files:
        parts = rel.split("/")
        for i in range(1, len(parts)):
            d = os.path.join(root, *parts[:i])
            if d not in made:
                if not os.path.isdir(d) or os.path.islink(d):
                    os.mkdir(d, 0o755)
                made.add(d)
        fd = os.open(os.path.join(root, *parts), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        try:
            os.fchmod(fd, 0o644)
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
        finally:
            os.close(fd)


def read(path):
    with open(path, "rb") as f:
        return f.read()


def inside(a, b):
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


def sandbox(ctx, argv, binds, env, cwd, timeout, code, stdout):
    """bwrap：根只读，/home 等换成空 tmpfs，整个工作目录先盖成空 tmpfs 再按需回绑；断网、清环境。"""
    args = [b"bwrap", b"--ro-bind", b"/", b"/"]
    for hidden in ("/home", "/root", "/run", "/var", "/tmp", ctx.workdir):
        args += [b"--tmpfs", hidden.encode()]
    args += [b"--dir", b"/tmp/home", b"--dev", b"/dev", b"--proc", b"/proc"]
    for kind, src, dst in binds + [("--ro-bind", ctx.prefix, ctx.prefix)]:
        args += [kind.encode(), src.encode(), dst.encode()]
    args.append(b"--clearenv")
    base = {"HOME": "/tmp/home", "TMPDIR": "/tmp", "LANG": "C.UTF-8",
            "PATH": os.path.join(ctx.prefix, "bin") + ":/usr/bin:/bin"}
    for key, value in {**base, **env}.items():
        args += [b"--setenv", key.encode(), value.encode()]
    args += [b"--unshare-all", b"--die-with-parent", b"--new-session", b"--chdir", cwd.encode(), b"--",
             *(a if isinstance(a, bytes) else a.encode() for a in argv)]
    return call(args, timeout, code, stdin=subprocess.DEVNULL, stdout=stdout, env={"PATH": GIT_ENV["PATH"]})


# ---- 第 1 步：预检（第一片，取自受信提交） ----

def step_precheck(ctx):
    path = os.path.join(ctx.workdir, "step1")
    os.mkdir(path, 0o700)
    oid = object_at(ctx, ctx.trusted, TRUSTED_CODE[1])
    write_files(path, [("precheck.py", blobs(ctx, [oid])[oid])])
    argv = [sys.executable, "-I", os.path.join(path, "precheck.py"), *([FLAG] if ctx.approved else []),
            ctx.repo, ctx.base, ctx.head, ctx.branch]
    p = call(argv, TIMEOUT["precheck"], "PRECHECK", stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
             env={"PATH": GIT_ENV["PATH"]})
    lines = p.stdout.split(b"\n")
    if lines[-1] != b"":
        raise Fault("PRECHECK_OUTPUT", b"stdout", "预检输出没有以换行结尾")
    lines = lines[:-1]
    if p.returncode == 0 and len(lines) == 1 and lines[0].startswith(b"PRECHECK GREEN OK " + ctx.head + b" role="):
        return [], lines[0][len(b"PRECHECK GREEN OK ") + len(ctx.head) + 1:].decode("ascii", "replace")
    reds = [PRECHECK_RED.fullmatch(line) for line in lines]
    if p.returncode == 1 and reds and all(reds):
        return [(m[1].decode(), m[2], m[3].decode("utf-8", "replace")) for m in reds], ""
    raise Fault("PRECHECK_EXIT", b"precheck.py", "预检退出 %d，输出 %d 行，无法解读为绿或红" % (p.returncode, len(lines)))


# ---- 第 2 步：取料 ----

def step_fetch(ctx):
    trusted_files = []
    for rel, mode, kind, oid in tree(ctx, ctx.trusted, GATE):
        if mode != b"100644" or kind != b"blob" or not all(SEGMENT.fullmatch(s) for s in rel.split(b"/")):
            raise Fault("TRUSTED_TREE", GATE + b"/" + rel, "受信提交的门禁目录里有非常规条目")
        trusted_files.append((rel.decode("ascii"), oid))
    configs, base_tree = [], tree(ctx, ctx.base, b"formal_math")
    for name in CONFIGS:
        entry = [e for e in base_tree if e[0] == name]
        if len(entry) != 1 or entry[0][1] != b"100644" or entry[0][2] != b"blob":
            raise Fault("BASE_CONFIG", b"formal_math/" + name, "基线缺这个构建配置文件或不是普通文件")
        configs.append((name.decode("ascii"), entry[0][3]))
    if object_at(ctx, ctx.head, b"formal_math") is None:
        raise Fault("NO_PACKAGE", ctx.head, "被审提交没有 formal_math/")
    reds, content = [], []
    for rel, mode, kind, oid in tree(ctx, ctx.head, b"formal_math"):
        parts = rel.split(b"/")
        if not (parts[0] in CONTENT_ROOTS and len(parts) > 1 or rel.endswith(b".lean") and len(parts) == 1):
            continue
        stems = parts[:-1] + [parts[-1][:-5] if parts[-1].endswith(b".lean") else b""]
        if mode != b"100644" or kind != b"blob" or not all(MODULE.fullmatch(s) for s in stems) or \
                len(parts) == 1 and rel not in CONTENT_TOP:
            reds.append(("CONTENT_PATH", b"formal_math/" + rel, "内容文件须是模块名文法的 100644 .lean 普通文件"))
            continue
        content.append((rel.decode("ascii"), oid))
    if reds:
        return reds, ""
    if not content:
        raise Fault("NO_CONTENT", ctx.head, "被审提交没有内容文件")
    data = blobs(ctx, [oid for _, oid in trusted_files + configs + content])
    ctx.trusted_dir, ctx.audited = os.path.join(ctx.workdir, "trusted"), os.path.join(ctx.workdir, "audited")
    os.mkdir(ctx.trusted_dir, 0o700)
    os.mkdir(ctx.audited, 0o700)
    write_files(ctx.trusted_dir, [("verification/" + rel, data[oid]) for rel, oid in trusted_files])
    write_files(ctx.audited, [(rel, data[oid]) for rel, oid in configs + content])
    ctx.content = sorted(rel for rel, _ in content)
    ctx.modules = [rel[:-5].replace("/", ".") for rel in ctx.content]
    ctx.lock = object_at(ctx, ctx.head, b"formal_math/statement-lock.json")
    return [], "受信 %d 个文件，内容 %d 个模块，配置取自基线" % (len(trusted_files), len(content))


# ---- 第 3 步：构建审计程序（受信目录，来源与配置都取自受信提交） ----

def step_auditor(ctx):
    pkg = os.path.join(ctx.trusted_dir, "verification", "auditor")
    toolchain = read(os.path.join(ctx.audited, "lean-toolchain"))
    if not os.path.isfile(os.path.join(pkg, "lean-toolchain")) or read(os.path.join(pkg, "lean-toolchain")) != toolchain:
        raise Fault("TOOLCHAIN_MISMATCH", b"auditor/lean-toolchain", "审计程序与被审包的工具链文件不同")
    m = re.fullmatch(rb"leanprover/lean4:v([0-9][0-9A-Za-z.-]*)\n?", toolchain)
    if not m:
        raise Fault("TOOLCHAIN", b"formal_math/lean-toolchain", "工具链文件不合 leanprover/lean4:v<版本>")
    p = call(["lean", "--print-prefix"], 60, "TOOLCHAIN", cwd=pkg, stdin=subprocess.DEVNULL,
             stdout=subprocess.PIPE, env={k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "ELAN_HOME")})
    ctx.prefix = os.path.realpath(p.stdout.decode("utf-8", "replace").strip()) if p.returncode == 0 else ""
    lean, lake = os.path.join(ctx.prefix, "bin", "lean"), os.path.join(ctx.prefix, "bin", "lake")
    v = call([lean, "--version"], 60, "TOOLCHAIN", stdin=subprocess.DEVNULL, stdout=subprocess.PIPE) \
        if ctx.prefix and os.path.isfile(lean) else None
    if v is None or not v.stdout.startswith(b"Lean (version " + m[1] + b","):
        raise Fault("TOOLCHAIN", ctx.prefix or "lean", "运行中的 Lean 与工具链文件 v%s 不符" % m[1].decode())
    home = os.path.join(ctx.workdir, "home")
    os.mkdir(home, 0o700)
    env = {"PATH": os.path.join(ctx.prefix, "bin") + ":/usr/bin:/bin", "HOME": home, "LANG": "C.UTF-8"}
    p = call([lake, "build"], TIMEOUT["auditor"], "AUDITOR_BUILD", cwd=pkg, env=env,
             stdin=subprocess.DEVNULL, stdout=2)
    ctx.auditor = os.path.join(pkg, ".lake", "build", "bin", "fm_audit")
    if p.returncode or os.path.islink(ctx.auditor) or not os.path.isfile(ctx.auditor):
        raise Fault("AUDITOR_BUILD", pkg, "受信审计程序构建失败（退出 %d）" % p.returncode)
    digest = hashlib.sha256(read(ctx.auditor)).hexdigest()
    return [], "binary=%s sha256=%s" % (ctx.auditor, digest)


def run_auditor(ctx, command, binds, env, timeout):
    """在沙箱里跑受信审计程序，逐行解析 JSON；退出码只用于核对，不用于下结论。"""
    p = sandbox(ctx, [ctx.auditor, command, *ctx.auditor_args], binds, env, ctx.audited, timeout,
                "AUDITOR", subprocess.PIPE)
    rows = []
    try:
        text = p.stdout.decode("utf-8")
        if not text.endswith("\n"):
            raise ValueError
        rows = [json.loads(line) for line in text[:-1].split("\n")]
    except ValueError:
        raise Fault("AUDITOR_OUTPUT", command, "审计程序输出不是逐行 JSON（退出 %d）" % p.returncode)
    result = rows.pop() if rows else None
    if not (isinstance(result, list) and len(result) == 4 and result[:2] == ["result", command] and
            result[2] in ("red", "green") and type(result[3]) is int):
        raise Fault("AUDITOR_OUTPUT", command, "缺少结果行（退出 %d）" % p.returncode)
    findings = [r for r in rows if isinstance(r, list) and r[:1] == ["finding"]]
    if any(len(f) != 6 or not all(isinstance(x, str) for x in f) for f in findings) or \
            (result[2] == "red") != bool(findings) or p.returncode != (1 if findings else 0):
        raise Fault("AUDITOR_OUTPUT", command, "判定、发现与退出码 %d 不一致" % p.returncode)
    if result[3] != len(ctx.modules):
        raise Fault("MODULE_COUNT", command, "审计程序审过 %d 个模块，git 树里有 %d 个" % (result[3], len(ctx.modules)))
    return findings, [r for r in rows if not (isinstance(r, list) and r[:1] == ["finding"])]


# ---- 第 4 步：头部规则 ----

PROOF_LANES = {"Chan.Thm", "Chan.Proofs", "Chan.Exec"}
FOUNDATION = {"Chan.Defs", "Chan.Proxy", "Chan.Hypotheses"}
AUDIT_LANES = {"Chan.Audit", "Chan.Audit.Literal"}
EXTERNAL = {"Lean", "Init", "Std", "Mathlib", "Batteries", "Aesop", "Qq", "Plausible",
            "ProofWidgets", "LeanSearchClient", "ImportGraph", "Cli", "Lake"}


def lane(module):
    for prefix in (
        "Chan.Audit.Literal", "Chan.Defs", "Chan.Proxy", "Chan.Hypotheses", "Chan.Thm",
        "Chan.Proofs", "Chan.Exec", "Chan.Audit", "Chan.Final", "ChanChallenge",
        "ChanDyn", "ChanTest", "ChanExplore",
    ):
        if module == prefix or module.startswith(prefix + "."):
            return prefix
    return "Chan" if module == "Chan" or module.startswith("Chan.") else ""


def allowed_edge(src, dst, local, transitive=False):
    a, b = lane(src), lane(dst)
    if dst not in local:
        external = dst.partition(".")[0]
        if a in {"ChanChallenge", "Chan.Audit.Literal"}:
            return external in {"Mathlib", "Init"}
        return external in EXTERNAL
    if not a or not b:
        return False
    if a == "ChanExplore":
        return True
    if b == "ChanExplore":
        return False
    if a in {"ChanChallenge", "Chan.Audit.Literal"}:
        return b in {
            "Chan.Defs", "Chan.Hypotheses", "Chan.Audit.Literal",
        }
    if a == "Chan.Defs":
        return b == "Chan.Defs"
    if a in {"Chan.Proxy", "Chan.Hypotheses"}:
        return b in {a, "Chan.Defs"}
    if a in PROOF_LANES:
        return b in FOUNDATION | PROOF_LANES
    if a in AUDIT_LANES:
        return b in FOUNDATION | PROOF_LANES | AUDIT_LANES
    if a == "Chan.Final":
        return b == "Chan.Thm" or transitive and b in FOUNDATION | PROOF_LANES
    if a == "ChanDyn":
        return b in FOUNDATION | PROOF_LANES | AUDIT_LANES | {"Chan", "Chan.Final", "ChanDyn"}
    if a == "ChanTest":
        return b not in {"ChanChallenge", "ChanExplore"}
    return b not in {"ChanChallenge", "ChanDyn", "ChanTest"}


def step_headers(ctx):
    ctx.auditor_args = [x for rel, mod in zip(ctx.content, ctx.modules) for x in (mod, rel)]
    binds = [("--ro-bind", ctx.audited, ctx.audited), ("--ro-bind", ctx.trusted_dir, ctx.trusted_dir)]
    findings, rows = run_auditor(ctx, "headers", binds, {}, TIMEOUT["headers"])
    source = {}
    for row in rows:
        if not (isinstance(row, list) and len(row) == 5 and row[0] == "header" and row[1] in ctx.content and
                row[1] not in source and row[2] == ctx.modules[ctx.content.index(row[1])] and
                isinstance(row[3], bool) and isinstance(row[4], list) and
                all(isinstance(i, list) and len(i) == 4 and isinstance(i[0], str) and type(i[1]) is int and
                    isinstance(i[2], bool) and isinstance(i[3], bool) for i in row[4])):
            raise Fault("AUDITOR_OUTPUT", "headers", "头部记录无法解读")
        source[row[1]] = (row[3], [(dst, line, import_all) for dst, line, import_all, _ in row[4]])
    unparsed = {f[2] for f in findings if f[4] == "HEADER_PARSE"}
    if source.keys() | unparsed != set(ctx.content) or source.keys() & unparsed:
        raise Fault("AUDITOR_OUTPUT", "headers", "头部记录与请求的文件不一一对应")
    reds = [(f[4], "formal_math/%s:%s" % (f[2], f[3]), f[5]) for f in findings]
    local = set(ctx.modules)
    graph = {}
    for path, (is_module, imports) in source.items():
        module = ctx.modules[ctx.content.index(path)]
        graph[module] = []
        if not is_module:
            continue  # MODULE_FIRST 已由审计程序报出。
        for dst, line, _ in imports:
            graph[module].append((dst, line))
            where = "formal_math/%s:%d" % (path, line)
            if dst == "Mathlib":
                reds.append(("WHOLE_MATHLIB", where, "请只导入所需的 Mathlib 子模块"))
            elif not allowed_edge(module, dst, local):
                reds.append(("IMPORT_EDGE", where, f"禁止导入 {dst}"))
    if reds:
        return reds, ""
    for path in ctx.content:
        module = ctx.modules[ctx.content.index(path)]
        for dst, line in graph.get(module, ()):
            pending, seen = [dst], {module}
            while pending:
                target = pending.pop()
                if target in seen:
                    continue
                seen.add(target)
                if not allowed_edge(module, target, local, transitive=True):
                    reds.append(("IMPORT_CLOSURE", "formal_math/%s:%d" % (path, line), f"经 {dst} 间接导入 {target}"))
                    break
                pending.extend(imported for imported, _ in graph.get(target, ()))
    return reds, "%d 个文件头" % len(source)


# ---- 第 5 步：源码形状（第四片） ----

def step_shape(ctx):
    return [], "SHAPE 未安装：源码形状门归第四片，本次的绿不含这一层"


# ---- 第 6 步：沙箱构建 ----

def step_build(ctx):
    lake_dir = os.path.join(ctx.audited, ".lake")
    os.mkdir(lake_dir, 0o755)
    os.mkdir(os.path.join(lake_dir, "packages"), 0o755)
    binds = [("--ro-bind", ctx.audited, ctx.audited), ("--bind", lake_dir, lake_dir),
             ("--ro-bind", ctx.packages, os.path.join(lake_dir, "packages"))]
    probe = sandbox(ctx, ["lean", "--version"], binds, {}, ctx.audited, 60, "SANDBOX", subprocess.PIPE)
    if probe.returncode or not probe.stdout.startswith(b"Lean (version "):
        raise Fault("SANDBOX", b"bwrap", "沙箱探针失败（退出 %d）" % probe.returncode)
    p = sandbox(ctx, ["lake", "build", "--wfail"], binds, {}, ctx.audited, TIMEOUT["build"], "BUILD", 2)
    if p.returncode < 0:
        raise Fault("BUILD", b"lake", "构建被信号 %d 终止" % -p.returncode)
    if p.returncode:
        return [("BUILD_WFAIL", b"formal_math/lakefile.toml", "lake build --wfail 退出 %d" % p.returncode)], ""
    reds = []
    for rel in ctx.content:
        olean = os.path.join(lake_dir, "build", "lib", "lean", rel[:-5] + ".olean")
        if os.path.islink(olean) or not os.path.isfile(olean):
            reds.append(("NO_ARTIFACT", "formal_math/" + rel, "默认目标的构建没有产出这个模块的 .olean"))
    # 第 7 步的搜索路径上被审产物排在工具链库之前：顶层只许内容根，免得遮住 Init 等库模块。
    lib = os.path.join(lake_dir, "build", "lib", "lean")
    if os.path.realpath(lib) != lib:
        reds.append(("ARTIFACT_ROOT", "formal_math/.lake/build/lib/lean", "产物目录不得是符号链接或经由符号链接"))
    for name in sorted(os.listdir(lib)) if os.path.isdir(lib) else []:
        if name.split(".")[0] not in ROOT_NAMES or os.path.islink(os.path.join(lib, name)):
            reds.append(("ARTIFACT_ROOT", "formal_math/.lake/build/lib/lean/" + name, "产物目录顶层只许内容根"))
    return reds, "%d 个模块都有产物" % len(ctx.content)


# ---- 第 7 步：环境层与声明锁 ----

def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"重复键：{key}")
        obj[key] = value
    return obj


def compare_lock(expect, rows):
    actual = {}
    for name, mod, statement in rows:
        payload = json.dumps(statement, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if name in actual:
            raise Fault("AUDITOR_OUTPUT", "env", f"声明名重复：{name}")
        actual[name] = (mod, hashlib.sha256(payload).hexdigest())
    reds = []
    for name in sorted(actual.keys() | expect.keys()):
        if name not in actual:
            reds.append(("LOCK_REMOVED", "formal_math/statement-lock.json:" + name, "锁定声明不在环境中"))
        else:
            mod, digest = actual[name]
            if name in expect and digest == expect[name]:
                continue
            code = "LOCK_CHANGED" if name in expect else "LOCK_UNLISTED"
            reds.append((code, "formal_math/" + mod.replace(".", "/") + ".lean:" + name, f"现算 {digest}"))
    return reds


def step_env(ctx, certificate=None):
    """certificate：派生证书文件，必须位于受信目录下；本片没有产生它的一侧（第四片），恒为 None。"""
    try:
        manifest = json.loads(read(os.path.join(ctx.audited, "lake-manifest.json")),
                              object_pairs_hook=unique_object)
        names = [p["name"] for p in manifest["packages"]]
        if ctx.lock is None:
            raise ValueError("被审提交没有 formal_math/statement-lock.json")
        expect = json.loads(blobs(ctx, [ctx.lock])[ctx.lock], object_pairs_hook=unique_object)
    except (ValueError, KeyError, TypeError) as e:
        raise Fault("INPUT", "lake-manifest.json/statement-lock.json", "无法解读：%s" % e)
    if not all(isinstance(n, str) and PACKAGE.fullmatch(n) for n in names) or not isinstance(expect, dict):
        raise Fault("INPUT", "lake-manifest.json/statement-lock.json", "包名或锁文件格式不合")
    if certificate is not None and not inside(os.path.realpath(certificate), ctx.trusted_dir):
        raise Fault("CERTIFICATE", certificate, "派生证书必须在受信目录下")
    search = [os.path.join(ctx.packages, n, ".lake", "build", "lib", "lean") for n in names]
    search.append(os.path.join(ctx.audited, ".lake", "build", "lib", "lean"))
    ctx.auditor_args = (["--derived", certificate] if certificate else []) + ctx.modules
    binds = [("--ro-bind", ctx.audited, ctx.audited), ("--ro-bind", ctx.packages, ctx.packages),
             ("--ro-bind", ctx.trusted_dir, ctx.trusted_dir)]
    env = {"LEAN_PATH": ":".join(search), "LEAN_SYSROOT": ctx.prefix}
    findings, rows = run_auditor(ctx, "env", binds, env, TIMEOUT["env"])
    locks = []
    for row in rows:
        if not (isinstance(row, list) and len(row) == 4 and row[0] == "lock" and isinstance(row[1], str) and
                row[2] in ctx.modules):
            raise Fault("AUDITOR_OUTPUT", "env", "锁行无法解读")
        locks.append(row[1:])
    if any(f[1] not in ("3", "15") for f in findings):
        raise Fault("AUDITOR_OUTPUT", "env", "发现行的门号无法解读")
    reds = [(f[4], "%s:%s" % (f[2], f[3]), f[5]) for f in findings] + compare_lock(expect, locks)
    return reds, "%d 个模块，%d 条锁行" % (len(ctx.modules), len(locks))


STEP_FUNCS = (step_precheck, step_fetch, step_auditor, step_headers, step_shape, step_build, step_env)


# ---- 入口 ----

def parse(argv):
    opts, approved = {}, False
    args = [os.fsencode(a) for a in argv]
    while args:
        a = args.pop(0)
        if a == FLAG and not approved:
            approved = True
        elif a in OPTIONS and a not in opts and args and args[0] and not args[0].startswith(b"-"):
            opts[a] = args.pop(0)
        else:
            raise Fault("USAGE", a, "用法：run.py " + USAGE)
    missing = [o for o in OPTIONS[2:] if o not in opts]
    until = opts.get(b"--until", b"7")
    if missing or not re.fullmatch(rb"[1-7]", until):
        raise Fault("USAGE", (missing or [b"--until"])[0], "用法：run.py " + USAGE)
    return opts, approved, int(until)


def prepare(argv):
    opts, approved, until = parse(argv)
    ctx = Run()
    ctx.repo, ctx.approved, ctx.until, ctx.branch = os.path.abspath(opts[b"--repo"]), approved, until, opts[b"--branch"]
    ctx.base, ctx.head = commit(ctx, opts[b"--base"]), commit(ctx, opts[b"--head"])
    ctx.bootstrap = b"--bootstrap-trusted-from" in opts
    ctx.trusted = commit(ctx, opts[b"--bootstrap-trusted-from"]) if ctx.bootstrap else ctx.base
    ctx.workdir, ctx.packages = (os.path.realpath(os.fsdecode(opts[k])) for k in (b"--workdir", b"--packages"))
    guarded = [os.path.realpath(os.fsdecode(out.strip()))
               for flag in (b"--show-toplevel", b"--absolute-git-dir", b"--git-common-dir")
               for rc, out in [git(ctx, b"rev-parse", b"--path-format=absolute", flag, ok=(0, 128))] if rc == 0]
    if any(inside(ctx.workdir, g) or inside(g, ctx.workdir) for g in guarded + [ctx.packages]):
        raise Fault("WORKDIR", ctx.workdir, "工作目录必须在仓库检出、git 目录与依赖目录之外，且互不包含")
    if not os.path.isdir(ctx.packages):
        raise Fault("PACKAGES", ctx.packages, "依赖目录不存在")
    if os.path.lexists(ctx.workdir):
        if os.path.islink(opts[b"--workdir"]) or not os.path.isdir(ctx.workdir) or os.listdir(ctx.workdir):
            raise Fault("WORKDIR", ctx.workdir, "工作目录须不存在或为空目录")
    else:
        os.mkdir(ctx.workdir, 0o700)
    return ctx


def main(argv, steps=STEP_FUNCS, start=1):
    """start 只给自测的旁路用例用（从第 2 步直接起跑）；命令行入口恒从第 1 步开始。"""
    out_err = []

    def out(*fields):
        err = emit(1, b"FM", *fields)
        if err:
            out_err.append(err)

    def fault(step, f):
        code, obj, msg = (tuple(f.args) + ("-", "-", "-"))[:3]
        emit(2, b"FM FAULT", step, code, show(obj), msg)
        return 2

    try:
        ctx = prepare(argv)
        mode = b"bootstrap" if ctx.bootstrap else b"baseline"
        out(b"MODE", mode, b"trusted=" + ctx.trusted, b"base=" + ctx.base, b"head=" + ctx.head,
            "自举模式：受信代码取自调用方指定的提交，不保证来自主干" if ctx.bootstrap else "受信代码取自基线")
        missing = [p for p in TRUSTED_CODE if object_at(ctx, ctx.trusted, p) is None]
        if missing:
            raise Fault("NO_TRUSTED_CODE", missing[0], "受信提交缺门禁代码；自举须显式给 --bootstrap-trusted-from")
        me = git(ctx, b"hash-object", b"--no-filters", b"--stdin", data=read(os.path.abspath(__file__)))[1].strip()
        if me != object_at(ctx, ctx.trusted, TRUSTED_CODE[0]):
            raise Fault("RUNNER_MISMATCH", me, "正在运行的 run.py 不是受信提交里的那一份")
        out(b"RUNNER", b"blob=" + me, b"from=" + ctx.trusted + b":" + TRUSTED_CODE[0])
    except Fault as f:
        return fault("prepare", f)
    except Exception as e:  # 意外一律归入无法判定
        return fault("prepare", Fault("INTERNAL", "-", "%s: %s" % (type(e).__name__, e)))
    for n, (name, step) in enumerate(zip(STEPS, steps), 1):
        if n < start:
            continue
        if n > ctx.until:
            out(b"RESULT PARTIAL", "只跑到第 %d 步，没有做完整判定" % ctx.until)
            return 2
        began = time.monotonic()
        try:
            reds, note = step(ctx)
        except Fault as f:
            out(b"STEP", n, name, b"FAULT", "%.1fs" % (time.monotonic() - began))
            return fault(name, f)
        except Exception as e:
            out(b"STEP", n, name, b"FAULT", "%.1fs" % (time.monotonic() - began))
            return fault(name, Fault("INTERNAL", "-", "%s: %s" % (type(e).__name__, e)))
        for code, obj, msg in sorted(set(reds), key=lambda r: (r[0], show(r[1]), r[2])):
            out(b"RED", name, code, show(obj), msg)
        out(b"STEP", n, name, b"RED" if reds else b"GREEN", "%.1fs" % (time.monotonic() - began), note)
        if reds:
            out(b"RESULT RED", "第 %d 步 %s 判红，后面的步骤没有跑" % (n, name))
            return 1
    out(b"RESULT GREEN", "七步全绿（第 5 步源码形状未安装）")
    if out_err:
        emit(2, b"FM FAULT output OUTPUT stdout", "输出写不出：%s" % out_err[0])
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
