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
import importlib.util, json, os, sys
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
    if mode == "probe" and (cmd[:2] == ["lake", "build"] or cmd[0] == getattr(ctx, "auditor", None) and cmd[1] == "env"):
        probe(ctx, "build" if cmd[0] == "lake" else "env", binds, env, cwd)
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
    p.stdout = b"".join(l + b"\n" for l in lines)
    return p
run.sandbox = patched
if mode == "timeout":
    run.TIMEOUT["build"] = 30
steps = list(run.STEP_FUNCS)
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
            repo=None, lite=False, env=None, argv=None):
        work = workdir or self.workdir(name)
        if argv is None:
            argv = ["--repo", (repo or self.repo).path, "--base", base or (self.lite_base if lite else self.base),
                    "--head", head, "--branch", branch, "--workdir", work,
                    "--packages", self.fake_packages if lite else self.packages, *extra]
        cmd = [sys.executable, "-I", RUN, *argv] if mode is None else \
            [sys.executable, "-I", os.path.join(self.tmp, "driver.py"), RUN, mode, *argv]
        p = subprocess.run(cmd, capture_output=True, env={"PATH": os.environ["PATH"], CANARY: "leak-canary",
                                                          "HOME": os.environ.get("HOME", "/"), **(env or {})})
        res = parse_result(p)
        res["work"] = work
        if not keep and os.path.isdir(work):
            shutil.rmtree(work)
        return res


