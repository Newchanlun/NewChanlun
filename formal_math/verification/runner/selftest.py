#!/usr/bin/env python3
"""runner/run.py 的自测：现造小 git 仓库，经新入口跑整条流水线，断言整次运行的退出码、红码集合与输出协议。

用法：selftest.py --packages <依赖目录> [--jobs N] [--only 子串] [--cases S1,E2,…] [--skip-corpus] [--discover]
      selftest.py --packages <依赖目录> --mutants [--jobs N]
- 骨架用例（S*、E*）：见 README「自测」。每次运行都另核对输出协议（`protocol()`）。
- 语料用例：`fixtures.tsv` 里每个标了期望的旧夹具。`--discover` 只打印实测结果（同表格式），不断言。
- `--mutants`：在临时副本里逐一改弱运行脚本或审计程序，每种弱化都必须让骨架自测失败；先断言未改弱的副本全过。
共享依赖目录只读使用：凡是要验证「依赖目录写不进」的用例都用临时目录里自建的假依赖目录（lite 基线，无依赖包）。
须先 `source scripts/fm_env.sh`，并整体包在 `flock <lean.lock> guard.sh` 里跑。"""
import json
import os
import signal
import stat
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
VERIFICATION = os.path.dirname(HERE)
FM = os.path.dirname(VERIFICATION)
RUN = os.path.join(HERE, "run.py")
ROOTS = ("Chan", "ChanTest", "ChanChallenge", "ChanDyn", "ChanExplore")
CONFIG_NAMES = ("lakefile.toml", "lake-manifest.json", "lean-toolchain")
CANARY = "FM_SELFTEST_CANARY"
GIT_ID = {"GIT_AUTHOR_NAME": "FM 自测", "GIT_AUTHOR_EMAIL": "fm-fixture@example.invalid",
          "GIT_COMMITTER_NAME": "FM 自测", "GIT_COMMITTER_EMAIL": "fm-fixture@example.invalid",
          "GIT_AUTHOR_DATE": "2026-11-26T00:00:00Z", "GIT_COMMITTER_DATE": "2026-11-26T00:00:00Z",
          "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "PATH": os.environ["PATH"]}
M = "module\n\npublic section\n\n"

DRIVER = r'''
import importlib.util, json, os, re, sys
spec = importlib.util.spec_from_file_location("fm_run", sys.argv[1])
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)
mode, argv = sys.argv[2], sys.argv[3:]
orig = run.sandbox
PROBE = r"""
echo "NET:$(tail -n +3 /proc/net/dev | cut -d: -f1 | tr -d ' ' | sort | tr '\n' ,)"
echo "ENV:$(env | cut -d= -f1 | sort | tr '\n' ,)"
while [ $# -gt 0 ]; do
  case "$1" in
    see) test -e "$3" && echo "SEE:$2" ;;
    write) if (echo x > "$3") 2>/dev/null; then echo "WROTE:$2"; rm -f "$3"; fi ;;
  esac
  shift 3
done
"""

def probe(ctx, step, binds, env, cwd):
    cfg = json.loads(os.environ["FM_SELFTEST_PROBE"])
    pkgs = ctx.audited + "/.lake/packages" if step == "build" else ctx.packages
    args = ["see", "host", cfg["host"], "see", "repo", cfg["repo"],
            "see", "trusted", ctx.trusted_dir + "/verification/runner/run.py",
            "write", "src", ctx.audited + "/probe-src", "write", "lake", ctx.audited + "/.lake/probe-lake",
            "write", "packages", pkgs + "/probe-pkg", "write", "trusted", ctx.trusted_dir + "/probe-trusted"]
    p = orig(ctx, ["/bin/sh", "-c", PROBE, "probe", *args], binds, env, cwd, 60, "PROBE", "probe")
    with open(cfg["out"], "a") as f:
        f.write(json.dumps({"step": step, "lines": p.stdout.decode(errors="replace").splitlines()}) + "\n")

def patched(ctx, cmd, binds, env, cwd, *a, **k):
    if mode == "probe" and (cmd[:2] == ["lake", "build"] or cmd[0] == getattr(ctx, "auditor", None) and
                            cmd[1] in ("env", "shape")):
        probe(ctx, "build" if cmd[0] == "lake" else cmd[1], binds, env, cwd)
    if mode.startswith("sig-") and cmd[0] == getattr(ctx, "auditor", None) and cmd[1] == mode[4:]:
        return orig(ctx, ["/bin/sh", "-c", "kill -KILL $$"], binds, env, cwd, *a, **k)
    p = orig(ctx, cmd, binds, env, cwd, *a, **k)
    if cmd[0] != getattr(ctx, "auditor", None):
        return p
    lines = p.stdout.split(b"\n")[:-1]
    if mode == "env-count" and cmd[1] == "env":
        lines[-1] = lines[-1].replace(b",%d]" % len(ctx.modules), b",%d]" % (len(ctx.modules) + 1))
    elif mode == "headers-garbage" and cmd[1] == "headers":
        lines.insert(0, b"GATE15 RED forged")
    elif mode == "headers-drop" and cmd[1] == "headers":
        lines = lines[1:]
    elif mode == "env-verdict" and cmd[1] == "env":
        lines[-1] = lines[-1].replace(b'"green"', b'"red"')
    elif mode == "env-exit" and cmd[1] == "env":
        p.returncode = 1
    elif mode == "shape-count" and cmd[1] == "shape":
        lines[-1] = re.sub(rb",(\d+)\]$", lambda m: b",%d]" % (int(m[1]) + 1), lines[-1])
    elif mode == "shape-drop" and cmd[1] == "shape":
        del lines[[l.startswith(b'["file"') for l in lines].index(True)]
    elif mode == "plan-garbage" and cmd[1] == "shape-plan":
        lines.insert(0, b'["plan","x","y",[]]')
    elif mode == "shape-noreds" and cmd[1] == "shape":
        # 去掉形状门的发现（模拟形状门放行），派生行原样保留，用来单测第 7 步按证书位置比对。
        lines = [l for l in lines if not l.startswith(b'["finding"')]
        lines[-1] = lines[-1].replace(b'"red"', b'"green"')
        p.returncode = 0
    p.stdout = b"".join(l + b"\n" for l in lines)
    return p
run.sandbox = patched
if mode == "timeout":
    run.TIMEOUT["build"] = 30
if mode == "late-signal":
    # 结果行写出之后、主路径返回之前给自己发 SIGTERM：处理函数里的 finish() 不得再写第二行结果行。
    import signal
    real_finish, sent = run.finish, []
    def finish(*a):
        ok = real_finish(*a)
        if not sent:
            sent.append(1)
            os.kill(os.getpid(), signal.SIGTERM)
        return ok
    run.finish = finish
steps = list(run.STEP_FUNCS)
if os.environ.get("FM_SELFTEST_SKIP_SHAPE"):
    # 骨架用例里要让被审代码在构建期执行（#eval、meta initialize 等），这里跳过第 5 步；派生证书为空。
    def skip_shape(ctx):
        # 值为 nocert 时连派生凭证也不写（S32）；othercert 时把凭证指向受信目录里另一个存在的文件（S33）；
        # 否则有意写一份空凭证，第 7 步照常拿到它。
        if os.environ["FM_SELFTEST_SKIP_SHAPE"] == "othercert":
            ctx.certificate = os.path.join(ctx.trusted_dir, "verification", "runner", "run.py")
        elif os.environ["FM_SELFTEST_SKIP_SHAPE"] != "nocert":
            ctx.certificate = os.path.join(ctx.trusted_dir, "derived.json")
            run.write_files(ctx.trusted_dir, [("derived.json", b"[]")])
        return [], "自测旁路：跳过源码形状"
    steps[4] = skip_shape
if mode.startswith("warm:"):
    # 语料用例复用预编译的审计程序产物：源码逐字相同，第 3 步的 lake build 核对哈希后不重建。
    import shutil
    def warm(ctx, real=steps[2]):
        shutil.copytree(mode[5:], ctx.trusted_dir + "/verification/auditor/.lake", symlinks=True)
        return real(ctx)
    steps[2] = warm
sys.exit(run.main(argv, steps=steps, start=2 if mode == "bypass" else 1))
'''


def read(path):
    with open(path, "rb") as f:
        return f.read()


def rmtree(path):
    """被审构建可能留下属主不可列出的目录（模式 0111），先放开属主权限再删。"""
    if os.path.lexists(path):
        subprocess.run(["chmod", "-R", "u+rwx", path], capture_output=True)
        shutil.rmtree(path, ignore_errors=True)


class Repo:
    """只用底层命令造提交，不检出，所以 .gitattributes 与过滤器碰不到自测的输入。"""

    def __init__(self, path):
        self.path = path
        os.makedirs(path)
        self.git("init", "-q", "-b", "main")

    def git(self, *args, data=None):
        p = subprocess.run(["git", "-C", self.path, *args], input=data, capture_output=True, env=GIT_ID)
        if p.returncode:
            raise RuntimeError("git %s: %s" % (args[0], p.stderr.decode(errors="replace")))
        return p.stdout

    def commit(self, files, parent=None, raw=None):
        """files：{相对仓库根的路径: 字节}；raw：{目录路径: 树对象原始字节}，用来造畸形树；返回提交对象名。"""
        tree = {}
        for path, data in files.items():
            node = tree
            *dirs, name = path.split("/")
            for d in dirs:
                node = node.setdefault(d, {})
            node[name] = self.git("hash-object", "-w", "--no-filters", "--stdin", data=data).strip()

        def mktree(node, path=""):
            if path in (raw or {}):
                return self.git("hash-object", "-t", "tree", "--literally", "-w", "--stdin", data=raw[path]).strip()
            rows = b""
            for name, value in sorted(node.items()):
                kind, mode = ("tree", "040000") if isinstance(value, dict) else ("blob", "100644")
                oid = mktree(value, path + "/" + name if path else name) if isinstance(value, dict) else value
                rows += b"%s %s %s\t%s\0" % (mode.encode(), kind.encode(), oid, name.encode())
            return self.git("mktree", "-z", data=rows).strip()

        args = ["commit-tree", mktree(tree).decode(), "-m", "自测"] + (["-p", parent] if parent else [])
        return self.git(*args).strip().decode()


def entry(mode, name, oid):
    """树对象里的一条原始条目。"""
    return b"%s %s\0" % (mode, name) + bytes.fromhex(oid.decode() if isinstance(oid, bytes) else oid)


def lakefile(files, require=True):
    """按提交里实有的内容根生成构建配置：根模块文件进 roots 与 globs，子目录进 globs（Lake 的 glob 要求目录存在）。"""
    libs = []
    for r in ROOTS:
        has_file, has_dir = "formal_math/%s.lean" % r in files, any(p.startswith("formal_math/%s/" % r) for p in files)
        if has_file or has_dir:
            libs.append((r, [r] if has_file else [], ([r] if has_file else []) + ([r + ".+"] if has_dir else [])))
    quote = lambda xs: ", ".join('"%s"' % x for x in xs)
    out = 'name = "fixture"\ndefaultTargets = [%s]\n\n' % quote(r for r, _, _ in libs)
    out += '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\nlinter.unusedVariables = true\n'
    if require:
        out += ('\n[[require]]\nname = "mathlib"\ngit = "https://github.com/leanprover-community/mathlib4.git"\n'
                'rev = "v4.36.0"\n')
    for r, roots, globs in libs:
        out += '\n[[lean_lib]]\nname = "%s"\nroots = [%s]\nglobs = [%s]\n' % (r, quote(roots), quote(globs))
    return out.encode()


LITE_MANIFEST = (b'{"version": "1.3.0",\n "packagesDir": ".lake/packages",\n "packages": [],\n "name": "fixture",\n'
                 b' "lakeDir": ".lake",\n "fixedToolchain": false}\n')


def trusted_files():
    files = {}
    for sub in ("runner", "precheck", "auditor"):
        top = os.path.join(VERIFICATION, sub)
        for d, dirs, names in os.walk(top):
            dirs[:] = [x for x in dirs if x not in (".lake", "__pycache__")]
            for n in names:
                if n.endswith(".pyc"):
                    continue
                full = os.path.join(d, n)
                files["formal_math/verification/" + os.path.relpath(full, VERIFICATION)] = read(full)
    return files


def template(extra=None, gate=True, placeholders=True, lite=False, roots=ROOTS):
    """lite：没有依赖包的基线（清单为空、配置不 require），配合假依赖目录用，不碰共享依赖目录。"""
    files = trusted_files() if gate else {}
    files.update({
        "formal_math/lean-toolchain": read(os.path.join(FM, "lean-toolchain")),
        "formal_math/lake-manifest.json": LITE_MANIFEST if lite else read(os.path.join(FM, "lake-manifest.json")),
        "formal_math/Chan.lean": b"module\n",
        "formal_math/ChanTest/Probe.lean": read(os.path.join(FM, "ChanTest", "Probe.lean")),
        "formal_math/statement-lock.json": b"{}\n",
    })
    if placeholders:
        for r in ("Chan", "ChanChallenge", "ChanDyn", "ChanExplore"):
            if r in roots:
                files["formal_math/%s/Base.lean" % r] = b"module\n"
    files.update(extra or {})
    files["formal_math/lakefile.toml"] = lakefile(files, require=not lite)
    return files


class Suite:
    def __init__(self, tmp, packages, warm=True):
        self.tmp, self.packages = tmp, packages
        self.fake_packages = os.path.join(tmp, "fake-packages")
        os.makedirs(self.fake_packages)
        self.host_canary = os.path.join(tmp, "host-canary")
        open(self.host_canary, "w").close()
        self.repo = Repo(os.path.join(tmp, "仓库 repo"))
        self.base_files = template()
        self.base = self.repo.commit(self.base_files)
        self.lite_files = template(lite=True)
        self.lite_base = self.repo.commit(self.lite_files)
        self.counter = 0
        self.warm = self.warm_auditor() if warm else None

    def warm_auditor(self):
        """语料用例共用的审计程序预编译产物；骨架用例每次都在受信目录里从头构建。"""
        pkg = os.path.join(self.tmp, "warm-auditor")
        shutil.copytree(os.path.join(VERIFICATION, "auditor"), pkg, ignore=shutil.ignore_patterns(".lake"))
        prefix = subprocess.run(["lean", "--print-prefix"], cwd=pkg, capture_output=True, text=True).stdout.strip()
        build = subprocess.run([os.path.join(prefix, "bin", "lake"), "build"], cwd=pkg, capture_output=True)
        if build.returncode:
            raise RuntimeError("预编译审计程序失败：" + build.stdout.decode(errors="replace"))
        return os.path.join(pkg, ".lake")

    def workdir(self, name):
        self.counter += 1
        return os.path.join(self.tmp, "w%03d-%s" % (self.counter, re.sub(r"[^A-Za-z0-9_-]", "_", name)[:60]))

    def lite(self, extra):
        return self.repo.commit({**self.lite_files, **extra}, self.lite_base)

    def run(self, name, head, branch="proof/selftest", base=None, extra=(), mode=None, keep=False, workdir=None,
            repo=None, lite=False, env=None, argv=None, umask=None, skip_shape=False):
        """skip_shape：经驱动脚本跳过第 5 步（派生证书为空），给要让被审代码在构建期执行的骨架用例用。"""
        work = workdir or self.workdir(name)
        if skip_shape:
            mode, env = mode or "plain", {**(env or {}), "FM_SELFTEST_SKIP_SHAPE": "1"}
        if argv is None:
            argv = ["--repo", (repo or self.repo).path, "--base", base or (self.lite_base if lite else self.base),
                    "--head", head, "--branch", branch, "--workdir", work,
                    "--packages", self.fake_packages if lite else self.packages, *extra]
        cmd = [sys.executable, "-I", RUN, *argv] if mode is None else \
            [sys.executable, "-I", os.path.join(self.tmp, "driver.py"), RUN, mode, *argv]
        p = subprocess.run(cmd, capture_output=True, env={"PATH": os.environ["PATH"], CANARY: "leak-canary",
                                                          "HOME": os.environ.get("HOME", "/"), **(env or {})},
                           preexec_fn=None if umask is None else (lambda: os.umask(umask)))
        res = parse_result(p)
        res["work"] = work
        if not keep:
            rmtree(work)
        return res


def parse_result(p):
    out, err = p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    reds = {line.split(" ")[3] for line in out.splitlines() if line.startswith("FM RED ")}
    steps = re.findall(r"^FM STEP (\d) (\S+) (\S+)", out, re.M)
    faults = re.findall(r"^FM FAULT \S+ (\S+)", err, re.M)
    pairs = {tuple(line.split(" ")[3:5]) for line in out.splitlines() if line.startswith("FM RED ")}
    return dict(rc=p.returncode, reds=reds, steps=steps, faults=faults, out=out, err=err, pairs=pairs,
                out_b=p.stdout, err_b=p.stderr)


def printable(line):
    return all(c == " " or 0x21 <= ord(c) < 0x7F or ord(c) >= 0x80 and unicodedata.category(c)[0] in "LNPS"
               for c in line)


def protocol(res):
    """输出协议：两路都是合法 UTF-8；每行只含可见字符与空格；标准输出只有 MODE、RUNNER、RED、STEP、RESULT 行，
    恰好一行 RESULT 且在最后，状态与退出码一致；标准错误只有 FAULT、LOG 行。返回问题描述，没有问题返回空串。"""
    try:
        out, err = res["out_b"].decode("utf-8"), res["err_b"].decode("utf-8")
    except UnicodeDecodeError:
        return "输出不是合法 UTF-8"
    if not out.endswith("\n") or err and not err.endswith("\n"):
        return "输出没有以换行结尾"
    lines, elines = out.split("\n")[:-1], err.split("\n")[:-1] if err else []
    for line in lines:
        if not re.match(r"FM (MODE|RUNNER|RED|STEP|RESULT) ", line) or not printable(line):
            return "标准输出有不合协议的行：%r" % line[:120]
    for line in elines:
        if not re.match(r"FM (FAULT|LOG) ", line) or not printable(line):
            return "标准错误有不合协议的行：%r" % line[:120]
    results = [line for line in lines if line.startswith("FM RESULT ")]
    if len(results) != 1 or lines[-1] != results[0]:
        return "RESULT 行不是恰好一行且在最后"
    status = results[0].split(" ")[2]
    if status not in {0: ("GREEN",), 1: ("RED",), 2: ("FAULT", "PARTIAL")}.get(res["rc"], ()):
        return "RESULT %s 与退出码 %s 不一致" % (status, res["rc"])
    return ""


def check(name, ok, res, detail=""):
    problem = protocol(res) if "out_b" in res else ""
    ok = ok and not problem
    shown = "rc=%s 红码=%s 故障=%s" % (res["rc"], ",".join(sorted(res["reds"])) or "—", ",".join(res["faults"]) or "—")
    detail = "；".join(x for x in (detail, problem and "协议：" + problem) if x)
    os.write(1, ("%s\t%s\t%s\t%s\n" % ("通过" if ok else "失败", name, shown, detail)).encode())
    if not ok:
        os.write(2, (res["out"][-3000:] + res["err"][-3000:]).encode())
    return ok


def last_step(res):
    return res["steps"][-1][1] if res["steps"] else "-"


def snapshot(root):
    return sorted((os.path.relpath(os.path.join(d, n), root), os.lstat(os.path.join(d, n)).st_mtime_ns)
                  for d, _, ns in os.walk(root) for n in ns)


# ---- 形状门红例目录：（相对 formal_math 的路径，导入，正文，期望红码集合） ----
T, F = "Chan/Thm/", "Chan/Final/"
SHAPE_RED = [
    # 命令白名单：本地元编程与不在名单里的命令
    (T + "CmdMacro.lean", (), 'macro "fm_m" : term => `(1)', {"SHAPE_COMMAND"}),
    (T + "CmdSyntax.lean", (), 'syntax "fm_s" : term', {"SHAPE_COMMAND"}),
    (T + "CmdNotation.lean", (), 'notation "fm_n" => 1', {"SHAPE_COMMAND"}),
    (T + "CmdElab.lean", (), 'elab "fm_e" : term => pure (Lean.mkNatLit 1)', {"SHAPE_COMMAND"}),
    (T + "CmdInitialize.lean", (), "initialize pure ()", {"SHAPE_COMMAND"}),
    (T + "CmdPrint.lean", (), "#print Nat", {"SHAPE_COMMAND"}),
    (T + "CmdExport.lean", (), "export Nat (succ)", {"SHAPE_COMMAND"}),
    (T + "CmdLemma.lean", ("Mathlib.Tactic.Lemma",), "lemma fmL : True := trivial", {"SHAPE_COMMAND"}),
    # 声明白名单
    (T + "DeclAxiom.lean", (), "axiom fmAx : True", {"SHAPE_DECL"}),
    # 修饰符白名单与 meta section
    (T + "ModMeta.lean", (), "meta def fmMeta : Nat := 1", {"SHAPE_MODIFIER"}),
    (T + "ModUnsafe.lean", (), "unsafe def fmUnsafe : Nat := 1", {"SHAPE_MODIFIER"}),
    (T + "ModPartial.lean", (), "partial def fmPartial (n : Nat) : Nat := fmPartial n", {"SHAPE_MODIFIER"}),
    (T + "ModMetaSection.lean", (), "meta section\nend", {"SHAPE_MODIFIER"}),
    # 属性白名单（含属性宏不展开、-attr 擦除）
    (T + "AttrImplementedBy.lean", (), "def fmI : Nat := 1\n@[implemented_by fmI] def fmX : Nat := 1", {"SHAPE_ATTRIBUTE"}),
    (T + "AttrExtern.lean", (), '@[extern "fm_c"] opaque fmExt : Nat → Nat', {"SHAPE_ATTRIBUTE"}),
    (T + "AttrInit.lean", (), "def fmIO : IO Unit := pure ()\n@[init fmIO] def fmInit : Unit := ()", {"SHAPE_ATTRIBUTE"}),
    (T + "AttrCsimp.lean", (), "@[csimp] theorem fmC : @Nat.add = @Nat.add := rfl", {"SHAPE_ATTRIBUTE"}),
    (T + "AttrErase.lean", (), "def fmE : Nat := 1\nattribute [-implemented_by] fmE", {"SHAPE_ATTRIBUTE"}),
    (T + "AttrLocalMacro.lean", (), "@[local macro Lean.Parser.Term.app] def fmMac : Nat := 1", {"SHAPE_ATTRIBUTE"}),
    # 派生目标类白名单（行内与 deriving instance）
    (T + "DerivingInline.lean", (), "inductive FmD where\n  | a\nderiving Lean.ToJson", {"SHAPE_DERIVING"}),
    (T + "DerivingInstance.lean", (), "inductive FmD2 where\n  | a\nderiving instance Lean.ToExpr for FmD2",
     {"SHAPE_DERIVING"}),
    # #guard_msgs 的限制
    (F + "GuardSpec.lean", (), "/-- info: Nat : Type -/\n#guard_msgs (drop warning) in\n#check Nat", {"SHAPE_GUARD_MSGS"}),
    (F + "GuardInner.lean", (), "#guard_msgs in\nexample : True := trivial", {"SHAPE_GUARD_MSGS"}),
    (F + "PrintAxiomsBare.lean", (), "#print axioms Nat.add", {"SHAPE_GUARD_MSGS"}),
    (T + "GuardOutsideFinal.lean", (), "/-- info: Nat : Type -/\n#guard_msgs in\n#check Nat", {"SHAPE_COMMAND"}),
    # set_option 的各个语法位置
    (T + "OptCommand.lean", (), "set_option autoImplicit true", {"SHAPE_OPTION_CONTROLLED"}),
    (T + "OptCommandIn.lean", (), "set_option relaxedAutoImplicit true in\ntheorem fmO : True := trivial",
     {"SHAPE_OPTION_CONTROLLED"}),
    (T + "OptTerm.lean", (), "def fmT : Nat := set_option linter.unusedVariables false in 1", {"SHAPE_OPTION_CONTROLLED"}),
    (T + "OptTactic.lean", (), "theorem fmTac : True := by set_option debug.skipKernelTC true in trivial", {"SHAPE_OPTION"}),
    (T + "OptGrind.lean", (), "theorem fmG (x : Nat) : x = x := by\n  grind =>\n    set_option smartUnfolding false in\n"
     "    skip", {"SHAPE_OPTION"}),
    (T + "OptGuillemet.lean", (), "set_option «linter».unusedVariables false", {"SHAPE_OPTION_CONTROLLED"}),
    (T + "OptTrace.lean", (), "set_option trace.Meta.synthInstance true", {"SHAPE_OPTION"}),
    # 点名的禁用清单，每项一例
    (T + "FbSorryTerm.lean", (), "theorem fmS : 1 = 2 := sorry", {"SHAPE_FORBIDDEN"}),
    (T + "FbSorryTactic.lean", (), "theorem fmS : 1 = 2 := by sorry", {"SHAPE_FORBIDDEN"}),
    (T + "FbAdmit.lean", (), "theorem fmS : 1 = 2 := by admit", {"SHAPE_FORBIDDEN"}),
    (T + "FbNativeDecide.lean", (), "theorem fmN : 1 < 2 := by native_decide", {"SHAPE_FORBIDDEN"}),
    (T + "FbDecideNative.lean", (), "theorem fmN : 1 < 2 := by decide +native", {"SHAPE_FORBIDDEN"}),
    (T + "FbDecideNativeVal.lean", (), "theorem fmN : 1 < 2 := by decide (native := true)", {"SHAPE_FORBIDDEN"}),
    (T + "FbOldConfig.lean", (), "theorem fmC : 1 = 1 := by simp (config := {})", {"SHAPE_FORBIDDEN"}),
    # 旧式配置子句（独审 r1 甲-1）：按记号形状查，覆盖核心 config 种类、Aesop 的两种子句、新式 valConfigItem，
    # 出现位置覆盖战术块、by 项、conv、first 分支
    (T + "FbCfgAesop.lean", ("Mathlib.Tactic.Common",),
     "theorem fmA1 : True := by\n  aesop (config := { maxRuleApplications := 200 })", {"SHAPE_FORBIDDEN"}),
    (T + "FbCfgAesopSimpByTerm.lean", ("Mathlib.Tactic.Common",),
     "theorem fmA2 : True ∧ True := ⟨by aesop (simp_config := { zeta := false }), trivial⟩", {"SHAPE_FORBIDDEN"}),
    (T + "FbCfgPlausibleFirst.lean", ("Mathlib.Tactic.Common",),
     "theorem fmA3 (n : Nat) : n = n := by\n  first | plausible (config := { numInst := 5 }) | rfl", {"SHAPE_FORBIDDEN"}),
    (T + "FbCfgCongr.lean", ("Batteries.Tactic.Congr",),
     "theorem fmA4 (f : Nat → Nat) (a b : Nat) (h : a = b) : f a = f b := by\n  congr (config := {})",
     {"SHAPE_FORBIDDEN"}),
    (T + "FbCfgConv.lean", (), "theorem fmA5 (a : Nat) : a + 0 = a := by\n  conv => lhs; simp (config := {})",
     {"SHAPE_FORBIDDEN"}),
    # 按形状判的代价（独审 r2 甲-C1）：参数名以 config 结尾的命名参数同样判红
    (T + "FbCfgNamedArg.lean", (), "def fmRun (config n : Nat) : Nat := config + n\n"
     "theorem fmNA : fmRun (config := 1) 2 = 3 := rfl", {"SHAPE_FORBIDDEN"}),
    # 必绿对照：新式字面量配置项、名字不以 config 结尾的命名参数、类型标注与元组，本文件不得出现在红行里。
    # 类型标注与元组的左括号是 hygienicLParen 节点而不是记号，钉不住 legacyConfig 的 := 要件（见 README）
    (T + "CfgNewStyleGreen.lean", ("Mathlib.Tactic.Common",),
     "theorem fmG1 (a : Nat) : a + 0 = a := by simp (maxSteps := 1000)\n"
     "theorem fmG2 (p : Prop) (h : p) : p := by simp +contextual [h]\n"
     "theorem fmG3 (a : Nat) : a = a := by simp -zeta\n"
     "theorem fmG4 : 2 < 3 := by decide +kernel\n"
     "theorem fmG5 (a : Nat) : a + 0 = a := by\n  conv => lhs; simp (maxSteps := 10)\n"
     "theorem fmG6 : True := by\n  first | simp (maxDischargeDepth := 2) | trivial\n"
     "def fmRun2 (cfg n : Nat) : Nat := cfg + n\n"
     "theorem fmG7 : fmRun2 (cfg := 1) 2 = fmRun2 1 2 := rfl\n"
     "def fmG8 (my_config : Nat) : Nat := (my_config : Nat)\n"
     "def fmG9 (config : Nat) : Nat × Nat := (config, config)", set()),
    (T + "FbIncludeStr.lean", (), 'def fmStr : String := include_str "x.txt"', {"SHAPE_FORBIDDEN"}),
    (T + "FbEvalPercent.lean", ("Mathlib.Tactic.Eval",), "def fmEv : Nat := eval% 1 + 1", {"SHAPE_FORBIDDEN"}),
    (T + "FbByElab.lean", (), "def fmBe : Nat := by_elab pure (Lean.mkNatLit 1)", {"SHAPE_FORBIDDEN"}),
    (T + "FbRunTac.lean", (), "theorem fmR : True := by run_tac pure ()", {"SHAPE_FORBIDDEN"}),
    (T + "FbRunCmd.lean", (), "run_cmd pure ()", {"SHAPE_COMMAND", "SHAPE_FORBIDDEN"}),
    (T + "FbRunMeta.lean", (), "run_meta pure ()", {"SHAPE_COMMAND", "SHAPE_FORBIDDEN"}),
    (T + "FbRunElab.lean", (), "run_elab pure ()", {"SHAPE_COMMAND", "SHAPE_FORBIDDEN"}),
    (T + "FbSudo.lean", ("Mathlib.Tactic.SudoSetOption",), "def fmSu : Nat := sudo set_option fm.x true in 1",
     {"SHAPE_FORBIDDEN"}),
    (T + "FbTermUnsafe.lean", (), "def fmU : Nat := unsafe 1", {"SHAPE_FORBIDDEN"}),
    (T + "FbTrace.lean", (), 'theorem fmTr : True := by\n  trace "x"\n  trivial', {"SHAPE_FORBIDDEN"}),
    (T + "FbSuccessIfFail.lean", ("Mathlib.Tactic.SuccessIfFailWithMsg",),
     'theorem fmSf : True := by\n  success_if_fail_with_msg "x" fail\n  trivial', {"SHAPE_FORBIDDEN"}),
    (T + "FbEval.lean", (), "#eval 1", {"SHAPE_COMMAND", "SHAPE_FORBIDDEN"}),
    (T + "FbEvalBang.lean", (), "#eval! 1", {"SHAPE_COMMAND", "SHAPE_FORBIDDEN"}),
    (T + "FbExit.lean", (), "#exit", {"SHAPE_COMMAND", "SHAPE_FORBIDDEN"}),
    (T + "FbSorryAx.lean", (), "def fmSa : Nat := sorryAx Nat", {"SHAPE_FORBIDDEN"}),
    (T + "FbRootSorryAxCheck.lean", (), "#check (_root_.sorryAx False false)", {"SHAPE_FORBIDDEN"}),
    (T + "FbRootSorryAxVariable.lean", (), "variable (h : False := _root_.sorryAx False false)", {"SHAPE_FORBIDDEN"}),
    (F + "FbRootSorryAxGuard.lean", (), "#guard_msgs in\n#check _root_.sorryAx False false", {"SHAPE_FORBIDDEN"}),
    # 解析失败、缺库模块
    (T + "ParseError.lean", (), "theorem fmP : True := by (", {"SHAPE_PARSE"}),
    (T + "MissingLibrary.lean", ("Mathlib.FmDoesNotExist",), "def fmM : Nat := 1", {"SHAPE_IMPORT"}),
]


# ---- 骨架用例 ----

def skeleton(s):
    cases = []

    def case(cid):
        def register(fn):
            cases.append((cid, fn))
            return fn
        return register

    ok_thm = {"formal_math/Chan/Thm/Ok.lean": (M + "theorem ok : 1 + 1 = 2 := rfl\n").encode()}
    green = s.repo.commit({**s.base_files, **ok_thm}, s.base)
    lite_green = s.lite(ok_thm)

    @case("S1")
    def _():
        r = s.run("S1-green", green)
        good = r["rc"] == 0 and not r["reds"] and [x[2] for x in r["steps"]] == ["GREEN"] * 7 and \
            re.search(r"^FM STEP 5 shape GREEN ", r["out"], re.M) is not None and "未安装" not in r["out"] and \
            r["out"].startswith("FM MODE baseline ")
        return check("S1 阴性对照：未改动的证明提交七步全绿", good, r)

    # 夹具里的 lakefile 存成 hijack-lakefile.toml：门禁目录下任何层级的 Lake 配置名都会被预检判 LAKE_FILE。
    b1 = {"formal_math/" + dst: read(os.path.join(HERE, "selftest-cases", "r5-b1", src))
          for src, dst in (("hijack-lakefile.toml", "lakefile.toml"), ("ChanExplore/FakeAudit.lean",) * 2,
                           ("Chan/Thm/Bogus.lean",) * 2)}
    hijack = s.repo.commit({**s.base_files, **b1}, s.base)

    @case("S2")
    def _():
        r = s.run("S2-r5b1", hijack, branch="infra/hijack", extra=["--trusted-change-approved"], keep=True)
        good = r["rc"] == 1 and r["reds"] == {"PATH_SCOPE"} and last_step(r) == "precheck" and \
            len(r["steps"]) == 1 and not os.path.exists(os.path.join(r["work"], "trusted"))
        rmtree(r["work"])
        return check("S2 R5-B1 劫持在第 1 步预检判红，后续步骤没跑", good, r)

    @case("S3")
    def _():
        r = s.run("S3-r5b1-bypass", hijack, branch="infra/hijack", mode="bypass", keep=True, skip_shape=True)
        work = r["work"]
        binary = os.path.join(work, "trusted", "verification", "auditor", ".lake", "build", "bin", "fm_audit")
        planted = [os.path.join(d, n) for root in (s.tmp, s.repo.path) for d, _, ns in os.walk(root)
                   for n in ns if n == "sentinel_perfect_6of6.txt"]
        good = r["rc"] == 1 and r["reds"] == {"ENV_AXIOM", "ENV_AXIOM_DEP"} and last_step(r) == "env" and \
            r["steps"][0][:2] == ("2", "fetch") and ("binary=%s " % binary) in r["out"] and \
            read(os.path.join(work, "audited", "lakefile.toml")) == s.base_files["formal_math/lakefile.toml"] and \
            not planted
        rmtree(work)
        return check("S3 绕过预检从第 2 步起跑：配置仍取自基线、执行的是受信目录的审计程序、假 main 没跑", good, r,
                     "哨兵=%s" % (planted or "无"))

    attrs = b"formal_math/Chan/Thm/** export-ignore\n*.lean filter=fmevil eol=crlf\n"
    base2 = s.repo.commit({**s.lite_files, ".gitattributes": attrs}, s.lite_base)
    attr_file = (M + "theorem attr_kept : True := trivial\n").encode()
    head2 = s.repo.commit({**s.lite_files, ".gitattributes": attrs, "formal_math/Chan/Thm/Attr.lean": attr_file}, base2)

    @case("S4")
    def _():
        s.repo.git("config", "filter.fmevil.smudge", "sed s/theorem/axiom/")
        archived = subprocess.run(["git", "-C", s.repo.path, "archive", "--format=tar", head2, "formal_math/Chan"],
                                  capture_output=True, env=GIT_ID).stdout
        r = s.run("S4-gitattributes", head2, base=base2, keep=True, lite=True)
        got = os.path.join(r["work"], "audited", "Chan", "Thm", "Attr.lean")
        same = os.path.isfile(got) and read(got) == attr_file and (os.stat(got).st_mode & 0o7777) == 0o644
        good = r["rc"] == 0 and same and b"Attr.lean" not in archived
        rmtree(r["work"])
        return check("S4 .gitattributes（export-ignore、filter、eol）不影响取料：文件在、逐字节相同、模式 0644", good, r,
                     "对照：git archive %s 该文件" % ("不含" if b"Attr.lean" not in archived else "含"))

    for cid, mode, fault in (("S5a", "env-count", "MODULE_COUNT"), ("S5b", "headers-garbage", "AUDITOR_OUTPUT"),
                             ("S5c", "headers-drop", "AUDITOR_OUTPUT"), ("S5d", "env-verdict", "AUDITOR_OUTPUT"),
                             ("S5e", "env-exit", "AUDITOR_OUTPUT"), ("S5f", "shape-count", "MODULE_COUNT"),
                             ("S5g", "shape-drop", "AUDITOR_OUTPUT"), ("S5h", "plan-garbage", "AUDITOR_OUTPUT")):
        @case(cid)
        def _(mode=mode, fault=fault):
            r = s.run("S5-" + mode, lite_green, mode=mode, lite=True)
            good = r["rc"] == 2 and r["faults"] == [fault]
            return check("S5 审计程序输出被篡改（%s）退 2" % mode, good, r)

    edge = s.lite({"formal_math/Chan/Thm/Edge.lean": b"module\n\npublic import ChanExplore.Base\n"})

    @case("S6a")
    def _():
        r = s.run("S6-header-red", edge, keep=True, lite=True)
        good = r["rc"] == 1 and r["reds"] == {"IMPORT_EDGE", "IMPORT_SOURCE"} and \
            [x[1] for x in r["steps"]] == ["precheck", "fetch", "auditor", "headers"] and \
            not os.path.exists(os.path.join(r["work"], "audited", ".lake"))
        rmtree(r["work"])
        return check("S6a 第 4 步判红后第 5–7 步没跑（无步骤行，构建目录不存在）", good, r)

    broken = s.lite({"formal_math/Chan/Thm/Broken.lean": (M + "theorem broken : 1 = 2 := rfl\n").encode()})

    @case("S6b")
    def _():
        r = s.run("S6-build-red", broken, lite=True)
        good = r["rc"] == 1 and r["reds"] == {"BUILD_WFAIL"} and last_step(r) == "build" and len(r["steps"]) == 6
        return check("S6b 第 6 步构建判红后第 7 步没跑", good, r)

    @case("S7")
    def _():
        work = s.workdir("S7-sentinel")
        repo = Repo(os.path.join(s.tmp, "哨兵 repo"))
        targets = [os.path.join(s.tmp, "sentinel-tmp"), os.path.join(work, "trusted", "sentinel-trusted"),
                   os.path.join(repo.path, "sentinel-repo"), os.path.join(s.fake_packages, "sentinel-packages")]
        writes = "".join('  try IO.FS.writeFile "%s" "x" catch _ => pure ()\n' % t
                         for t in targets[:3] + [".lake/packages/sentinel-packages", "lake-manifest.json",
                                                 "Chan/Base.lean"])
        lean = (M + "#eval show IO Unit from do\n%s" % writes + '  IO.FS.writeFile ".lake/inside-ok" "x"\n').encode()
        files = {**s.lite_files, "formal_math/ChanExplore/Sentinel.lean": lean}
        base = repo.commit(s.lite_files)
        head = repo.commit(files, base)
        before = snapshot(repo.path)
        r = s.run("S7-sentinel", head, base=base, keep=True, workdir=work, repo=repo, lite=True, skip_shape=True)
        leaked = [t for t in targets if os.path.lexists(t)]
        audited = os.path.join(work, "audited")
        untouched = all(os.path.isfile(os.path.join(audited, p)) and
                        read(os.path.join(audited, p)) == files["formal_math/" + p]
                        for p in ("lake-manifest.json", "Chan/Base.lean"))
        inside = os.path.isfile(os.path.join(audited, ".lake", "inside-ok"))
        # 正对照写进 .lake 的文件不在形状表里，第 6 步因此恰好报这一条 EXTRA_ARTIFACT。
        good = r["rc"] == 1 and r["pairs"] == {("EXTRA_ARTIFACT", "formal_math/.lake/inside-ok")} and not leaked and \
            inside and untouched and snapshot(repo.path) == before
        rmtree(work)
        return check("S7 被审代码在构建期执行，但被审工作区源码、配置与工作区之外都没有被写入", good, r,
                     "工作区内对照=%s 源码配置未变=%s 外泄=%s" % (inside, untouched, leaked or "无"))

    @case("S8")
    def _():
        results, problems = [], []
        w = s.workdir("S8-usage")
        base_args = ["--repo", s.repo.path, "--base", s.lite_base, "--head", lite_green, "--branch", "proof/x",
                     "--workdir", w, "--packages", s.fake_packages]
        for label, argv in (("缩写", ["--wor", w] + base_args[:8]), ("等号", ["--until=3"] + base_args),
                            ("重复", base_args + ["--repo", s.repo.path]), ("缺依赖目录", base_args[:10]),
                            ("步号越界", base_args + ["--until", "8"]), ("未知开关", ["--approve"] + base_args),
                            ("工作目录在仓库里", base_args[:9] + [os.path.join(s.repo.path, "w")] + base_args[10:])):
            res = parse_result(subprocess.run([sys.executable, "-I", RUN, *argv], capture_output=True))
            results.append(res["rc"] == 2 and not res["steps"])
            problems.append(protocol(res))
        os.makedirs(w)
        open(os.path.join(w, "x"), "w").close()
        res = parse_result(subprocess.run([sys.executable, "-I", RUN, *base_args], capture_output=True))
        results.append(res["rc"] == 2 and res["faults"] == ["WORKDIR"])
        problems.append(protocol(res))
        shutil.rmtree(w)
        bad = [p for p in problems if p]
        return check("S8 参数与前置条件：缩写、等号、重复、缺项、越界、未知开关、工作目录在仓库里或非空都退 2",
                     all(results) and not bad, dict(rc="-", reds=set(), faults=[], out="", err=""),
                     "逐项=%s %s" % (results, bad[:1]))

    @case("S9")
    def _():
        r = s.run("S9-until3", lite_green, extra=["--until", "3"], lite=True)
        good = r["rc"] == 2 and [x[2] for x in r["steps"]] == ["GREEN"] * 3 and "RESULT PARTIAL" in r["out"]
        return check("S9 --until 3 全绿也退 2（未做完整判定）", good, r)

    @case("S10")
    def _():
        r = s.run("S10-until1-red", hijack, branch="infra/hijack", extra=["--until", "1", "--trusted-change-approved"])
        return check("S10 --until 1 遇红仍退 1", r["rc"] == 1 and r["reds"] == {"PATH_SCOPE"}, r)

    bare = template(gate=False, lite=True)
    bare_base = s.repo.commit(bare)
    bare_head = s.repo.commit({**bare, **ok_thm}, bare_base)

    @case("S11")
    def _():
        r = s.run("S11-no-trusted", bare_head, base=bare_base, lite=True)
        return check("S11 基线缺受信代码且没给自举开关：退 2", r["rc"] == 2 and r["faults"] == ["NO_TRUSTED_CODE"], r)

    @case("S12")
    def _():
        r = s.run("S12-bootstrap", bare_head, base=bare_base, extra=["--bootstrap-trusted-from", s.lite_base], lite=True)
        good = r["rc"] == 0 and r["out"].startswith("FM MODE bootstrap trusted=%s " % s.lite_base) and \
            "自举模式" in r["out"].splitlines()[0]
        return check("S12 自举模式：首行写明自举，受信代码取自指定提交，全绿", good, r)

    stale = dict(s.lite_files)
    stale["formal_math/verification/runner/run.py"] += b"# drift\n"
    stale_base = s.repo.commit(stale)

    @case("S13")
    def _():
        r = s.run("S13-runner-mismatch", stale_base, base=stale_base, lite=True)
        return check("S13 正在运行的 run.py 与受信提交不同：退 2", r["rc"] == 2 and r["faults"] == ["RUNNER_MISMATCH"], r)

    with_thm = {**s.lite_files, **ok_thm}
    ok_blob = s.repo.git("hash-object", "-w", "--no-filters", "--stdin", data=ok_thm["formal_math/Chan/Thm/Ok.lean"])
    lake_file = s.lite({**ok_thm, "formal_math/Chan/Thm/lakefile.lean": b"import Lake\n"})

    @case("S14")
    def _():
        r = s.run("S14-lake-file", lake_file, lite=True)
        good = r["rc"] == 1 and r["reds"] == {"LAKE_FILE"} and len(r["steps"]) == 1
        return check("S14 被审提交在 Chan/Thm/ 下放 lakefile.lean：第 1 步 LAKE_FILE", good, r)

    dup = s.repo.commit(with_thm, s.lite_base, raw={"formal_math/Chan/Thm": entry(b"100644", b"Ok.lean", ok_blob.strip()) * 2})

    @case("S15")
    def _():
        r = s.run("S15-tree-form", dup, lite=True)
        good = r["rc"] == 1 and "TREE_FORM" in r["reds"] and len(r["steps"]) == 1
        return check("S15 树对象里有重复条目：第 1 步 TREE_FORM", good, r)

    some_tree = s.repo.git("rev-parse", s.lite_base + ":formal_math/ChanTest").strip()
    for cid, label, target in (("S16a", "树", some_tree), ("S16b", "提交", s.lite_base.encode())):
        bad = s.repo.commit(with_thm, s.lite_base, raw={"formal_math/Chan/Thm": entry(b"100644", b"Ok.lean", target)})

        @case(cid)
        def _(label=label, bad=bad):
            r1 = s.run("S16-blob-mode", bad, lite=True)
            ok1 = check("%s 模式 100644 的条目实为%s对象：预检第 1 步 TREE_FORM" % (cid, label),
                        r1["rc"] == 1 and "TREE_FORM" in r1["reds"] and len(r1["steps"]) == 1, r1)
            r2 = s.run("S16-blob-mode-bypass", bad, mode="bypass", keep=True, lite=True)
            wrote = os.path.exists(os.path.join(r2["work"], "audited"))
            good = r2["rc"] == 2 and r2["faults"] == ["GIT"] and [x[1:] for x in r2["steps"]] == [
                ("fetch", "FAULT")] and not wrote
            rmtree(r2["work"])
            ok2 = check("%s 同一提交绕过预检：取料按对象读取时失败退 2，不写出被审工作区（纵深防御）" % cid, good, r2)
            return ok1 and ok2

    init_mod = (M + 'meta initialize\n  IO.eprintln s!"FM-SELFTEST-INIT-RAN app={← IO.appPath}"\n').encode()
    init_head = s.lite({"formal_math/ChanExplore/InitMod.lean": init_mod,
                        "formal_math/ChanExplore/InitUser.lean": b"module\n\npublic import ChanExplore.InitMod\n"})

    @case("S17")
    def _():
        r = s.run("S17-init", init_head, lite=True, skip_shape=True)
        built = re.search(r"^FM LOG build .*FM-SELFTEST-INIT-RAN app=\S*/bin/lean", r["err"], re.M) is not None
        audited = re.search(r"^FM LOG (env|headers) .*FM-SELFTEST-INIT-RAN", r["err"], re.M) is not None
        good = r["rc"] == 1 and r["reds"] == {"ENV_META"} and last_step(r) == "env" and built and not audited
        return check("S17 读环境不运行被审模块的初始化器：构建期 lean 运行了它（正对照），审计程序没有", good, r,
                     "正对照=%s 审计程序运行=%s" % (built, audited))

    kill = s.lite({"formal_math/ChanExplore/Kill.lean": (
        M + '#eval show IO Unit from do\n  let _ ← IO.Process.output {cmd := "/bin/sh", '
            'args := #["-c", "kill -KILL 2"]}\n  pure ()\n').encode()})

    @case("S18")
    def _():
        r = s.run("S18-signal", kill, lite=True, skip_shape=True)
        good = r["rc"] == 2 and r["faults"] == ["SIGNAL"] and r["steps"][-1][1:] == ("build", "FAULT")
        return check("S18 第 6 步沙箱里的 lake 被信号杀死：无法判定退 2，不报 BUILD_WFAIL", good, r)

    spin = s.lite({"formal_math/ChanExplore/Spin.lean": (
        M + '#eval show IO Unit from do\n  for _ in [0:100000] do\n    IO.sleep 200\n'
            '    let h ← IO.FS.Handle.mk ".lake/tick" .append\n    h.putStrLn "t"\n    h.flush\n').encode()})

    @case("S19")
    def _():
        r = s.run("S19-timeout", spin, mode="timeout", keep=True, lite=True, skip_shape=True)
        tick = os.path.join(r["work"], "audited", ".lake", "tick")
        size = os.path.getsize(tick) if os.path.exists(tick) else -1
        time.sleep(2)
        after = os.path.getsize(tick) if os.path.exists(tick) else -1
        good = r["rc"] == 2 and r["faults"] == ["BUILD"] and "超时" in r["err"] and size > 0 and size == after
        rmtree(r["work"])
        return check("S19 第 6 步超时（自测把时限改成 30 秒）：退 2，沙箱里的进程随之结束", good, r,
                     "tick 字节数 %d → %d（2 秒后）" % (size, after))

    def shell(script, imports=()):
        """被审模块在构建期跑一段 shell；imports 里的模块先于它构建。"""
        head = "module\n\n" + "".join("public import %s\n" % m for m in imports) + "\npublic section\n\n"
        return (head + '#eval show IO Unit from do\n  let _ ← IO.Process.output {cmd := "/bin/sh", args := #["-c", %s]}\n'
                % json.dumps(script)).encode()

    plant = s.lite({"formal_math/ChanExplore/Plant.lean": shell(
        "L=.lake/build/lib/lean; mkdir -p $L/Init && : > $L/Init/Fake.olean; : > $L/Chan/Ghost.olean; "
        "ln -s /etc/hostname $L/Chan/Link.olean; : > $L/Chan/Base.x.olean; mkfifo $L/Chan/Pipe.olean; "
        "mkdir $L/Chan/Dir.olean; : > .lake/stray; mkdir -p .lake/build/bin && : > .lake/build/bin/x; "
        ": > $L/ChanDyn/Ghost2.olean && chmod 111 $L/ChanDyn; chmod 755 $L/Chan/Base.ilean",
        ("Chan", "Chan.Base", "ChanDyn.Base"))})
    L = "formal_math/.lake/build/lib/lean/"
    plant_pairs = {("ARTIFACT_ROOT", L + "Init"), ("EXTRA_ARTIFACT", L + "Chan/Ghost.olean"),
                   ("ARTIFACT_FORM", L + "Chan/Link.olean"), ("EXTRA_ARTIFACT", L + "Chan/Base.x.olean"),
                   ("ARTIFACT_FORM", L + "Chan/Pipe.olean"), ("EXTRA_ARTIFACT", L + "Chan/Dir.olean"),
                   ("EXTRA_ARTIFACT", "formal_math/.lake/stray"), ("EXTRA_ARTIFACT", "formal_math/.lake/build/bin"),
                   ("ARTIFACT_FORM", L + "ChanDyn"), ("NO_ARTIFACT", "formal_math/ChanDyn/Base.lean"),
                   ("ARTIFACT_FORM", L + "Chan/Base.ilean")}

    @case("S20")
    def _():
        r = s.run("S20-artifacts", plant, lite=True, skip_shape=True)
        good = r["rc"] == 1 and r["pairs"] == plant_pairs and last_step(r) == "build"
        return check("S20 构建往 .lake 里放 Init、没有源码的模块、名字带多余点的 .olean、名为 .olean 的目录、符号链接、"
                     "管道、杂项文件与目录、把内容目录改成 0111：每一项按形状表各报其码（逐项比对红码与路径）", good, r,
                     "多出=%s 缺少=%s" % (sorted(r["pairs"] - plant_pairs), sorted(plant_pairs - r["pairs"])))

    relink = s.lite({"formal_math/ChanExplore/Relink.lean": shell(
        "mv .lake/build/lib/lean .lake/build/lib/real && ln -s real .lake/build/lib/lean", ("Chan", "Chan.Base"))})

    @case("S28")
    def _():
        r = s.run("S28-lib-symlink", relink, lite=True, skip_shape=True)
        want = {("ARTIFACT_FORM", "formal_math/.lake/build/lib/lean"), ("EXTRA_ARTIFACT", "formal_math/.lake/build/lib/real")}
        good = r["rc"] == 1 and want <= r["pairs"] and r["reds"] == {"ARTIFACT_FORM", "EXTRA_ARTIFACT", "NO_ARTIFACT"}
        return check("S28 构建把 build/lib/lean 换成指向别处的符号链接：ARTIFACT_FORM，且不跟随它去核对", good, r)

    nodyn_files = template(lite=True, roots=("Chan", "ChanChallenge", "ChanExplore"))
    nodyn_base = s.repo.commit(nodyn_files)
    nodyn_head = s.repo.commit({**nodyn_files, "formal_math/ChanDyn/X.lean": b"module\n"}, nodyn_base)

    @case("S21")
    def _():
        r = s.run("S21-no-artifact", nodyn_head, base=nodyn_base, lite=True)
        good = r["rc"] == 1 and r["reds"] == {"NO_ARTIFACT"} and last_step(r) == "build"
        return check("S21 基线配置不构建 ChanDyn，被审提交加了 ChanDyn/X.lean：第 6 步 NO_ARTIFACT", good, r)

    @case("S22")
    def _():
        probe_out = os.path.join(s.tmp, "probe-%d.jsonl" % id(object()))
        cfg = {"out": probe_out, "host": s.host_canary, "repo": os.path.join(s.repo.path, ".git")}
        r = s.run("S22-probe", lite_green, mode="probe", lite=True, env={"FM_SELFTEST_PROBE": json.dumps(cfg)})
        seen = {}
        if os.path.exists(probe_out):
            for line in open(probe_out):
                row = json.loads(line)
                seen[row["step"]] = row["lines"]
        allowed = {"HOME", "TMPDIR", "LANG", "PATH", "PWD", "SHLVL", "_", "OLDPWD", "LEAN_PATH", "LEAN_SYSROOT"}

        def facts(step):
            lines = seen.get(step, [])
            net = [x[4:] for x in lines if x.startswith("NET:")]
            env = [x[4:] for x in lines if x.startswith("ENV:")]
            return (net[0].strip(",").split(",") if net else None,
                    set(env[0].strip(",").split(",")) if env else None,
                    {x[4:] for x in lines if x.startswith("SEE:")}, {x[6:] for x in lines if x.startswith("WROTE:")})
        b, e, h = facts("build"), facts("env"), facts("shape")
        good = r["rc"] == 0 and b[0] == ["lo"] and e[0] == ["lo"] and h[0] == ["lo"] and b[1] is not None and \
            b[1] <= allowed and e[1] is not None and e[1] <= allowed and h[1] is not None and h[1] <= allowed and \
            b[2] == set() and e[2] == {"trusted"} and h[2] == {"trusted"} and \
            b[3] == {"lake"} and e[3] == set() and h[3] == set()
        return check("S22 沙箱探针（第 5、6、7 步同挂载同环境）：只有回环网卡、环境已清、宿主机目录与仓库不可见、"
                     "第 6 步只有 .lake 可写、第 5、7 步全只读、受信目录第 6 步不可见", good, r,
                     "第5步=%s 第6步=%s 第7步=%s" % (h, b, e))

    impostors = ("re", "json", "os", "sitecustomize", "traceback", "posix", "sys", "signal", "stat", "time")

    @case("S24")
    def _():
        copy = os.path.join(s.tmp, "isolated-copy")
        os.makedirs(copy, exist_ok=True)
        shutil.copy2(RUN, copy)
        marks = os.path.join(s.tmp, "impostor-marks")
        os.makedirs(marks, exist_ok=True)
        for name in impostors:
            with open(os.path.join(copy, name + ".py"), "w") as f:
                f.write("open(%r, 'w').close()\nraise SystemExit(0)\n" % os.path.join(marks, name))
        results = []
        for label, redirect in (("两路正常", ""), ("标准输出关闭", ">&-"), ("标准错误关闭", "2>&-"),
                                ("两路都关闭", ">&- 2>&-"), ("标准输出写满", ">/dev/full"), ("标准错误写满", "2>/dev/full")):
            p = subprocess.run(["/bin/sh", "-c", 'exec "$@" ' + redirect, "sh", sys.executable,
                                os.path.join(copy, "run.py"), "--repo", s.repo.path],
                               stdout=subprocess.PIPE if not redirect else subprocess.DEVNULL,
                               stderr=subprocess.PIPE if not redirect else subprocess.DEVNULL,
                               env={"PATH": os.environ["PATH"]})
            ran = sorted(os.listdir(marks))
            for m in ran:
                os.unlink(os.path.join(marks, m))
            ok = p.returncode == 2 and not ran and bool(redirect or p.stdout == b"FM RESULT FAULT prepare NOT_ISOLATED\n")
            results.append(ok)
            os.write(1 if ok else 2, ("  S24 %s：rc=%d 冒名模块被执行=%s\n" % (label, p.returncode, ran or "无")).encode())
        res = dict(rc="-", reds=set(), faults=[], out="", err="")
        return check("S24 不带 -I 运行（Python %d.%d.%d），两路正常、关闭、写满六种状态：同目录的 %s 都没有被执行，退 2"
                     % (sys.version_info[:3] + ("、".join(impostors),)), all(results), res, "逐项=%s" % results)

    @case("S25")
    def _():
        work = s.workdir("S25-stdout-eagain")
        argv = [sys.executable, "-I", RUN, "--repo", s.repo.path, "--base", s.lite_base, "--head", lite_green,
                "--branch", "proof/selftest", "--workdir", work, "--packages", s.fake_packages]
        rfd, wfd = os.pipe()
        os.set_blocking(wfd, False)
        try:
            while True:
                os.write(wfd, b"\n" * 65536)
        except BlockingIOError:
            pass
        p = subprocess.Popen(argv, stdout=wfd, stderr=subprocess.PIPE, env={"PATH": os.environ["PATH"],
                                                                             "HOME": os.environ.get("HOME", "/")})
        os.close(wfd)
        time.sleep(0.6)  # 这段时间里开头几行因管道满写不出（EAGAIN），之后读端开始读
        data = b""
        while True:
            chunk = os.read(rfd, 65536)
            if not chunk:
                break
            data += chunk
        os.close(rfd)
        err = p.stderr.read()
        rc = p.wait()
        rmtree(work)
        lines = data.lstrip(b"\n").decode("utf-8", "replace").splitlines()
        results = [l for l in lines if l.startswith("FM RESULT ")]
        good = rc == 2 and len(results) <= 1 and not any(l.startswith("FM RESULT GREEN") for l in lines)
        res = dict(rc=rc, reds=set(), faults=re.findall(r"^FM FAULT \S+ (\S+)", err.decode("utf-8", "replace"), re.M),
                   out="\n".join(lines), err=err.decode("utf-8", "replace"))
        return check("S25 标准输出一度写不出（满的非阻塞管道）、后来又写得出：退 2，至多一行结果行，没有绿结果行", good, res,
                     "结果行=%s" % results)

    for cid, sig in (("S26a", signal.SIGINT), ("S26b", signal.SIGTERM)):
        @case(cid)
        def _(cid=cid, sig=sig):
            work = s.workdir(cid + "-signal")
            argv = [sys.executable, "-I", os.path.join(s.tmp, "driver.py"), RUN, "plain", "--repo", s.repo.path,
                    "--base", s.lite_base, "--head", spin,
                    "--branch", "proof/selftest", "--workdir", work, "--packages", s.fake_packages]
            p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/"),
                                      "FM_SELFTEST_SKIP_SHAPE": "1"},
                                 preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
            tick = os.path.join(work, "audited", ".lake", "tick")
            for _ in range(900):
                if os.path.exists(tick):
                    break
                time.sleep(0.1)
            time.sleep(1)
            p.send_signal(sig)
            out, err = p.communicate()
            size = os.path.getsize(tick) if os.path.exists(tick) else -1
            time.sleep(2)
            after = os.path.getsize(tick) if os.path.exists(tick) else -1
            left = subprocess.run(["pgrep", "-f", work], capture_output=True).stdout.strip()
            rmtree(work)
            res = parse_result(subprocess.CompletedProcess(argv, p.returncode, out, err))
            good = res["rc"] == 2 and res["out"].endswith("FM RESULT FAULT build SIGNAL\n") and size > 0 and \
                size == after and not left
            return check("%s 第 6 步期间给运行脚本发 %s：写一行 FM RESULT FAULT … SIGNAL 后退 2，沙箱里的进程随之结束"
                         % (cid, sig.name), good, res, "tick %d → %d 残留进程=%s" % (size, after, left or "无"))

    for cid, step in (("S27a", "headers"), ("S27b", "env"), ("S27c", "shape")):
        @case(cid)
        def _(cid=cid, step=step):
            r = s.run(cid + "-auditor-signal", lite_green, mode="sig-" + step, lite=True)
            good = r["rc"] == 2 and r["faults"] == ["SIGNAL"] and r["steps"][-1][1:] == (step, "FAULT")
            return check("%s 第 %s 步的审计程序被信号杀死：SIGNAL 退 2" % (cid, step), good, r)

    @case("S31")
    def _():
        r = s.run("S31-late-signal", lite_green, mode="late-signal", lite=True)
        results = [l for l in r["out"].splitlines() if l.startswith("FM RESULT ")]
        good = r["rc"] == 2 and len(results) == 1 and results[0].startswith("FM RESULT GREEN") and \
            r["out"].endswith(results[0] + "\n") and "SIGNAL" in r["faults"]
        # 这一例的退出码与绿结果行按单向契约本就可以不一致（出现绿行不保证退 0），不套用 protocol() 的双向核对。
        res = {k: r[k] for k in ("rc", "reds", "faults", "out", "err")}
        return check("S31 绿结果行写出后、进程退出前收到 SIGTERM：处理函数不再写第二行结果行（标准输出仍只有那一行绿），退 2",
                     good, res, "结果行=%s" % results)

    @case("S32")
    def _():
        r = s.run("S32-no-certificate", lite_green, lite=True, env={"FM_SELFTEST_SKIP_SHAPE": "nocert"}, mode="plain")
        good = r["rc"] == 2 and r["faults"] == ["NO_CERTIFICATE"] and r["steps"][-1][1:] == ("env", "FAULT")
        return check("S32 第 5 步没有产出派生凭证（驱动脚本跳过第 5 步且不写凭证）：第 7 步 NO_CERTIFICATE 退 2，不靠异常兜底",
                     good, r)

    @case("S33")
    def _():
        r = s.run("S33-other-certificate", lite_green, lite=True, env={"FM_SELFTEST_SKIP_SHAPE": "othercert"}, mode="plain")
        good = r["rc"] == 2 and r["faults"] == ["NO_CERTIFICATE"] and r["steps"][-1][1:] == ("env", "FAULT")
        return check("S33 派生凭证非空但不是第 5 步写出的那一份（指向受信目录里另一个存在的文件）：第 7 步 NO_CERTIFICATE 退 2",
                     good, r)

    oracle_src = read(os.path.join(VERIFICATION, "must_green", "known-not-covered", "linarith-oracle-eval", "formal_math",
                                   "Chan", "Thm", "LinarithOracle.lean"))
    oracle_head = s.repo.commit({**s.base_files, "formal_math/Chan/Thm/LinarithOracle.lean": oracle_src}, s.base)

    @case("H4")
    def _():
        mark = "FM-R2-LINARITH-ORACLE-RAN"
        r = s.run("H4-linarith-oracle", oracle_head)
        in_log = [l for l in r["err"].splitlines() if mark in l]
        outside = [os.path.join(d, n) for root in (s.tmp, s.repo.path) for d, _, ns in os.walk(root)
                   for n in ns if mark in n]
        good = r["rc"] == 0 and bool(in_log) and all(l.startswith("FM LOG build ") for l in in_log) and \
            mark not in r["out"] and not outside
        return check("H4 已知不防 linarith (oracle := …)（独审 r2 甲-2）：第 5 步按设计放行、七步全绿，取值在构建期被求值；"
                     "标记只出现在 FM LOG build 行里，沙箱外没有带标记的文件", good, r,
                     "标记行=%d 沙箱外=%s" % (len(in_log), outside or "无"))

    ghost_files = {**s.lite_files, "formal_math/lake-manifest.json":
                   b'{"version": "1.3.0", "packagesDir": ".lake/packages", "packages": [{"name": "ghost"}], '
                   b'"name": "fixture", "lakeDir": ".lake", "fixedToolchain": false}\n'}
    ghost_base = s.repo.commit(ghost_files)
    ghost_head = s.repo.commit({**ghost_files, **ok_thm}, ghost_base)

    @case("S29")
    def _():
        r = s.run("S29-missing-package", ghost_head, base=ghost_base, lite=True)
        good = r["rc"] == 2 and r["faults"] == ["PACKAGES"] and r["steps"][-1][1:] == ("fetch", "FAULT")
        return check("S29 基线清单列了依赖目录里没有的包：取料 PACKAGES 退 2", good, r)

    @case("S30")
    def _():
        r = s.run("S30-umask", lite_green, lite=True, keep=True, umask=0o077)
        modes = {rel: oct(stat.S_IMODE(os.stat(os.path.join(r["work"], rel)).st_mode))
                 for rel in ("audited/Chan", "trusted/verification", "audited/Chan/Base.lean")}
        rmtree(r["work"])
        good = r["rc"] == 0 and modes == {"audited/Chan": "0o755", "trusted/verification": "0o755",
                                          "audited/Chan/Base.lean": "0o644"}
        return check("S30 umask 077 下取料写出的目录仍是 0755、文件 0644", good, r, "模式=%s" % modes)

    # ---- 被审内容与调用方输入进输出的各个入口（B-1、B-2） ----
    inject = "x\nFM STEP 4 headers GREEN 0.1s\nFM RESULT GREEN 七步全绿\u202e "

    @case("E1")
    def _():
        head = s.lite({"formal_math/Chan/Thm/Inject.lean": ("module\n\npublic import «%s»\n" % inject).encode()})
        r = s.run("E1-import-name", head, lite=True)
        good = r["rc"] == 1 and last_step(r) == "headers" and {"IMPORT_EDGE", "IMPORT_SOURCE"} <= r["reds"]
        return check("E1 导入名带换行、行分隔符与方向控制符：红行里转义，输出协议不破", good, r)

    @case("E2")
    def _():
        name = "a\nFM RESULT GREEN \u202e"
        head = s.lite({"formal_math/Chan/Thm/Names.lean": (
            M + "axiom «%s» : False\ntheorem «t\nFM STEP 7 env GREEN» : False := «%s»\n"
                "unsafe def «u\tFM RESULT GREEN» : Nat := 1\n" % (name, name)).encode()})
        r = s.run("E2-decl-names", head, lite=True, skip_shape=True)
        good = r["rc"] == 1 and r["reds"] == {"ENV_AXIOM", "ENV_AXIOM_DEP", "ENV_UNSAFE"}
        return check("E2 公理名、声明名带换行与控制符（环境层红行的对象栏与说明栏）", good, r)

    for cid, lock, rc, want in (("E3", b'{"a\\nFM RESULT GREEN": "x"}', 1, "LOCK_REMOVED"),
                                ("E4", b'{"\\ud800": "x"}', 2, "INPUT"),
                                ("E5", b'{"\\ud800": "x", "\\ud800": "y"}', 2, "INPUT"),
                                ("E6", b'{"k": "\\ud800"}', 2, "INPUT"),
                                ("E7", b'{"k": NaN}', 2, "INPUT"),
                                ("E14", b'{"a": "x", "a": "y"}', 2, "INPUT"),
                                ("E15", b'{"a": "\xff"}', 2, "INPUT")):
        @case(cid)
        def _(cid=cid, lock=lock, rc=rc, want=want):
            head = s.lite({"formal_math/statement-lock.json": lock})
            r = s.run(cid + "-lock", head, branch="decl/lock", lite=True)
            good = r["rc"] == rc and (r["reds"] == {want} if rc == 1 else r["faults"] == [want])
            return check("%s 锁文件 %s：%s" % (cid, lock.decode("utf-8", "backslashreplace"), "红行转义" if rc == 1 else "无法判定退 2，不回溯"),
                         good, r)

    @case("E8")
    def _():
        r = s.run("E8-branch", lite_green, branch="proof/x\nFM RESULT GREEN\x1b[2J", lite=True)
        good = r["rc"] == 1 and r["reds"] == {"BRANCH_ROLE"} and "\\x5c" not in r["out"]
        return check("E8 分支名带换行与 ESC：预检红行转出时只转义一次", good, r)

    @case("E9")
    def _():
        work = s.workdir("E9")
        argv = [b"--repo", s.repo.path.encode(), b"--base", s.lite_base.encode(), b"--head",
                b"HEAD\nFM RESULT GREEN", b"--branch", b"proof/\xff\xfe", b"--workdir", work.encode(),
                b"--packages", s.fake_packages.encode()]
        r = parse_result(subprocess.run([sys.executable, "-I", RUN, *argv], capture_output=True))
        return check("E9 提交名带换行、分支名非 UTF-8：BAD_REV 退 2", r["rc"] == 2 and r["faults"] == ["BAD_REV"], r)

    @case("E10")
    def _():
        head = s.lite({"formal_math/ChanExplore/Say.lean": (
            M + '#eval IO.println "x\\nFM RESULT GREEN 伪造\\n\\x1b[31mFM STEP 7 env GREEN\\u2028"\n').encode()})
        r = s.run("E10-lake-log", head, lite=True, skip_shape=True)
        good = r["rc"] == 0 and "伪造" in r["err"]
        return check("E10 构建日志里的伪造行：只以转义后的 FM LOG 行出现在标准错误", good, r)

    @case("E11")
    def _():
        name = b"A\nFM RESULT GREEN.lean"
        head = s.repo.commit(with_thm, s.lite_base, raw={"formal_math/Chan/Thm": entry(b"100644", name, ok_blob.strip())})
        r1 = s.run("E11-path", head, lite=True)
        r2 = s.run("E11-path-bypass", head, mode="bypass", lite=True)
        ok1 = check("E11a 内容路径带换行：预检 PATH_GRAMMAR 红行转义", r1["rc"] == 1 and "PATH_GRAMMAR" in r1["reds"], r1)
        ok2 = check("E11b 同一提交绕过预检：取料 CONTENT_PATH 红行转义",
                    r2["rc"] == 1 and r2["reds"] == {"CONTENT_PATH"}, r2)
        return ok1 and ok2

    @case("E12")
    def _():
        head = s.lite({"formal_math/Chan/Thm/Bad.lean": b"module\n-- \xff\xfe\n"})
        r = s.run("E12-encoding", head, lite=True)
        return check("E12 内容文件不是 UTF-8：取料 CONTENT_ENCODING 红", r["rc"] == 1 and r["reds"] == {"CONTENT_ENCODING"}, r)

    @case("E13")
    def _():
        bad_dir = os.path.join(s.tmp, "\udcff\nFM RESULT GREEN").encode("utf-8", "surrogateescape")
        res = []
        for label, wd, pk, want in (("工作目录父目录不存在", bad_dir + b"/missing/w", s.fake_packages.encode(), "INTERNAL"),
                                    ("依赖目录不存在", (s.workdir("E13") + "-w").encode(), bad_dir, "PACKAGES")):
            argv = [b"--repo", s.repo.path.encode(), b"--base", s.lite_base.encode(), b"--head", lite_green.encode(),
                    b"--branch", b"proof/x", b"--workdir", wd, b"--packages", pk]
            r = parse_result(subprocess.run([sys.executable, "-I", RUN, *argv], capture_output=True))
            res.append(check("E13 调用方路径参数非 UTF-8 且带换行（%s）：异常消息转义，退 2" % label,
                             r["rc"] == 2 and r["faults"] == [want], r))
        return all(res)

    # ---- 第 5 步：源码形状（第四片） ----
    def shape_pairs(res):
        """第 5 步红行的（红码，文件）集合，去掉行号。"""
        return {(line.split(" ")[3], line.split(" ")[4].rsplit(":", 1)[0]) for line in res["out"].splitlines()
                if line.startswith("FM RED shape ")}

    red_files, red_want = {}, set()
    for rel, imports, body, codes in SHAPE_RED:
        red_files["formal_math/" + rel] = ("module\n\n" + "".join("public import %s\n" % i for i in imports) +
                                           "\npublic section\n\n" + body + "\n").encode()
        red_want |= {(c, "formal_math/" + rel) for c in codes}
    red_head = s.repo.commit({**s.base_files, **red_files}, s.base)

    @case("H1")
    def _():
        r = s.run("H1-shape-red", red_head)
        got = shape_pairs(r)
        good = r["rc"] == 1 and last_step(r) == "shape" and got == red_want and len(r["steps"]) == 5
        return check("H1 形状门红例目录（%d 个文件：命令、声明、修饰符、属性、派生、#guard_msgs、set_option 各位置、"
                     "禁用清单各项、Chan/Defs、解析失败、缺库模块）：逐文件比对红码集合" % len(SHAPE_RED), good, r,
                     "多出=%s 缺少=%s" % (sorted(got - red_want)[:6], sorted(red_want - got)[:6]))

    # 旧门 15 的源码层规则：Chan/Defs 归 decl 角色，单独一个提交。
    defs_head = s.repo.commit({**s.base_files,
                               "formal_math/Chan/Defs/NoExpose.lean": (M + "def fmDef : Nat := 1\n").encode(),
                               "formal_math/Chan/Defs/Exposed.lean":
                                   b"module\n\n@[expose] public section\n\ndef fmDef2 : Nat := 1\n"}, s.base)

    @case("H1b")
    def _():
        r = s.run("H1b-defs-expose", defs_head, branch="decl/selftest")
        good = r["rc"] == 1 and shape_pairs(r) == {("SHAPE_EXPOSE", "formal_math/Chan/Defs/NoExpose.lean")}
        return check("H1b Chan/Defs 下的文件不用 @[expose] public section：SHAPE_EXPOSE；用了的那个不报", good, r,
                     "得到=%s" % sorted(shape_pairs(r)))

    scope_dir = os.path.join(HERE, "selftest-cases", "shape", "scope")
    scope = {name: read(os.path.join(scope_dir, name + ".lean")) for name in ("Green", "Red1", "Red2", "Red3")}
    scope_green = s.repo.commit({**s.base_files, "formal_math/Chan/Thm/ScopeGreen.lean": scope["Green"]}, s.base)
    scope_red = s.repo.commit({**s.base_files, **{"formal_math/Chan/Thm/Scope%s.lean" % n: scope[n]
                                                  for n in ("Red1", "Red2", "Red3")}}, s.base)

    @case("H2")
    def _():
        r = s.run("H2-scope-green", scope_green, keep=True)
        counts = elab_consistency(s, r["work"], os.path.join(r["work"], "trusted", "verification", "auditor",
                                                              ".lake", "build", "bin", "fm_audit"))
        rmtree(r["work"])
        good = r["rc"] == 0 and counts["mismatch"] == [] and counts["files"] >= 1
        ok1 = check("H2a 作用域跟踪的阴性对照（namespace/section/end 嵌套、open … in、mutual … end、public section、"
                    "文件末尾未闭合的节）：七步全绿，只解析与真实精化的命令数一致", good, r, str(counts))
        r2 = s.run("H2-scope-red", scope_red)
        want = {("SHAPE_PARSE", "formal_math/Chan/Thm/Scope%s.lean" % n) for n in ("Red1", "Red2", "Red3")}
        ok2 = check("H2b 作用域关闭后作用域记号失效（end Nat、section 内 open 后 end、open … in 之后）：第 5 步 SHAPE_PARSE",
                    r2["rc"] == 1 and shape_pairs(r2) == want, r2, "得到=%s" % sorted(shape_pairs(r2)))
        r3 = s.run("H2-scope-red-build", scope_red, skip_shape=True)
        ok3 = check("H2c 同一提交跳过第 5 步：真实构建同样拒绝（BUILD_WFAIL），解析结论与 Lean 一致",
                    r3["rc"] == 1 and r3["reds"] == {"BUILD_WFAIL"}, r3)
        return ok1 and ok2 and ok3

    marker = "FM-SHAPE-EXEC-MARK"
    exec_head = s.lite({"formal_math/Chan/Thm/Exec.lean": (
        M + 'initialize IO.eprintln "%s-init"\n'
            '#eval IO.eprintln "%s-eval"\n'
            'macro "fm_mark" : command => do\n  Lean.Macro.throwError "%s-macro"\n'
            'run_cmd Lean.logInfo "%s-run"\n'
            'fm_mark\n' % ((marker,) * 4)).encode()})

    @case("H3")
    def _():
        r = s.run("H3-no-exec", exec_head, lite=True, keep=True)
        leaked = marker in r["err"]
        want = {("SHAPE_COMMAND", "formal_math/Chan/Thm/Exec.lean"), ("SHAPE_FORBIDDEN", "formal_math/Chan/Thm/Exec.lean"),
                ("SHAPE_PARSE", "formal_math/Chan/Thm/Exec.lean")}
        no_lake = not os.path.exists(os.path.join(r["work"], "audited", ".lake"))
        rmtree(r["work"])
        ok1 = check("H3a 被审文件带 initialize、#eval、宏定义与 run_cmd：第 5 步红，被审代码没有执行（标记未出现在任何日志、"
                    "构建目录没建）", r["rc"] == 1 and shape_pairs(r) == want and not leaked and no_lake, r,
                    "标记出现=%s" % leaked)
        ctl = s.lite({"formal_math/Chan/Thm/Exec.lean": (M + '#eval IO.eprintln "%s-eval"\n' % marker).encode()})
        r2 = s.run("H3-control", ctl, lite=True, skip_shape=True)
        ran = re.search(r"^FM LOG build .*%s-eval" % marker, r2["err"], re.M) is not None
        ok2 = check("H3b 正对照：跳过第 5 步时同一个 #eval 在第 6 步构建期执行，标记出现在构建日志里", ran, r2)
        return ok1 and ok2

    tree = "inductive Tree where\n  | leaf\n  | node (cs : List Tree)\nderiving Repr, BEq, Hashable, Ord\n\n"
    derived_ok = s.lite({"formal_math/Chan/Thm/Derived.lean": (M + tree).encode()})
    spoof = s.lite({"formal_math/Chan/Thm/Derived.lean": (
        M + tree + "namespace Spoof\npartial def loop (n : Nat) : Nat := loop (n + 1)\nend Spoof\n").encode()})

    @case("D1")
    def _():
        r = s.run("D1-derived-cert", derived_ok, lite=True)
        ok1 = check("D1a 合法派生（递归类型的 Repr、BEq、Hashable、Ord 生成 partial 辅助函数）：派生证书豁免，七步全绿",
                    r["rc"] == 0, r)
        r2 = s.run("D1-no-cert", derived_ok, lite=True, skip_shape=True)
        ok2 = check("D1b 同一提交派生证书为空：辅助函数在第 7 步 ENV_PARTIAL（证书确实是豁免的来源）",
                    r2["rc"] == 1 and r2["reds"] == {"ENV_PARTIAL"}, r2)
        return ok1 and ok2

    @case("D2")
    def _():
        r = s.run("D2-spoof", spoof, lite=True, mode="shape-noreds")
        names = {line.split(" ")[4] for line in r["out"].splitlines() if line.startswith("FM RED env ")}
        good = r["rc"] == 1 and r["reds"] == {"ENV_PARTIAL"} and \
            names == {"formal_math/Chan/Thm/Derived.lean:Spoof.loop._unsafe_rec"}
        return check("D2 同一模块里有合法派生时，手写 partial def（形状门被驱动脚本放行）：环境层按证书位置比对，"
                     "只有手写的那个 ENV_PARTIAL", good, r, "红行对象=%s" % sorted(names))

    @case("E16")
    def _():
        head = s.lite({"formal_math/Chan/Thm/Opt.lean": (
            M + "set_option «x\nFM RESULT GREEN\u202e» true\ntheorem t : True := by (\n").encode()})
        r = s.run("E16-shape-escape", head, lite=True)
        good = r["rc"] == 1 and r["reds"] == {"SHAPE_OPTION", "SHAPE_PARSE"}
        return check("E16 形状门发现的说明栏含被审文字（带换行与方向控制符的选项名、解析错误消息）：输出协议不破", good, r)
    return cases


