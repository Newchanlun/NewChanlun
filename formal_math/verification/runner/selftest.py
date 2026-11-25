#!/usr/bin/env python3
"""runner/run.py 的自测：现造小 git 仓库，经新入口跑整条流水线，断言整次运行的退出码与红码集合。

用法：selftest.py --packages <依赖目录> [--jobs N] [--only 子串] [--skip-corpus] [--discover]
- 骨架用例（S*）：阴性对照、R5-B1 劫持及其绕过预检的旁路、.gitattributes、输出篡改、快速失败、哨兵、参数与自举。
- 语料用例：`fixtures.tsv` 里每个标了期望的旧夹具。`--discover` 只打印实测结果（同表格式），不断言。
须先 `source scripts/fm_env.sh`，并整体包在 `flock <lean.lock> guard.sh` 里跑。"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
VERIFICATION = os.path.dirname(HERE)
FM = os.path.dirname(VERIFICATION)
RUN = os.path.join(HERE, "run.py")
ROOTS = ("Chan", "ChanTest", "ChanChallenge", "ChanDyn", "ChanExplore")
CONFIG_NAMES = ("lakefile.toml", "lake-manifest.json", "lean-toolchain")
GIT_ID = {"GIT_AUTHOR_NAME": "FM 自测", "GIT_AUTHOR_EMAIL": "fm-fixture@example.invalid",
          "GIT_COMMITTER_NAME": "FM 自测", "GIT_COMMITTER_EMAIL": "fm-fixture@example.invalid",
          "GIT_AUTHOR_DATE": "2026-11-26T00:00:00Z", "GIT_COMMITTER_DATE": "2026-11-26T00:00:00Z",
          "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "PATH": os.environ["PATH"]}
DRIVER = r'''
import importlib.util, sys
spec = importlib.util.spec_from_file_location("fm_run", sys.argv[1])
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)
mode, argv = sys.argv[2], sys.argv[3:]
orig = run.sandbox
def patched(ctx, cmd, *a, **k):
    p = orig(ctx, cmd, *a, **k)
    if cmd[0] != ctx.auditor:
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

    def commit(self, files, parent=None):
        """files：{相对仓库根的路径: 字节}；返回提交对象名。"""
        tree = {}
        for path, data in files.items():
            node = tree
            *dirs, name = path.split("/")
            for d in dirs:
                node = node.setdefault(d, {})
            node[name] = self.git("hash-object", "-w", "--no-filters", "--stdin", data=data).strip()

        def mktree(node):
            rows = b""
            for name, value in sorted(node.items()):
                kind, mode = ("tree", "040000") if isinstance(value, dict) else ("blob", "100644")
                oid = mktree(value) if isinstance(value, dict) else value
                rows += b"%s %s %s\t%s\0" % (mode.encode(), kind.encode(), oid, name.encode())
            return self.git("mktree", "-z", data=rows).strip()

        args = ["commit-tree", mktree(tree).decode(), "-m", "自测"] + (["-p", parent] if parent else [])
        return self.git(*args).strip().decode()


def lakefile(files):
    """按提交里实有的内容根生成构建配置：根模块文件进 roots 与 globs，子目录进 globs（Lake 的 glob 要求目录存在）。"""
    libs = []
    for r in ROOTS:
        has_file, has_dir = "formal_math/%s.lean" % r in files, any(p.startswith("formal_math/%s/" % r) for p in files)
        if has_file or has_dir:
            libs.append((r, [r] if has_file else [], ([r] if has_file else []) + ([r + ".+"] if has_dir else [])))
    quote = lambda xs: ", ".join('"%s"' % x for x in xs)
    out = 'name = "fixture"\ndefaultTargets = [%s]\n\n' % quote(r for r, _, _ in libs)
    out += ('[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\nlinter.unusedVariables = true\n\n'
            '[[require]]\nname = "mathlib"\ngit = "https://github.com/leanprover-community/mathlib4.git"\n'
            'rev = "v4.36.0"\n')
    for r, roots, globs in libs:
        out += '\n[[lean_lib]]\nname = "%s"\nroots = [%s]\nglobs = [%s]\n' % (r, quote(roots), quote(globs))
    return out.encode()


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


def template(extra=None, gate=True, placeholders=True):
    files = trusted_files() if gate else {}
    files.update({
        "formal_math/lean-toolchain": read(os.path.join(FM, "lean-toolchain")),
        "formal_math/lake-manifest.json": read(os.path.join(FM, "lake-manifest.json")),
        "formal_math/Chan.lean": b"module\n",
        "formal_math/ChanTest/Probe.lean": read(os.path.join(FM, "ChanTest", "Probe.lean")),
        "formal_math/statement-lock.json": b"{}\n",
    })
    if placeholders:
        for r in ("Chan", "ChanChallenge", "ChanDyn", "ChanExplore"):
            files["formal_math/%s/Base.lean" % r] = b"module\n"
    files.update(extra or {})
    files["formal_math/lakefile.toml"] = lakefile(files)
    return files


class Suite:
    def __init__(self, tmp, packages):
        self.tmp, self.packages = tmp, packages
        self.repo = Repo(os.path.join(tmp, "仓库 repo"))
        self.base_files = template()
        self.base = self.repo.commit(self.base_files)
        self.counter = 0
        self.warm = self.warm_auditor()

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

    def run(self, name, head, branch="proof/selftest", base=None, extra=(), mode=None, keep=False, workdir=None,
            repo=None):
        work = workdir or self.workdir(name)
        argv = ["--repo", (repo or self.repo).path, "--base", base or self.base, "--head", head, "--branch", branch,
                "--workdir", work, "--packages", self.packages, *extra]
        cmd = [sys.executable, "-I", RUN, *argv] if mode is None else \
            [sys.executable, "-I", os.path.join(self.tmp, "driver.py"), RUN, mode, *argv]
        p = subprocess.run(cmd, capture_output=True, env={"PATH": os.environ["PATH"],
                                                          "HOME": os.environ.get("HOME", "/")})
        out, err = p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
        reds = {line.split(" ")[3] for line in out.splitlines() if line.startswith("FM RED ")}
        steps = re.findall(r"^FM STEP (\d) (\S+) (\S+)", out, re.M)
        faults = re.findall(r"^FM FAULT \S+ (\S+)", err, re.M)
        result = dict(rc=p.returncode, reds=reds, steps=steps, faults=faults, out=out, err=err, work=work)
        if not keep and os.path.isdir(work):
            shutil.rmtree(work)
        return result


def check(name, ok, res, detail=""):
    shown = "rc=%s 红码=%s 故障=%s" % (res["rc"], ",".join(sorted(res["reds"])) or "—", ",".join(res["faults"]) or "—")
    os.write(1, ("%s\t%s\t%s\t%s\n" % ("通过" if ok else "失败", name, shown, detail)).encode())
    if not ok:
        os.write(2, (res["out"][-3000:] + res["err"][-3000:]).encode())
    return ok


def last_step(res):
    return res["steps"][-1][1] if res["steps"] else "-"


# ---- 骨架用例 ----

def skeleton(s):
    cases = []
    ok_thm = {"formal_math/Chan/Thm/Ok.lean": b"module\n\npublic section\n\ntheorem ok : 1 + 1 = 2 := rfl\n"}
    green = s.repo.commit({**s.base_files, **ok_thm}, s.base)

    def s1():
        r = s.run("S1-green", green)
        good = r["rc"] == 0 and not r["reds"] and [x[2] for x in r["steps"]] == ["GREEN"] * 7 and \
            "SHAPE 未安装" in r["out"] and r["out"].startswith("FM MODE baseline ")
        return check("S1 阴性对照：未改动的证明提交七步全绿", good, r)
    cases.append(s1)

    b1 = {"formal_math/" + rel: read(os.path.join(HERE, "selftest-cases", "r5-b1", rel))
          for rel in ("lakefile.toml", "ChanExplore/FakeAudit.lean", "Chan/Thm/Bogus.lean")}
    hijack = s.repo.commit({**s.base_files, **b1}, s.base)

    def s2():
        r = s.run("S2-r5b1", hijack, branch="infra/hijack", extra=["--trusted-change-approved"], keep=True)
        good = r["rc"] == 1 and r["reds"] == {"PATH_SCOPE"} and last_step(r) == "precheck" and \
            len(r["steps"]) == 1 and not os.path.exists(os.path.join(r["work"], "trusted"))
        shutil.rmtree(r["work"])
        return check("S2 R5-B1 劫持在第 1 步预检判红，后续步骤没跑", good, r)
    cases.append(s2)

    def s3():
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
    cases.append(s3)

    attrs = b"formal_math/Chan/Thm/** export-ignore\n*.lean filter=fmevil eol=crlf\n"
    base2 = s.repo.commit({**s.base_files, ".gitattributes": attrs}, s.base)
    attr_file = b"module\n\npublic section\n\ntheorem attr_kept : True := trivial\n"
    head2 = s.repo.commit({**s.base_files, ".gitattributes": attrs, "formal_math/Chan/Thm/Attr.lean": attr_file}, base2)

    def s4():
        s.repo.git("config", "filter.fmevil.smudge", "sed s/theorem/axiom/")
        archived = subprocess.run(["git", "-C", s.repo.path, "archive", "--format=tar", head2, "formal_math/Chan"],
                                  capture_output=True, env=GIT_ID).stdout
        r = s.run("S4-gitattributes", head2, base=base2, keep=True)
        got = os.path.join(r["work"], "audited", "Chan", "Thm", "Attr.lean")
        same = os.path.isfile(got) and read(got) == attr_file and \
            (os.stat(got).st_mode & 0o7777) == 0o644
        good = r["rc"] == 0 and same and b"Attr.lean" not in archived
        shutil.rmtree(r["work"])
        return check("S4 .gitattributes（export-ignore、filter、eol）不影响取料：文件在、逐字节相同、模式 0644", good, r,
                     "对照：git archive %s 该文件" % ("不含" if b"Attr.lean" not in archived else "含"))
    cases.append(s4)

    for mode, fault in (("env-count", "MODULE_COUNT"), ("headers-garbage", "AUDITOR_OUTPUT"),
                        ("headers-drop", "AUDITOR_OUTPUT"), ("env-verdict", "AUDITOR_OUTPUT"),
                        ("env-exit", "AUDITOR_OUTPUT")):
        def s5(mode=mode, fault=fault):
            r = s.run("S5-" + mode, green, mode=mode)
            good = r["rc"] == 2 and r["faults"] == [fault] and "RESULT GREEN" not in r["out"]
            return check("S5 审计程序输出被篡改（%s）退 2" % mode, good, r)
        cases.append(s5)

    edge = s.repo.commit({**s.base_files, "formal_math/Chan/Thm/Edge.lean":
                          b"module\n\npublic import ChanExplore.Base\n"}, s.base)

    def s6a():
        r = s.run("S6-header-red", edge, keep=True)
        good = r["rc"] == 1 and r["reds"] == {"IMPORT_EDGE", "IMPORT_SOURCE"} and [x[1] for x in r["steps"]] == list(
            ("precheck", "fetch", "auditor", "headers")) and \
            not os.path.exists(os.path.join(r["work"], "audited", ".lake"))
        shutil.rmtree(r["work"])
        return check("S6a 第 4 步判红后第 5–7 步没跑（无步骤行，构建目录不存在）", good, r)
    cases.append(s6a)

    broken = s.repo.commit({**s.base_files, "formal_math/Chan/Thm/Broken.lean":
                            b"module\n\npublic section\n\ntheorem broken : 1 = 2 := rfl\n"}, s.base)

    def s6b():
        r = s.run("S6-build-red", broken)
        good = r["rc"] == 1 and r["reds"] == {"BUILD_WFAIL"} and last_step(r) == "build" and len(r["steps"]) == 6
        return check("S6b 第 6 步构建判红后第 7 步没跑", good, r)
    cases.append(s6b)

    def s7():
        work = s.workdir("S7-sentinel")
        repo = Repo(os.path.join(s.tmp, "哨兵 repo"))
        targets = [os.path.join(s.tmp, "sentinel-tmp"), os.path.join(work, "trusted", "sentinel-trusted"),
                   os.path.join(repo.path, "sentinel-repo"), os.path.join(s.packages, "sentinel-packages")]
        writes = "".join('  try IO.FS.writeFile "%s" "x" catch _ => pure ()\n' % t
                         for t in targets[:3] + [".lake/packages/sentinel-packages"])
        lean = ("module\n\npublic section\n\n#eval show IO Unit from do\n%s"
                '  IO.FS.writeFile ".lake/inside-ok" "x"\n\n'
                'initialize IO.FS.writeFile "%s" "x"\n' % (writes, os.path.join(s.tmp, "sentinel-init"))).encode()
        user = b"module\n\npublic import ChanExplore.Sentinel\n"
        base = repo.commit(s.base_files)
        head = repo.commit({**s.base_files, "formal_math/ChanExplore/Sentinel.lean": lean,
                            "formal_math/ChanExplore/User.lean": user}, base)
        before = snapshot(repo.path)
        r = s.run("S7-sentinel", head, base=base, keep=True, workdir=work, repo=repo)
        leaked = [t for t in targets + [os.path.join(s.tmp, "sentinel-init")] if os.path.lexists(t)]
        if os.path.lexists(targets[3]):
            os.unlink(targets[3])  # 只删本自测造的哨兵，不动共享依赖目录里的其它东西
        inside = os.path.isfile(os.path.join(work, "audited", ".lake", "inside-ok"))
        good = r["rc"] == 0 and not leaked and inside and snapshot(repo.path) == before
        shutil.rmtree(work)
        return check("S7 被审代码在构建期执行，但被审工作区之外没有被写入（四个哨兵、初始化器、仓库快照）", good, r,
                     "工作区内对照=%s 外泄=%s" % (inside, leaked or "无"))
    cases.append(s7)

    def s8():
        results = []
        w = s.workdir("S8-usage")
        base_args = ["--repo", s.repo.path, "--base", s.base, "--head", green, "--branch", "proof/x",
                     "--workdir", w, "--packages", s.packages]
        for label, argv in (("缩写", ["--wor", w] + base_args[:8]), ("等号", ["--until=3"] + base_args),
                            ("重复", base_args + ["--repo", s.repo.path]), ("缺依赖目录", base_args[:10]),
                            ("步号越界", base_args + ["--until", "8"]), ("未知开关", ["--approve"] + base_args),
                            ("工作目录在仓库里", base_args[:9] + [os.path.join(s.repo.path, "w")] + base_args[10:])):
            p = subprocess.run([sys.executable, "-I", RUN, *argv], capture_output=True)
            results.append(p.returncode == 2 and b"FM RESULT" not in p.stdout)
        os.makedirs(w)
        open(os.path.join(w, "x"), "w").close()
        p = subprocess.run([sys.executable, "-I", RUN, *base_args], capture_output=True)
        results.append(p.returncode == 2 and b"WORKDIR" in p.stderr)
        shutil.rmtree(w)
        res = dict(rc="-", reds=set(), faults=[], out="", err="")
        return check("S8 参数与前置条件：缩写、等号、重复、缺项、越界、未知开关、工作目录在仓库里或非空都退 2",
                     all(results), res, "逐项=%s" % results)
    cases.append(s8)

    def s9():
        r = s.run("S9-until3", green, extra=["--until", "3"])
        good = r["rc"] == 2 and [x[2] for x in r["steps"]] == ["GREEN"] * 3 and "RESULT PARTIAL" in r["out"]
        return check("S9 --until 3 全绿也退 2（未做完整判定）", good, r)
    cases.append(s9)

    def s10():
        r = s.run("S10-until1-red", hijack, branch="infra/hijack", extra=["--until", "1", "--trusted-change-approved"])
        return check("S10 --until 1 遇红仍退 1", r["rc"] == 1 and r["reds"] == {"PATH_SCOPE"}, r)
    cases.append(s10)

    bare = template(gate=False)
    bare_base = s.repo.commit(bare)
    bare_head = s.repo.commit({**bare, **ok_thm}, bare_base)

    def s11():
        r = s.run("S11-no-trusted", bare_head, base=bare_base)
        return check("S11 基线缺受信代码且没给自举开关：退 2", r["rc"] == 2 and r["faults"] == ["NO_TRUSTED_CODE"], r)
    cases.append(s11)

    def s12():
        r = s.run("S12-bootstrap", bare_head, base=bare_base, extra=["--bootstrap-trusted-from", s.base])
        good = r["rc"] == 0 and r["out"].startswith("FM MODE bootstrap trusted=%s " % s.base) and "自举模式" in \
            r["out"].splitlines()[0]
        return check("S12 自举模式：首行写明自举，受信代码取自指定提交，全绿", good, r)
    cases.append(s12)

    stale = dict(s.base_files)
    stale["formal_math/verification/runner/run.py"] += b"# drift\n"
    stale_base = s.repo.commit(stale)

    def s13():
        r = s.run("S13-runner-mismatch", stale_base, base=stale_base)
        return check("S13 正在运行的 run.py 与受信提交不同：退 2", r["rc"] == 2 and r["faults"] == ["RUNNER_MISMATCH"], r)
    cases.append(s13)
    return cases


def snapshot(root):
    return sorted((os.path.relpath(os.path.join(d, n), root), os.lstat(os.path.join(d, n)).st_mtime_ns)
                  for d, _, ns in os.walk(root) for n in ns)


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


def main(argv):
    args, packages, jobs, only, skip_corpus, discover = list(argv), None, 1, None, False, False
    while args:
        a = args.pop(0)
        if a == "--packages" and args:
            packages = os.path.realpath(args.pop(0))
        elif a == "--jobs" and args and args[0].isdigit() and int(args[0]) > 0:
            jobs = int(args.pop(0))
        elif a == "--only" and args:
            only = args.pop(0)
        elif a == "--skip-corpus":
            skip_corpus = True
        elif a == "--discover":
            discover = True
        else:
            os.write(2, ("用法：selftest.py --packages <依赖目录> [--jobs N] [--only 子串] [--skip-corpus] "
                         "[--discover]\n").encode())
            return 2
    if packages is None or not os.path.isdir(packages) or "TMPDIR" not in os.environ:
        os.write(2, "需要 --packages 与 TMPDIR（先 source scripts/fm_env.sh）\n".encode())
        return 2
    tmp = tempfile.mkdtemp(prefix="fm-runner-selftest-", dir=os.environ["TMPDIR"])
    try:
        with open(os.path.join(tmp, "driver.py"), "w") as f:
            f.write(DRIVER)
        s = Suite(tmp, packages)
        cases = [] if discover else [c for c in skeleton(s) if only is None]
        if not skip_corpus:
            cases += corpus(s, discover, only)
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(lambda c: c(), cases))
        if discover:
            return 0
        os.write(1, ("自测：%d/%d 通过\n" % (sum(results), len(results))).encode())
        return 0 if all(results) else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