def parse_result(p):
    out, err = p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    reds = {line.split(" ")[3] for line in out.splitlines() if line.startswith("FM RED ")}
    steps = re.findall(r"^FM STEP (\d) (\S+) (\S+)", out, re.M)
    faults = re.findall(r"^FM FAULT \S+ (\S+)", err, re.M)
    return dict(rc=p.returncode, reds=reds, steps=steps, faults=faults, out=out, err=err,
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
            "SHAPE 未安装" in r["out"] and r["out"].startswith("FM MODE baseline ")
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
        shutil.rmtree(r["work"])
        return check("S2 R5-B1 劫持在第 1 步预检判红，后续步骤没跑", good, r)

    @case("S3")
    def _():
        r = s.run("S3-r5b1-bypass", hijack, branch="infra/hijack", mode="bypass", keep=True)
        work = r["work"]
        binary = os.path.join(work, "trusted", "verification", "auditor", ".lake", "build", "bin", "fm_audit")
        planted = [os.path.join(d, n) for root in (s.tmp, s.repo.path) for d, _, ns in os.walk(root)
                   for n in ns if n == "sentinel_perfect_6of6.txt"]
        good = r["rc"] == 1 and r["reds"] == {"ENV_AXIOM", "ENV_AXIOM_DEP"} and last_step(r) == "env" and \
            r["steps"][0][:2] == ("2", "fetch") and ("binary=%s " % binary) in r["out"] and \
            read(os.path.join(work, "audited", "lakefile.toml")) == s.base_files["formal_math/lakefile.toml"] and \
            not planted
        shutil.rmtree(work)
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
        shutil.rmtree(r["work"])
        return check("S4 .gitattributes（export-ignore、filter、eol）不影响取料：文件在、逐字节相同、模式 0644", good, r,
                     "对照：git archive %s 该文件" % ("不含" if b"Attr.lean" not in archived else "含"))

    for cid, mode, fault in (("S5a", "env-count", "MODULE_COUNT"), ("S5b", "headers-garbage", "AUDITOR_OUTPUT"),
                             ("S5c", "headers-drop", "AUDITOR_OUTPUT"), ("S5d", "env-verdict", "AUDITOR_OUTPUT"),
                             ("S5e", "env-exit", "AUDITOR_OUTPUT")):
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
        shutil.rmtree(r["work"])
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
        r = s.run("S7-sentinel", head, base=base, keep=True, workdir=work, repo=repo, lite=True)
        leaked = [t for t in targets if os.path.lexists(t)]
        audited = os.path.join(work, "audited")
        untouched = all(os.path.isfile(os.path.join(audited, p)) and
                        read(os.path.join(audited, p)) == files["formal_math/" + p]
                        for p in ("lake-manifest.json", "Chan/Base.lean"))
        inside = os.path.isfile(os.path.join(audited, ".lake", "inside-ok"))
        good = r["rc"] == 0 and not leaked and inside and untouched and snapshot(repo.path) == before
        shutil.rmtree(work)
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
            shutil.rmtree(r2["work"])
            ok2 = check("%s 同一提交绕过预检：取料按对象读取时失败退 2，不写出被审工作区（纵深防御）" % cid, good, r2)
            return ok1 and ok2

    init_mod = (M + 'meta initialize\n  IO.eprintln s!"FM-SELFTEST-INIT-RAN app={← IO.appPath}"\n').encode()
    init_head = s.lite({"formal_math/ChanExplore/InitMod.lean": init_mod,
                        "formal_math/ChanExplore/InitUser.lean": b"module\n\npublic import ChanExplore.InitMod\n"})

    @case("S17")
    def _():
        r = s.run("S17-init", init_head, lite=True)
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
        r = s.run("S18-signal", kill, lite=True)
        good = r["rc"] == 2 and r["faults"] == ["SIGNAL"] and r["steps"][-1][1:] == ("build", "FAULT")
        return check("S18 第 6 步沙箱里的 lake 被信号杀死：无法判定退 2，不报 BUILD_WFAIL", good, r)

    spin = s.lite({"formal_math/ChanExplore/Spin.lean": (
        M + '#eval show IO Unit from do\n  for _ in [0:100000] do\n    IO.sleep 200\n'
            '    let h ← IO.FS.Handle.mk ".lake/tick" .append\n    h.putStrLn "t"\n    h.flush\n').encode()})

    @case("S19")
    def _():
        r = s.run("S19-timeout", spin, mode="timeout", keep=True, lite=True)
        tick = os.path.join(r["work"], "audited", ".lake", "tick")
        size = os.path.getsize(tick) if os.path.exists(tick) else -1
        time.sleep(2)
        after = os.path.getsize(tick) if os.path.exists(tick) else -1
        good = r["rc"] == 2 and r["faults"] == ["BUILD"] and "超时" in r["err"] and size > 0 and size == after
        shutil.rmtree(r["work"])
        return check("S19 第 6 步超时（自测把时限改成 30 秒）：退 2，沙箱里的进程随之结束", good, r,
                     "tick 字节数 %d → %d（2 秒后）" % (size, after))

    plant = s.lite({"formal_math/ChanExplore/Plant.lean": (
        M + '#eval show IO Unit from do\n'
            '  IO.FS.createDirAll ".lake/build/lib/lean/Init"\n'
            '  IO.FS.writeFile ".lake/build/lib/lean/Init/Fake.olean" ""\n'
            '  IO.FS.createDirAll ".lake/build/lib/lean/Chan"\n'
            '  IO.FS.writeFile ".lake/build/lib/lean/Chan/Ghost.olean" ""\n'
            '  let _ ← IO.Process.output {cmd := "ln", args := #["-s", "/etc/hostname", '
            '".lake/build/lib/lean/Chan/Link.olean"]}\n').encode()})

    @case("S20")
    def _():
        r = s.run("S20-artifacts", plant, lite=True)
        good = r["rc"] == 1 and r["reds"] == {"ARTIFACT_ROOT", "EXTRA_ARTIFACT"} and last_step(r) == "build"
        return check("S20 构建在产物目录里放 Init、没有源码的模块与符号链接：第 6 步 ARTIFACT_ROOT、EXTRA_ARTIFACT", good, r)

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
        b, e = facts("build"), facts("env")
        good = r["rc"] == 0 and b[0] == ["lo"] and e[0] == ["lo"] and b[1] is not None and b[1] <= allowed and \
            e[1] is not None and e[1] <= allowed and b[2] == set() and e[2] == {"trusted"} and \
            b[3] == {"lake"} and e[3] == set()
        return check("S22 沙箱探针（第 6、7 步同挂载同环境）：只有回环网卡、环境已清、宿主机目录与仓库不可见、"
                     "第 6 步只有 .lake 可写、第 7 步全只读、受信目录第 6 步不可见", good, r,
                     "第6步=%s 第7步=%s" % (b, e))

    @case("S24")
    def _():
        copy = os.path.join(s.tmp, "isolated-copy")
        os.makedirs(copy, exist_ok=True)
        shutil.copy2(RUN, copy)
        sentinel = os.path.join(s.tmp, "json-py-ran")
        with open(os.path.join(copy, "json.py"), "w") as f:
            f.write("open(%r, 'w').close()\nimport sys\nsys.stdout.write('FM RESULT GREEN forged\\n')\n"
                    "raise SystemExit(0)\n" % sentinel)
        res = parse_result(subprocess.run([sys.executable, os.path.join(copy, "run.py"), "--repo", s.repo.path],
                                          capture_output=True, env={"PATH": os.environ["PATH"]}))
        good = res["rc"] == 2 and res["faults"] == ["NOT_ISOLATED"] and not os.path.exists(sentinel)
        return check("S24 不带 -I 运行：同目录的 json.py 没有被执行，退 2", good, res)

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
        r = s.run("E2-decl-names", head, lite=True)
        good = r["rc"] == 1 and r["reds"] == {"ENV_AXIOM", "ENV_AXIOM_DEP", "ENV_UNSAFE"}
        return check("E2 公理名、声明名带换行与控制符（环境层红行的对象栏与说明栏）", good, r)

    for cid, lock, rc, want in (("E3", b'{"a\\nFM RESULT GREEN": "x"}', 1, "LOCK_REMOVED"),
                                ("E4", b'{"\\ud800": "x"}', 2, "INPUT"),
                                ("E5", b'{"\\ud800": "x", "\\ud800": "y"}', 2, "INPUT"),
                                ("E6", b'{"k": "\\ud800"}', 2, "INPUT"),
                                ("E7", b'{"k": NaN}', 2, "INPUT")):
        @case(cid)
        def _(cid=cid, lock=lock, rc=rc, want=want):
            head = s.lite({"formal_math/statement-lock.json": lock})
            r = s.run(cid + "-lock", head, branch="decl/lock", lite=True)
            good = r["rc"] == rc and (r["reds"] == {want} if rc == 1 else r["faults"] == [want])
            return check("%s 锁文件 %s：%s" % (cid, lock.decode(), "红行转义" if rc == 1 else "无法判定退 2，不回溯"),
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
        r = s.run("E10-lake-log", head, lite=True)
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
    return cases


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


def corpus_case(s, fixture):
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
        return s.run(fixture, head, mode=warm), "base=模板 head=模板+夹具"
    # 只有内容的夹具：基线与被审是同一提交（预检因受管路径无改动而绿），配置按夹具实有的内容根生成。
    files = template(overlay, placeholders=False)
    head = s.repo.commit(files)
    return s.run(fixture, head, base=head, mode=warm), "base=head=模板+夹具"


def corpus(s, discover, only):
    if discover:
        fixtures = sorted(os.path.relpath(os.path.join(VERIFICATION, c, g, f), VERIFICATION)
                          for c in ("must_red", "must_green", "must_unknown")
                          for g in sorted(os.listdir(os.path.join(VERIFICATION, c))) if g != "g6b"
                          for f in sorted(os.listdir(os.path.join(VERIFICATION, c, g))))
        rows = [dict(fixture=f) for f in fixtures]
    else:
        rows = [r for r in load_table() if r["rc"] != "-"]
    rows = [r for r in rows if only is None or only in r["fixture"]]

    def one(row):
        res, how = corpus_case(s, row["fixture"])
        step = last_step(res) if res["rc"] == 1 else "-"
        if discover:
            line = "%s\t?\t%s\t%s\t%s\t%s\n" % (row["fixture"], res["rc"], step,
                                                ",".join(sorted(res["reds"])) or "-", how)
            os.write(1, line.encode())
            return True
        good = str(res["rc"]) == row["rc"] and step == row["step"] and res["reds"] == row["codes"]
        return check("语料 %s（%s）" % (row["fixture"], row["owner"]), good, res,
                     "期望 rc=%s 步=%s 码=%s" % (row["rc"], row["step"], ",".join(sorted(row["codes"])) or "—"))
    return [lambda row=row: one(row) for row in rows]


# ---- 弱化自测 ----

RUNNER = "verification/runner/run.py"
MUTANTS = [
    ("去掉 RUNNER_MISMATCH", RUNNER, [("if me != object_at(ctx, ctx.trusted, TRUSTED_CODE[0]):", "if False:")],
     "S13"),
    ("去掉模块数比对", RUNNER, [("if result[3] != len(ctx.modules):", "if False:")], "S5a"),
    ("不核对判定、发现与退出码一致", RUNNER,
     [("(result[2] == \"red\") != bool(findings) or p.returncode != (1 if findings else 0)", "False")], "S5d,S5e"),
    ("判红后继续跑下一步", RUNNER, [("            if reds:\n                out(\"RESULT\", \"RED\"",
                              "            if reds and n == 7:\n                out(\"RESULT\", \"RED\"")], "S2,S6a"),
    ("第 6 步受信目录可见可写", RUNNER, [('("--ro-bind", ctx.packages, os.path.join(lake_dir, "packages"))]',
                                 '("--ro-bind", ctx.packages, os.path.join(lake_dir, "packages")), '
                                 '("--bind", ctx.trusted_dir, ctx.trusted_dir)]')], "S22"),
    ("第 6 步被审工作区整个可写", RUNNER, [('binds = [("--ro-bind", ctx.audited, ctx.audited), ("--bind", lake_dir, lake_dir),',
                                   'binds = [("--bind", ctx.audited, ctx.audited), ("--bind", lake_dir, lake_dir),')],
     "S7,S22"),
    ("第 7 步被审工作区可写", RUNNER,
     [('binds = [("--ro-bind", ctx.audited, ctx.audited), ("--ro-bind", ctx.packages, ctx.packages),',
       'binds = [("--bind", ctx.audited, ctx.audited), ("--ro-bind", ctx.packages, ctx.packages),')], "S22"),
    ("沙箱不断网", RUNNER, [('b"--unshare-all"', 'b"--unshare-user", b"--unshare-pid", b"--unshare-ipc", '
                                              'b"--unshare-uts", b"--unshare-cgroup"')], "S22"),
    ("沙箱不清环境（去掉 --clearenv 且继承调用方环境）", RUNNER,
     [('args.append(b"--clearenv")', 'args += []'),
      ('env={"PATH": GIT_ENV["PATH"]})\n    if p.returncode >= 128', 'env=dict(os.environ))\n    if p.returncode >= 128')],
     "S22"),
    ("沙箱不遮宿主机目录", RUNNER, [('for hidden in ("/home", "/root", "/run", "/var", "/tmp", ctx.workdir):',
                               'for hidden in ("/tmp",):')], "S7,S22"),
    ("去掉 ARTIFACT_ROOT", RUNNER, [('if name.split(".")[0] not in ROOT_NAMES:', "if False:"),
                                   ("if os.path.islink(full):", "if False:")], "S20"),
    ("去掉 NO_ARTIFACT", RUNNER, [("for module in sorted(set(ctx.modules) - built):", "for module in []:")], "S21"),
    ("去掉 EXTRA_ARTIFACT", RUNNER, [("for module in sorted(built - set(ctx.modules)):", "for module in []:")], "S20"),
    ("信号死亡不归入无法判定", RUNNER, [("if p.returncode >= 128 or p.returncode < 0:", "if p.returncode < 0:")], "S18"),
    ("输出不转义", RUNNER, [("if 0x21 <= c < 0x7F and c != 0x5C or (spaces and c == 0x20):", "if True:")],
     "E1,E2,E3,E8,E10"),
    ("JSON 不拒孤立代理项", RUNNER, [("if not no_surrogates(value):", "if False:")], "E6"),
    ("不查隔离模式", RUNNER, [("if not sys.flags.isolated:", "if False:")], "S24"),
    ("审计程序加载扩展并运行初始化器", "verification/auditor/Main.lean",
     [("  let env := (← Lean.importModules (mods.map fun m => { module := m }) {}\n    (level := .private))",
       "  Lean.enableInitializersExecution\n"
       "  let env := (← Lean.importModules (mods.map fun m => { module := m }) {}\n"
       "    (level := .private) (loadExts := true))")], "S17"),
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
            for sub in ("runner", "precheck", "auditor"):
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
            shutil.rmtree(os.path.join(top, "m%02d" % i), ignore_errors=True)
        os.write(1, ("弱化自测：%s（%d 种弱化）\n" % ("全部被抓到" if ok else "有弱化没被抓到", len(MUTANTS))).encode())
        return 0 if ok else 1
    finally:
        shutil.rmtree(top, ignore_errors=True)


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
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