def elab_consistency(s, work, auditor):
    """对一次保留了工作目录的全绿运行：用审计程序重跑形状门拿每个文件只解析的命令数，再用真实前端（自测脚本
    ElabCount.lean，被审产物在搜索路径上）精化同一批文件数命令。返回 {files, mismatch}。"""
    audited = os.path.join(work, "audited")
    mods = []
    for d, _, names in os.walk(audited):
        if ".lake" in d.split(os.sep):
            continue
        for n in names:
            rel = os.path.relpath(os.path.join(d, n), audited)
            if n.endswith(".lean") and rel.split(os.sep)[0] in ROOTS + ("Chan.lean", "ChanExplore.lean"):
                mods.append((rel[:-5].replace(os.sep, "."), os.path.join(audited, rel)))
    manifest = json.loads(read(os.path.join(audited, "lake-manifest.json")))
    libs = [os.path.join(s.packages, p["name"], ".lake", "build", "lib", "lean") for p in manifest["packages"]]
    prefix = subprocess.run(["lean", "--print-prefix"], cwd=audited, capture_output=True, text=True).stdout.strip()
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/"), "LEAN_PATH": ":".join(libs),
           "LEAN_SYSROOT": prefix}
    args = [x for m, p in mods for x in (m, p)]
    plan = subprocess.run([auditor, "shape-plan", *args], capture_output=True, env=env)
    groups = {}
    for line in plan.stdout.decode().splitlines():
        row = json.loads(line)
        if row[0] == "plan":
            groups.setdefault(tuple(row[3]), []).append((row[2], row[1]))
    parsed = {}
    for libs_, items in groups.items():
        out = subprocess.run([auditor, "shape", *libs_, "--", *(x for m, p in items for x in (m, p))],
                             capture_output=True, env=env).stdout.decode()
        for line in out.splitlines():
            row = json.loads(line)
            if row[0] == "file":
                parsed[row[1]] = row[3]
    env["LEAN_PATH"] += ":" + os.path.join(audited, ".lake", "build", "lib", "lean")
    # 一个进程只精化一个文件：同一进程里第二次带初始化器加载另一组导入时，作用域记号等扩展状态不可靠。
    elab = {}
    for m, p in mods:
        out = subprocess.run(["lean", "--run", os.path.join(HERE, "selftest-cases", "shape", "ElabCount.lean"), m, p],
                             capture_output=True, env=env, cwd=audited).stdout.decode()
        elab.update({row[1]: row[2] for row in map(json.loads, out.splitlines()) if row[0] == "elab" and not row[3]})
    mismatch = [(os.path.relpath(p, audited), parsed.get(p), elab.get(p)) for _, p in mods
                if parsed.get(p) is None or parsed.get(p) != elab.get(p)]
    return {"files": len(mods), "commands": sum(parsed.values()), "mismatch": mismatch}


