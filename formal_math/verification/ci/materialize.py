#!/usr/bin/env python3
"""#2315（FM-06）辅助：只从 git 原始对象取料与校验 comparator 配置，绝不检出或读 PR 工作树。

必须以 `python3 -I` 运行。规则与 run.py 的取料步一致：
  - 只用 `ls-tree -r -z` 与 `cat-file --batch` 取 100644 blob 原始字节，不受 .gitattributes 影响；
  - 写文件用 O_CREAT|O_EXCL|O_NOFOLLOW、固定模式 0644，目录 0755；
  - JSON 严格解析：合法 UTF-8、拒重复键、拒 NaN/Infinity、拒孤立代理项。

子命令：
  configs   --repo R --base C --out DIR
            仅写出基线的 lakefile.toml / lake-manifest.json / lean-toolchain，并校验 require 与 manifest 钉选一致。
  audited   --repo R --base C --head H --out DIR
            写出基线三配置 + 被审提交全部内容 .lean 文件，并建空 .lake/packages 挂载点。
  challenge --repo R --base C --head H --out DIR
            写出基线三配置 + 被审提交的声明/挑战文件（仅 Chan/Defs、Chan/Hypotheses、
            Chan/Audit/Literal、ChanChallenge；物理上不含任何证明目录），并建空 .lake/packages。
  blob      --repo R --rev C --path P --out FILE
            从指定提交取出单个 100644 blob（用于从受信提交取出 precheck.py / run.py / comparator.json）。
  validate-comparator-config --file PATH [--allow-def-names] [--allow-sample-modules]
            按门 5 规则校验 comparator.json，并按固定键值对输出字段。
"""
import sys

if not sys.flags.isolated:
    import posix
    try:
        posix.write(2, b"FM_CI FAULT materialize.py MUST run with python3 -I\n")
    except BaseException:  # noqa: BLE001
        pass
    posix._exit(2)

import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import tomllib  # noqa: E402

CONFIGS = (b"lakefile.toml", b"lake-manifest.json", b"lean-toolchain")
CONTENT_ROOTS = (b"Chan", b"ChanTest", b"ChanChallenge", b"ChanDyn", b"ChanExplore")
CONTENT_TOP = (b"Chan.lean", b"ChanExplore.lean")
CHALLENGE_ALLOWED_PREFIXES = (
    b"Chan/Defs/",
    b"Chan/Hypotheses/",
    b"Chan/Audit/Literal/",
    b"ChanChallenge/",
)
CHALLENGE_MODULE_PREFIXES = (
    "ChanChallenge",
    "Chan.Defs",
    "Chan.Hypotheses",
    "Chan.Audit.Literal",
)
STANDARD_AXIOMS = {"propext", "Quot.sound", "Classical.choice"}
PRIMITIVE_TARGETS = (
    "Nat.add", "Nat.sub", "Nat.mul", "Nat.pow", "Nat.gcd", "Nat.div", "Nat.mod",
    "Nat.beq", "Nat.ble", "Nat.land", "Nat.lor", "Nat.xor", "Nat.shiftLeft", "Nat.shiftRight",
    "String.ofList", "Char.ofNat", "List", "eagerReduce", "Nat", "String", "String.mk",
    "Char", "optParam", "autoParam", "semiOutParam", "outParam",
)
QUOT_TARGETS = ("Quot", "Quot.mk", "Quot.lift", "Quot.ind")
MODULE_SEG = re.compile(rb"[A-Za-z][A-Za-z0-9_]*")
MOD_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*")
DECL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*")
PACKAGE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*")
OID = re.compile(rb"[0-9a-f]{40}|[0-9a-f]{64}")
TREE_ENTRY = re.compile(rb"([0-7]{6}) (blob|tree|commit) ([0-9a-f]{40}|[0-9a-f]{64})\t(.+)", re.S)
GIT_ENV = {
    "PATH": os.environ.get("PATH", os.defpath),
    "LC_ALL": "C",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_GRAFT_FILE": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
}