# ---- 语料用例 ----

def load_table():
    rows = []
    with open(os.path.join(HERE, "fixtures.tsv"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            fixture, owner, rc, step, codes, note = line.rstrip("\n").split("\t")
            rows.append(dict(fixture=fixture, owner=owner, rc=rc, step=step,
                             codes=set() if codes == "-" else set(codes.split(",")), note=note))
    return rows


# 归环境层、声明锁的旧夹具多半带第 5 步会拒的写法（axiom、partial、implemented_by 等）；它们要测的是第 7 步，
# 语料用例经驱动脚本跳过第 5 步跑（派生证书为空），表里的期望也按此记。
SKIP_SHAPE_OWNERS = ("环境层", "声明锁")


def corpus_case(s, fixture, keep=False, skip_shape=False):
    src = os.path.join(VERIFICATION, fixture, "formal_math")
    overlay = {}
    for d, _, names in os.walk(src):
        for n in names:
            full = os.path.join(d, n)
            overlay["formal_math/" + os.path.relpath(full, src)] = read(full)
    warm = "warm:" + s.warm
    touches_trusted = any(p in ("formal_math/" + c for c in CONFIG_NAMES) or p.startswith("formal_math/verification/")
                          for p in overlay)
    if touches_trusted:
        # 改了受信文件的夹具：基线是模板，被审提交叠上夹具（含它自己的配置），按证明角色送审。
        head = s.repo.commit({**template(), **overlay}, s.base)
        return s.run(fixture, head, mode=warm, keep=keep, skip_shape=skip_shape), "base=模板 head=模板+夹具"
    # 只有内容的夹具：基线与被审是同一提交（预检因受管路径无改动而绿），配置按夹具实有的内容根生成。
    files = template(overlay, placeholders=False)
    head = s.repo.commit(files)
    return s.run(fixture, head, base=head, mode=warm, keep=keep, skip_shape=skip_shape), "base=head=模板+夹具"


def corpus(s, discover, only):
    if discover:
        fixtures = sorted(os.path.relpath(os.path.join(VERIFICATION, c, g, f), VERIFICATION)
                          for c in ("must_red", "must_green", "must_unknown")
                          for g in sorted(os.listdir(os.path.join(VERIFICATION, c))) if g != "g6b"
                          for f in sorted(os.listdir(os.path.join(VERIFICATION, c, g))))
        owners = {r["fixture"]: r["owner"] for r in load_table()}
        rows = [dict(fixture=f, owner=owners.get(f, "?")) for f in fixtures]
    else:
        rows = [r for r in load_table() if r["rc"] != "-"]
    rows = [r for r in rows if only is None or only in r["fixture"]]

    def one(row):
        # 全绿的夹具另做「只解析与真实精化的命令数一致」比对（备忘第六节第三处）。
        skip = row["owner"] in SKIP_SHAPE_OWNERS
        consistency = not discover and row["rc"] == "0" and not skip
        res, how = corpus_case(s, row["fixture"], keep=consistency, skip_shape=skip)
        how += "（跳过第 5 步）" if skip else ""
        step = last_step(res) if res["rc"] == 1 else "-"
        counts = None
        if consistency:
            counts = elab_consistency(s, res["work"], os.path.join(s.warm, "build", "bin", "fm_audit"))
            rmtree(res["work"])
        if discover:
            line = "%s\t?\t%s\t%s\t%s\t%s\n" % (row["fixture"], res["rc"], step,
                                                ",".join(sorted(res["reds"])) or "-", how)
            os.write(1, line.encode())
            return True
        good = str(res["rc"]) == row["rc"] and step == row["step"] and res["reds"] == row["codes"] and \
            (counts is None or not counts["mismatch"] and counts["files"] > 0)
        return check("语料 %s（%s）" % (row["fixture"], row["owner"]), good, res,
                     "期望 rc=%s 步=%s 码=%s%s" % (row["rc"], row["step"], ",".join(sorted(row["codes"])) or "—",
                                                 "" if counts is None else "；命令数 解析=精化 %d 个文件 %d 条，不一致 %s"
                                                 % (counts["files"], counts["commands"], counts["mismatch"] or "无")))
    return [lambda row=row: one(row) for row in rows]


# ---- 弱化自测 ----

RUNNER = "verification/runner/run.py"
SHAPE = "verification/auditor/Auditor/Shape.lean"
MUTANTS = [
    ("去掉 RUNNER_MISMATCH", RUNNER, [("if me != object_at(ctx, ctx.trusted, TRUSTED_CODE[0]):", "if False:")],
     "S13"),
    ("去掉模块数比对", RUNNER, [("if result[3] != want:", "if False:")], "S5a,S5f"),
    ("不核对判定、发现与退出码一致", RUNNER,
     [("(result[2] == \"red\") != bool(findings) or p.returncode != (1 if findings else 0)", "False")], "S5d,S5e"),
    ("判红后继续跑下一步", RUNNER, [("            if reds:\n                return 1 if finish(",
                              "            if reds and n == 7:\n                return 1 if finish(")], "S2,S6a"),
    ("第 6 步受信目录可见可写", RUNNER, [('("--ro-bind", ctx.packages, os.path.join(lake_dir, "packages"))]',
                                 '("--ro-bind", ctx.packages, os.path.join(lake_dir, "packages")), '
                                 '("--bind", ctx.trusted_dir, ctx.trusted_dir)]')], "S22"),
    ("第 6 步被审工作区整个可写", RUNNER, [('binds = [("--ro-bind", ctx.audited, ctx.audited), ("--bind", lake_dir, lake_dir),',
                                   'binds = [("--bind", ctx.audited, ctx.audited), ("--bind", lake_dir, lake_dir),')],
     "S7,S22"),
    ("第 7 步被审工作区可写", RUNNER,
     [('ctx.modules\n    binds = [("--ro-bind", ctx.audited, ctx.audited), ("--ro-bind", ctx.packages, ctx.packages),',
       'ctx.modules\n    binds = [("--bind", ctx.audited, ctx.audited), ("--ro-bind", ctx.packages, ctx.packages),')], "S22"),
    ("沙箱不断网", RUNNER, [('b"--unshare-all"', 'b"--unshare-user", b"--unshare-pid", b"--unshare-ipc", '
                                              'b"--unshare-uts", b"--unshare-cgroup"')], "S22"),
    ("沙箱不清环境（去掉 --clearenv 且继承调用方环境）", RUNNER,
     [('args.append(b"--clearenv")', 'args += []'),
      ('env={"PATH": GIT_ENV["PATH"]})\n    if p.returncode >= 128', 'env=dict(os.environ))\n    if p.returncode >= 128')],
     "S22"),
    ("沙箱不遮宿主机目录", RUNNER, [('for hidden in ("/home", "/root", "/run", "/var", "/tmp", ctx.workdir):',
                               'for hidden in ("/tmp",):')], "S7,S22"),
    ("去掉「产物目录顶层只许内容根」（R16）", RUNNER,
     [('rel.rsplit("/", 1)[1].split(".")[0] not in ROOT_NAMES:', "False:")], "S20"),
    ("去掉目录项类型检查：符号链接、管道等（R3、R15）", RUNNER,
     [("if not (stat.S_ISDIR(kind) or stat.S_ISREG(kind)):", "if False:")], "S20,S28"),
    ("去掉形状表（EXTRA_ARTIFACT）", RUNNER, [('return red("EXTRA_ARTIFACT", rel, "形状表外的目录项")', "pass")], "S20"),
    ("目录模式异常或列不出时跳过", RUNNER,
     [('return red("ARTIFACT_FORM", rel, "目录模式 %o 不合（属主须可读写进入，不许特殊位）" % mode)', "return"),
      ('return red("ARTIFACT_FORM", rel, "目录列不出")', "return")], "S20"),
    ("去掉 NO_ARTIFACT", RUNNER, [('if "build/lib/lean/%s.olean" % "/".join(m) not in good:', "if False:")], "S21"),
    ("信号死亡不归入无法判定", RUNNER, [("if p.returncode >= 128 or p.returncode < 0:", "if p.returncode < 0:")], "S18"),
    ("信号判定只对第 6 步构建生效（R5b）", RUNNER,
     [("if p.returncode >= 128 or p.returncode < 0:", 'if tag == "build" and (p.returncode >= 128 or p.returncode < 0):')],
     "S27a,S27b"),
    ("输出不转义", RUNNER, [("if 0x21 <= c < 0x7F and c != 0x5C or (spaces and c == 0x20):", "if True:")],
     "E1,E2,E3,E8,E10"),
    ("JSON 不拒孤立代理项", RUNNER, [("if not no_surrogates(value):", "if False:")], "E6"),
    ("JSON 接受重复键（R2）", RUNNER, [('raise ValueError("重复键")', "pass")], "E14"),
    ("JSON 不要求合法 UTF-8（R7）", RUNNER, [('json.loads(data.decode("utf-8"),', 'json.loads(data.decode("utf-8", "ignore"),')],
     "E15"),
    ("不核对依赖目录里有没有基线清单的包（R8）", RUNNER,
     [("missing = [n for n in names if not os.path.isdir(os.path.join(ctx.packages, n))]", "missing = []")], "S29"),
    ("建目录后不 chmod（R14）", RUNNER, [("    os.mkdir(path, mode)\n    os.chmod(path, mode)", "    os.mkdir(path, mode)")],
     "S30"),
    ("绿的结论不再要求标准输出都写出去了（R4）", RUNNER,
     [('        if STATE["output"] is not None:\n            STATE["step"] = "output"',
       '        if False:\n            STATE["step"] = "output"')], "S25"),
    ("不装 SIGINT、SIGTERM 处理函数", RUNNER, [("        signal.signal(sig, on_signal)", "        pass")], "S26a,S26b"),
    ("去掉产物文件模式检查：执行位、特殊位、属主可读（骨架复审 r3 Q2）", RUNNER,
     [("            if mode & 0o7111 or not mode & 0o400:", "            if False:")], "S20"),
    ("finish() 去掉「整次运行至多写一次」的守卫（骨架复审 r3 Q5）", RUNNER,
     [('    if STATE["result"]:\n        return False\n    STATE["result"] = True\n', '    STATE["result"] = True\n')], "S31"),
    ("不查隔离模式", RUNNER, [("if not sys.flags.isolated:", "if False:")], "S24"),
    ("隔离检查失败时的诊断经 sys 的流写、不兜异常（N-1 旧形）", RUNNER,
     [("        try:\n            posix.write(fd, line.encode())\n        except BaseException:  # noqa: BLE001\n            pass",
       "        (sys.stderr if fd == 2 else sys.stdout).write(line)")], "S24"),
    ("审计程序加载扩展并运行初始化器", "verification/auditor/Main.lean",
     [("  let env := (← Lean.importModules (mods.map fun m => { module := m }) {}\n    (level := .private))",
       "  Lean.enableInitializersExecution\n"
       "  let env := (← Lean.importModules (mods.map fun m => { module := m }) {}\n"
       "    (level := .private) (loadExts := true))")], "S17"),
    # 第四片：源码形状门与派生证书
    ("去掉命令白名单", SHAPE, [('    if !ok then issues := issues.push (stx, "SHAPE_COMMAND"',
                          '    if false && !ok then issues := issues.push (stx, "SHAPE_COMMAND"')], "H1"),
    ("去掉声明白名单", SHAPE, [("if kind == `Lean.Parser.Command.declaration && !declKinds.contains",
                          "if false && kind == `Lean.Parser.Command.declaration && !declKinds.contains")], "H1"),
    ("去掉修饰符白名单", SHAPE, [("unless modifierKinds.contains k do", "unless true do")], "H1"),
    ("去掉属性白名单", SHAPE, [("unless attributeNames.contains name do", "unless true do")], "H1"),
    ("去掉派生目标类白名单", SHAPE,
     [("unless target.isIdent && derivingClasses.contains (stripRoot target.getId.eraseMacroScopes) do",
       "unless true do")], "H1"),
    ("去掉 #guard_msgs 的规格限制", SHAPE, [("if kind == `Lean.guardMsgsCmd && !stx[2].isNone then",
                                    "if false && kind == `Lean.guardMsgsCmd && !stx[2].isNone then")], "H1"),
    ("禁用清单去掉 native_decide", SHAPE, [('"sorry", "admit", "native_decide",', '"sorry", "admit",')], "H1"),
    ("set_option 只查命令位置", SHAPE, [("if stx.getNumArgs ≥ 2 && stx[0].isAtom",
                                 "if stx.getKind == `Lean.Parser.Command.set_option && stx.getNumArgs ≥ 2 && stx[0].isAtom")],
     "H1"),
    ("解析失败不判红", SHAPE,
     [('r := { r with issues := r.issues.push (m.pos.line, "SHAPE_PARSE", s!"解析失败：{← m.data.toString}") }',
       "pure ()")], "H1,H2"),
    ("去掉 Chan/Defs 须 @[expose] public section", SHAPE,
     [("if (`Chan.Defs).isPrefixOf mod.toName && !r.exposes then", "if false then")], "H1b"),
    ("派生证书不比对位置（同模块即豁免）", "verification/auditor/Main.lean",
     [("spans.any (fun (m, a, b) => m == e.mod && le a p && le p b)", "spans.any (fun (m, _, _) => m == e.mod)")],
     "D2"),
    ("形状检查的沙箱里被审工作区可写", RUNNER,
     [('    binds = [("--ro-bind", ctx.audited, ctx.audited), ("--ro-bind", ctx.packages, ctx.packages),\n'
       '             ("--ro-bind", ctx.trusted_dir, ctx.trusted_dir)]\n    env = {"LEAN_PATH": ":".join(search), '
       '"LEAN_SYSROOT": ctx.prefix}\n    ctx.auditor_args = [x for rel',
       '    binds = [("--bind", ctx.audited, ctx.audited), ("--ro-bind", ctx.packages, ctx.packages),\n'
       '             ("--ro-bind", ctx.trusted_dir, ctx.trusted_dir)]\n    env = {"LEAN_PATH": ":".join(search), '
       '"LEAN_SYSROOT": ctx.prefix}\n    ctx.auditor_args = [x for rel')], "S22"),
    ("去掉旧式配置子句规则（独审 r1 甲-1）", SHAPE,
     [("if let some key := legacyConfig stx then", "if let some key := (none : Option String) then")], "H1"),
    ("第 7 步不要求第 5 步产出的派生凭证", RUNNER,
     [('if certificate is None or certificate != os.path.join(ctx.trusted_dir, "derived.json"):', "if False:")],
     "S32"),
    ("NO_CERTIFICATE 只查为空、不比路径（独审 r2 乙-C1）", RUNNER,
     [('if certificate is None or certificate != os.path.join(ctx.trusted_dir, "derived.json"):',
       "if certificate is None:")], "S33"),
    ("形状检查不核对每组文件行", RUNNER,
     [("if sorted(r[1] for r in done) != sorted(files) or any(f[2] not in files for f in findings):", "if False:")],
     "S5g"),
]


def mutants(packages, jobs):
    """在临时副本里逐一改弱，再以副本的自测跑相关骨架用例；副本未改弱时须全过，改弱后须失败。"""
    top = tempfile.mkdtemp(prefix="fm-runner-mutants-", dir=os.environ["TMPDIR"])
    ok = True
    try:
        def copy(tag):
            root = os.path.join(top, tag, "formal_math")
            for rel in ("lean-toolchain", "lake-manifest.json", "ChanTest/Probe.lean"):
                os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
                shutil.copy2(os.path.join(FM, rel), os.path.join(root, rel))
            for sub in ("runner", "precheck", "auditor", "must_green/known-not-covered/linarith-oracle-eval"):
                shutil.copytree(os.path.join(VERIFICATION, sub), os.path.join(root, "verification", sub),
                                ignore=shutil.ignore_patterns(".lake", "__pycache__"))
            return root

        def run_copy(root, cases):
            p = subprocess.run([sys.executable, "-I", os.path.join(root, "verification", "runner", "selftest.py"),
                                "--packages", packages, "--skip-corpus", "--jobs", str(jobs),
                                *(["--cases", cases] if cases else [])], capture_output=True)
            return p.returncode, p.stdout.decode(errors="replace")

        began = time.monotonic()
        rc, out = run_copy(copy("control"), None)
        total = re.findall(r"自测：(\d+)/(\d+)", out)
        good = rc == 0
        os.write(1, ("%s\t对照（未改弱）\t骨架全量 %s\t%.0fs\n" % ("通过" if good else "失败", total, time.monotonic() - began))
                 .encode())
        ok = ok and good
        for i, (label, rel, edits, cases) in enumerate(MUTANTS):
            root = copy("m%02d" % i)
            path = os.path.join(root, rel)
            text = open(path, encoding="utf-8").read()
            for old, new in edits:
                if text.count(old) != 1:
                    os.write(1, ("失败\t%s\t改弱点出现 %d 次\n" % (label, text.count(old))).encode())
                    ok = False
                    break
                text = text.replace(old, new)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                began = time.monotonic()
                rc, out = run_copy(root, cases)
                failed = [line.split("\t")[1] for line in out.splitlines() if line.startswith("失败\t")]
                good = rc != 0 and bool(failed)
                os.write(1, ("%s\t%s\t用例 %s\t%.0fs\t抓到：%s\n" % ("通过" if good else "失败", label, cases,
                                                                time.monotonic() - began, "；".join(failed) or "—"))
                         .encode())
                ok = ok and good
            rmtree(os.path.join(top, "m%02d" % i))
        os.write(1, ("弱化自测：%s（%d 种弱化）\n" % ("全部被抓到" if ok else "有弱化没被抓到", len(MUTANTS))).encode())
        return 0 if ok else 1
    finally:
        rmtree(top)


def main(argv):
    args, packages, jobs, only, cases_filter = list(argv), None, 1, None, None
    skip_corpus = discover = mutate = False
    while args:
        a = args.pop(0)
        if a == "--packages" and args:
            packages = os.path.realpath(args.pop(0))
        elif a == "--jobs" and args and args[0].isdigit() and int(args[0]) > 0:
            jobs = int(args.pop(0))
        elif a == "--only" and args:
            only = args.pop(0)
        elif a == "--cases" and args:
            cases_filter = set(args.pop(0).split(","))
        elif a == "--skip-corpus":
            skip_corpus = True
        elif a == "--discover":
            discover = True
        elif a == "--mutants":
            mutate = True
        else:
            os.write(2, ("用法：selftest.py --packages <依赖目录> [--jobs N] [--only 子串] [--cases 编号,…] "
                         "[--skip-corpus] [--discover] [--mutants]\n").encode())
            return 2
    if packages is None or not os.path.isdir(packages) or "TMPDIR" not in os.environ:
        os.write(2, "需要 --packages 与 TMPDIR（先 source scripts/fm_env.sh）\n".encode())
        return 2
    if mutate:
        return mutants(packages, jobs)
    tmp = tempfile.mkdtemp(prefix="fm-runner-selftest-", dir=os.environ["TMPDIR"])
    try:
        with open(os.path.join(tmp, "driver.py"), "w") as f:
            f.write(DRIVER)
        s = Suite(tmp, packages, warm=not skip_corpus)
        cases = [] if discover or only else [fn for cid, fn in skeleton(s)
                                             if cases_filter is None or cid in cases_filter]
        if not skip_corpus and cases_filter is None:
            cases += corpus(s, discover, only)
        began = time.monotonic()
        def guarded(c):
            try:
                return c()
            except Exception as e:  # noqa: BLE001  用例自身出错算失败，不中断其它用例
                os.write(1, ("失败\t%s\t用例自身出错：%s: %s\n" % (getattr(c, "__name__", "?"), type(e).__name__, e))
                         .encode("utf-8", "backslashreplace"))
                return False
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(guarded, cases))
        if discover:
            return 0
        os.write(1, ("自测：%d/%d 通过（%.0fs）\n" % (sum(results), len(results), time.monotonic() - began)).encode())
        return 0 if all(results) else 1
    finally:
        rmtree(tmp)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