class Fail(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def git(repo, *args, data=None, ok=(0,)):
    argv = [b"git", b"-C", repo, b"-c", b"core.hooksPath=/dev/null",
            b"-c", b"advice.graftFileDeprecated=false", *args]
    p = subprocess.run(argv, env=GIT_ENV, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode not in ok:
        err = p.stderr.decode("utf-8", "replace").strip()
        raise Fail(2, f"git {args[0].decode()} 退出 {p.returncode}: {err}")
    return p.returncode, p.stdout


def resolve_commit(repo, rev):
    rc, out = git(repo, b"rev-parse", b"--verify", b"--quiet", b"--end-of-options", rev + b"^{commit}", ok=(0, 1))
    oid = out.strip()
    if rc or not OID.fullmatch(oid):
        raise Fail(2, f"解析不出提交: {rev.decode('utf-8', 'replace')}")
    return oid


def ls_tree(repo, rev, path):
    rc, out = git(repo, b"ls-tree", b"-r", b"-z", b"--end-of-options", rev + b":" + path, ok=(0, 128))
    if rc != 0:
        raise Fail(2, f"提交 {rev.decode()} 缺少目录 {path.decode('utf-8', 'replace')}")
    entries = []
    for rec in out.split(b"\0")[:-1]:
        m = TREE_ENTRY.fullmatch(rec)
        if not m:
            raise Fail(2, "ls-tree 输出无法解读")
        mode, kind, oid, rel = m.groups()
        entries.append((rel, mode, kind, oid))
    return entries


def read_blobs(repo, oids):
    uniq = sorted(set(oids))
    if not uniq:
        return {}
    out = git(repo, b"cat-file", b"--batch", data=b"".join(o + b"\n" for o in uniq))[1]
    result, pos = {}, 0
    for oid in uniq:
        end = out.find(b"\n", pos)
        head = out[pos:end].split(b" ") if end >= 0 else []
        if len(head) != 3 or head[0] != oid or head[1] != b"blob" or not head[2].isdigit():
            raise Fail(2, f"对象不是 blob 或输出无法解读: {oid.decode()}")
        size = int(head[2])
        result[oid], pos = out[end + 1:end + 1 + size], end + 2 + size
        if out[pos - 1:pos] != b"\n":
            raise Fail(2, "cat-file 输出长度不符")
    if pos != len(out):
        raise Fail(2, "cat-file 输出有多余字节")
    return result


def strict_json(data, label):
    def unique_object(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise ValueError(f"重复键 {k}")
            obj[k] = v
        return obj

    def reject_constant(name):
        raise ValueError(f"非有限数 {name}")

    def no_surrogates(v):
        if isinstance(v, str):
            return not any(0xD800 <= ord(c) <= 0xDFFF for c in v)
        if isinstance(v, list):
            return all(no_surrogates(x) for x in v)
        if isinstance(v, dict):
            return all(no_surrogates(k) and no_surrogates(x) for k, x in v.items())
        return True

    try:
        val = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        raise Fail(1, f"{label}: 严格 JSON 解析失败: {e}")
    if not no_surrogates(val):
        raise Fail(1, f"{label}: JSON 含孤立代理项")
    return val


def ensure_empty_dir(path):
    if os.path.islink(path):
        raise Fail(2, f"输出目录不能是符号链接: {path}")
    if os.path.exists(path):
        if not os.path.isdir(path) or os.listdir(path):
            raise Fail(2, f"输出目录必须不存在或为空目录: {path}")
    else:
        os.mkdir(path, 0o755)
        os.chmod(path, 0o755)


def write_files(root, files):
    made = set()
    for rel, data in files:
        parts = rel.split("/")
        for i in range(1, len(parts)):
            d = os.path.join(root, *parts[:i])
            if d not in made:
                if os.path.islink(d):
                    raise Fail(2, f"遇到符号链接目录: {d}")
                if not os.path.isdir(d):
                    os.mkdir(d, 0o755)
                    os.chmod(d, 0o755)
                made.add(d)
        dst = os.path.join(root, *parts)
        fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        try:
            os.fchmod(fd, 0o644)
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
        finally:
            os.close(fd)


def fetch_base_configs(repo, base_oid):
    base_tree = ls_tree(repo, base_oid, b"formal_math")
    configs = []
    for name in CONFIGS:
        hits = [e for e in base_tree if e[0] == name]
        if len(hits) != 1 or hits[0][1] != b"100644" or hits[0][2] != b"blob":
            raise Fail(2, f"基线缺少普通文件 formal_math/{name.decode()}")
        configs.append((name.decode("ascii"), hits[0][3]))
    return configs


def verify_config_pins(lakefile_bytes, manifest_bytes):
    try:
        pkg = tomllib.loads(lakefile_bytes.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise Fail(2, f"基线 lakefile.toml 无法解析: {e}")
    manifest = strict_json(manifest_bytes, "formal_math/lake-manifest.json")
    if not isinstance(manifest, dict):
        raise Fail(2, "formal_math/lake-manifest.json 顶层须为对象")
    for key, want in (("packagesDir", ".lake/packages"), ("lakeDir", ".lake")):
        if manifest.get(key, want) != want:
            raise Fail(2, f"formal_math/lake-manifest.json:{key} 须为 {want}")
    pkgs = manifest.get("packages")
    if not isinstance(pkgs, list):
        raise Fail(2, "formal_math/lake-manifest.json 缺少 packages 列表")
    direct = {}
    for p in pkgs:
        if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not PACKAGE_NAME.fullmatch(p["name"]):
            raise Fail(2, "formal_math/lake-manifest.json 包项格式不合")
        if not p.get("inherited"):
            direct[p["name"]] = p
    for req in pkg.get("require", []):
        if not isinstance(req, dict) or req.get("name") not in direct:
            raise Fail(2, f"基线 lakefile.toml 含 manifest 未钉选的直接依赖: {req}")
        entry = direct[req["name"]]
        if req.get("git") != entry.get("url") or req.get("rev") != entry.get("inputRev"):
            raise Fail(2, f"基线 lakefile.toml 依赖 {req['name']} 的 git/rev 与 manifest 不一致")
    return [p["name"] for p in pkgs]


def select_content(repo, head_oid, challenge_only=False):
    head_tree = ls_tree(repo, head_oid, b"formal_math")
    content = []
    for rel, mode, kind, oid in head_tree:
        parts = rel.split(b"/")
        is_content = (parts[0] in CONTENT_ROOTS and len(parts) > 1) or (rel.endswith(b".lean") and len(parts) == 1)
        if not is_content:
            continue
        stems = parts[:-1] + [parts[-1][:-5] if parts[-1].endswith(b".lean") else b""]
        if mode != b"100644" or kind != b"blob" or not all(MODULE_SEG.fullmatch(s) for s in stems) or \
                (len(parts) == 1 and rel not in CONTENT_TOP):
            raise Fail(1, f"内容文件路径或模式不合规范: formal_math/{rel.decode('utf-8', 'replace')}")
        if challenge_only and not any(rel.startswith(pfx) for pfx in CHALLENGE_ALLOWED_PREFIXES):
            continue
        content.append((rel.decode("ascii"), oid))
    if not content:
        raise Fail(2, "被审提交没有符合范围的内容 .lean 文件")
    return content


def cmd_configs(opts):
    repo = os.fsencode(os.path.abspath(opts["--repo"]))
    base_oid = resolve_commit(repo, os.fsencode(opts["--base"]))
    out_dir = opts["--out"]
    configs = fetch_base_configs(repo, base_oid)
    data = read_blobs(repo, [oid for _, oid in configs])
    by_name = {name: data[oid] for name, oid in configs}
    pkg_names = verify_config_pins(by_name["lakefile.toml"], by_name["lake-manifest.json"])
    ensure_empty_dir(out_dir)
    write_files(out_dir, [(name, by_name[name]) for name, _ in configs])
    for name in pkg_names:
        print(f"PACKAGE {name}")


def cmd_workspace(opts, challenge_only):
    repo = os.fsencode(os.path.abspath(opts["--repo"]))
    base_oid = resolve_commit(repo, os.fsencode(opts["--base"]))
    head_oid = resolve_commit(repo, os.fsencode(opts["--head"]))
    out_dir = opts["--out"]
    configs = fetch_base_configs(repo, base_oid)
    content = select_content(repo, head_oid, challenge_only=challenge_only)
    data = read_blobs(repo, [oid for _, oid in configs + content])
    by_name = {name: data[oid] for name, oid in configs}
    pkg_names = verify_config_pins(by_name["lakefile.toml"], by_name["lake-manifest.json"])
    for rel, oid in content:
        try:
            data[oid].decode("utf-8")
        except UnicodeDecodeError:
            raise Fail(1, f"内容文件不是合法 UTF-8: formal_math/{rel}")
    ensure_empty_dir(out_dir)
    write_files(out_dir, [(rel, data[oid]) for rel, oid in configs + content])
    lake_dir = os.path.join(out_dir, ".lake")
    os.mkdir(lake_dir, 0o755)
    os.chmod(lake_dir, 0o755)
    pkg_dir = os.path.join(lake_dir, "packages")
    os.mkdir(pkg_dir, 0o755)
    os.chmod(pkg_dir, 0o755)
    for name in pkg_names:
        print(f"PACKAGE {name}")


def cmd_blob(opts):
    repo = os.fsencode(os.path.abspath(opts["--repo"]))
    rev_oid = resolve_commit(repo, os.fsencode(opts["--rev"]))
    rel_path = os.fsencode(opts["--path"])
    out_file = opts["--out"]
    rc, out = git(repo, b"ls-tree", b"-z", b"--end-of-options", rev_oid, b"--", rel_path, ok=(0, 1))
    recs = [r for r in out.split(b"\0") if r]
    if rc != 0 or len(recs) != 1:
        raise Fail(2, f"提交 {rev_oid.decode()} 缺少文件 {opts['--path']}")
    m = TREE_ENTRY.fullmatch(recs[0])
    if not m:
        raise Fail(2, "ls-tree 条目无法解读")
    mode, kind, oid, found_path = m.groups()
    if found_path != rel_path or mode != b"100644" or kind != b"blob":
        raise Fail(2, f"路径 {opts['--path']} 不是 100644 blob（mode={mode.decode()} kind={kind.decode()}）")
    raw = read_blobs(repo, [oid])[oid]
    parent = os.path.dirname(os.path.abspath(out_file))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, mode=0o755, exist_ok=True)
    fd = os.open(out_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        os.fchmod(fd, 0o644)
        view = memoryview(raw)
        while view:
            view = view[os.write(fd, view):]
    finally:
        os.close(fd)
    print(oid.decode("ascii"))


def cmd_validate_comparator(opts, flags):
    path = opts["--file"]
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise Fail(2, f"读不到 comparator 配置 {path}: {e}")
    cfg = strict_json(raw, path)
    if not isinstance(cfg, dict):
        raise Fail(1, "门 5：comparator 配置顶层须为 JSON 对象")
    allow_def = "--allow-def-names" in flags
    allow_sample = "--allow-sample-modules" in flags

    def_names = cfg.get("definition_names")
    if def_names is not None:
        if not isinstance(def_names, list) or not all(isinstance(x, str) for x in def_names):
            raise Fail(1, "门 5：definition_names 须为字符串数组")
        if def_names and not allow_def:
            raise Fail(1, f"门 5：comparator.json 的 definition_names 必须为空，现有 {def_names}")

    chal = cfg.get("challenge_module")
    sol = cfg.get("solution_module")
    if not isinstance(chal, str) or not MOD_NAME.fullmatch(chal):
        raise Fail(1, f"门 5：challenge_module 非法: {chal!r}")
    if not isinstance(sol, str) or not MOD_NAME.fullmatch(sol):
        raise Fail(1, f"门 5：solution_module 非法: {sol!r}")
    if chal == sol:
        raise Fail(1, "门 5：challenge_module 与 solution_module 不得相同")
    if not allow_sample and not any(chal == p or chal.startswith(p + ".") for p in CHALLENGE_MODULE_PREFIXES):
        raise Fail(1, f"门 5：challenge_module ({chal}) 必须落在声明/挑战目录（{', '.join(CHALLENGE_MODULE_PREFIXES)}）")

    thms = cfg.get("theorem_names")
    if not isinstance(thms, list) or not thms or not all(isinstance(x, str) and DECL_NAME.fullmatch(x) for x in thms):
        raise Fail(1, "门 5：theorem_names 须为非空合法声明名数组")

    axioms = cfg.get("permitted_axioms")
    if not isinstance(axioms, list) or not all(isinstance(x, str) for x in axioms):
        raise Fail(1, "门 5：permitted_axioms 须为字符串数组")
    bad_axioms = [a for a in axioms if a not in STANDARD_AXIOMS]
    if bad_axioms:
        raise Fail(1, f"门 5：permitted_axioms 含标准三公理之外的公理: {bad_axioms}")

    if cfg.get("enable_nanoda"):
        raise Fail(1, "门 5：配置中不许开启 enable_nanoda（外部检查器由 --paranoid 开关控制）")
    ext = cfg.get("external_kernels")
    if ext is not None and ext != {}:
        raise Fail(1, "门 5：配置中不许指定 external_kernels")

    print(f"CHALLENGE_MODULE={chal}")
    print(f"SOLUTION_MODULE={sol}")
    targets = []
    if "Quot.sound" in axioms:
        targets.extend(QUOT_TARGETS)
    targets.extend(thms)
    targets.extend(axioms)
    targets.extend(PRIMITIVE_TARGETS)
    if def_names:
        targets.extend(def_names)
    seen = set()
    for t in targets:
        if t not in seen:
            seen.add(t)
            print(f"EXPORT_TARGET={t}")


def parse_cli(argv):
    if not argv:
        raise Fail(2, "缺少子命令（configs|audited|challenge|blob|validate-comparator-config）")
    sub, rest = argv[0], argv[1:]
    opts, flags = {}, set()
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("--allow-def-names", "--allow-sample-modules"):
            flags.add(a)
            i += 1
        elif a in ("--repo", "--base", "--head", "--rev", "--path", "--out", "--file"):
            if i + 1 >= len(rest) or a in opts:
                raise Fail(2, f"参数错误: {a}")
            opts[a] = rest[i + 1]
            i += 2
        else:
            raise Fail(2, f"未知参数: {a}")
    return sub, opts, flags


def main(argv):
    try:
        sub, opts, flags = parse_cli(argv)
        if sub == "configs":
            for k in ("--repo", "--base", "--out"):
                if k not in opts:
                    raise Fail(2, f"configs 缺少 {k}")
            cmd_configs(opts)
        elif sub == "audited":
            for k in ("--repo", "--base", "--head", "--out"):
                if k not in opts:
                    raise Fail(2, f"audited 缺少 {k}")
            cmd_workspace(opts, challenge_only=False)
        elif sub == "challenge":
            for k in ("--repo", "--base", "--head", "--out"):
                if k not in opts:
                    raise Fail(2, f"challenge 缺少 {k}")
            cmd_workspace(opts, challenge_only=True)
        elif sub == "blob":
            for k in ("--repo", "--rev", "--path", "--out"):
                if k not in opts:
                    raise Fail(2, f"blob 缺少 {k}")
            cmd_blob(opts)
        elif sub == "validate-comparator-config":
            if "--file" not in opts:
                raise Fail(2, "validate-comparator-config 缺少 --file")
            cmd_validate_comparator(opts, flags)
        else:
            raise Fail(2, f"未知子命令: {sub}")
        return 0
    except Fail as e:
        sys.stderr.write(f"FM_CI MATERIALIZE ERROR ({e.code}): {e.msg}\n")
        return e.code
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"FM_CI MATERIALIZE INTERNAL: {type(e).__name__}: {e}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
