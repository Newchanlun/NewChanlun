"""一轮对抗脚本（2312-review-tmp/run_adversarial.py）的精确复跑副本。
所有实验用例与一轮逐字一致，仅将临时沙箱与产物输出目录重定向至 /Volumes/AgentStorage/fm/r2/2312-r2-tmp/，
避免污染一轮审阅目录。
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

WT = Path("/Users/silencehan/.t3/worktrees/NewChanlun/infra-2312-b-env-gates-2428b08ce810d112")
VER = WT / "formal_math/verification"
BASE_TMP = Path("/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r1_sandbox")
PKG_LINK = (WT / "formal_math/.lake/packages").resolve()

ENV = os.environ.copy()
ENV["TMPDIR"] = "/Volumes/AgentStorage/fm/r2/2312-r2-tmp/tmp"
ENV["PATH"] = f"{Path.home() / '.elan/bin'}:{ENV.get('PATH', '')}"
ENV.pop("GITHUB_HEAD_REF", None)


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=AdvTest",
         "-c", "user.email=adv@example.invalid", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )


def make_pkg(repo: Path, files: dict[str, str], uses_mathlib=False, extra_libs=(),
             custom_lakefile: str | None = None, git_branch: str | None = None,
             pre_git_files: dict[str, str] | None = None):
    if repo.exists():
        shutil.rmtree(repo)
    fm = repo / "formal_math"
    vdir = fm / "verification"
    vdir.mkdir(parents=True)
    for fn in ("run_gates.py", "pins.json", "Audit.lean", "EnvGates.lean", "garbage-signoffs.yaml"):
        shutil.copy2(VER / fn, vdir)
    for fn in ("lean-toolchain", "lake-manifest.json", "formalization.yaml", "statement-lock.json"):
        shutil.copy2(WT / "formal_math" / fn, fm)
    (fm / "ChanTest").mkdir()
    shutil.copy2(WT / "formal_math/ChanTest/Probe.lean", fm / "ChanTest/Probe.lean")
    (fm / "Chan.lean").write_text("module\n")

    libs = {"Chan", "ChanTest", *extra_libs}
    for rel in files:
        if rel.startswith("formal_math/") and rel.endswith(".lean"):
            p = Path(rel).relative_to("formal_math")
            libs.add(p.parts[0].removesuffix(".lean"))
    for lib in libs:
        (fm / lib).mkdir(exist_ok=True)

    if uses_mathlib:
        (fm / ".lake").mkdir(exist_ok=True)
        (fm / ".lake/packages").symlink_to(PKG_LINK)

    if custom_lakefile is not None:
        (fm / "lakefile.toml").write_text(custom_lakefile)
    else:
        (fm / "lakefile.toml").write_text(
            'name = "adv"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
            '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
            'linter.unusedVariables = true\n'
            + ('\n[[require]]\nname = "mathlib"\ngit = "https://github.com/leanprover-community/mathlib4.git"\n'
               'rev = "v4.36.0"\n' if uses_mathlib else "")
            + "".join(
                f'\n[[lean_lib]]\nname = "{lib}"\nglobs = ["{lib}.*"]\n'
                for lib in sorted(libs)
            )
            + '\n[[lean_exe]]\nname = "fm_audit"\nroot = "verification.Audit"\n'
            + '\n[[lean_lib]]\nname = "FMEnvGates"\nroots = ["verification.EnvGates"]\n'
        )

    if pre_git_files:
        for rel, content in pre_git_files.items():
            dst = repo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(content)

    if git_branch:
        git(repo, "init", "-q", "-b", "main")
        git(repo, "add", "formal_math")
        git(repo, "commit", "-qm", "base")
        git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(repo, "switch", "-qc", git_branch)

    for rel, content in files.items():
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content)

    if git_branch:
        git(repo, "add", "formal_math")
        git(repo, "commit", "-qm", "change")


def run_gate(repo: Path, gate: str, extra_env=None):
    env = ENV.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(repo / "formal_math/verification/run_gates.py"),
         "--repo-root", str(repo), "--gate", gate],
        cwd=repo, env=env, capture_output=True, text=True, check=False, timeout=300,
    )


def run_fm_audit_raw(repo: Path, gate: str, mods: list[str], stdin="{}"):
    fm = repo / "formal_math"
    b = subprocess.run(["lake", "build", *(f"+{m}:olean" for m in mods)],
                       cwd=fm, env=ENV, capture_output=True, text=True, check=False, timeout=300)
    if b.returncode != 0:
        return b
    return subprocess.run(["lake", "exe", "fm_audit", gate, *mods],
                          cwd=fm, env=ENV, input=stdin, capture_output=True, text=True, check=False, timeout=300)


RESULTS = []


def record(case_id: str, gate: str, desc: str, res: subprocess.CompletedProcess):
    entry = {
        "id": case_id,
        "gate": gate,
        "desc": desc,
        "rc": res.returncode,
        "stdout": res.stdout.strip(),
        "stderr": res.stderr.strip(),
    }
    RESULTS.append(entry)
    print(f"[{case_id}] gate={gate} rc={res.returncode} | {desc}", flush=True)
    if entry["stdout"]:
        for line in entry["stdout"].splitlines()[:6]:
            print(f"    OUT: {line}", flush=True)
    if entry["stderr"]:
        for line in entry["stderr"].splitlines()[:6]:
            print(f"    ERR: {line}", flush=True)


def main():
    BASE_TMP.mkdir(parents=True, exist_ok=True)
    Path(ENV["TMPDIR"]).mkdir(parents=True, exist_ok=True)

    # --- Exp 1A ---
    r = BASE_TMP / "exp1a"
    make_pkg(r, {})
    fake_bin = r / "fakebin"
    fake_bin.mkdir()
    fake_lean = fake_bin / "lean"
    fake_lean.write_text("#!/bin/sh\necho 'Lean (version 4.35.0, fake)'\n")
    fake_lean.chmod(0o755)
    record("1A", "1", "运行期 lean --version 为 4.35.0 但 lean-toolchain 为 v4.36.0",
           run_gate(r, "1", extra_env={"PATH": f"{fake_bin}:{ENV['PATH']}"}))

    # --- Exp 2A ---
    r = BASE_TMP / "exp2a"
    make_pkg(r, {
        "formal_math/Chan.lean": (
            "module\n"
            "set_option relaxedAutoImplicit true in\n"
            "def f (x : α) := x\n"
        )
    })
    record("2A", "2", "源码局部 set_option relaxedAutoImplicit true", run_gate(r, "2"))

    # --- Exp 2B ---
    r = BASE_TMP / "exp2b"
    make_pkg(r, {
        "formal_math/Chan.lean": (
            "module\n"
            "set_option warningAsError false\n"
            "def unused (ignored : Nat) : Nat := 0\n"
        )
    })
    record("2B", "2", "源码局部 set_option warningAsError false 压制未用变量报错", run_gate(r, "2"))

    # --- Exp 2C ---
    r = BASE_TMP / "exp2c"
    make_pkg(r, {
        "formal_math/Chan.lean": (
            'module\n'
            'def _a := r"\\"\n'
            'set_option linter.unusedVariables false\n'
            'def _b := "\\""\n'
            'def unused (ignored : Nat) : Nat := 0\n'
        )
    })
    record("2C", "2", 'r"\\" 词法脱同步绕过 gate2 禁用 set_option linter.unusedVariables false', run_gate(r, "2"))

    # --- Exp 2D ---
    r = BASE_TMP / "exp2d"
    custom_toml = (
        'name = "adv"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
        '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n\n'
        '[[lean_lib]]\nname = "Chan"\n'
        'leanOptions = { linter.unusedVariables = false, autoImplicit = true }\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nglobs = ["ChanTest.*"]\n'
    )
    make_pkg(r, {
        "formal_math/Chan.lean": "module\ndef unused (ignored : α) : Nat := 0\n"
    }, custom_lakefile=custom_toml)
    record("2D", "2", "[[lean_lib]] 级 leanOptions 覆盖顶层禁止项", run_gate(r, "2"))

    # --- Exp 2E ---
    r = BASE_TMP / "exp2e"
    real_toml = (
        'name = "chan"\nversion = "0.1.0"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
        '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n\n'
        '[[lean_lib]]\nname = "Chan"\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nroots = ["ChanTest.Probe"]\nglobs = ["ChanTest.+"]\n'
    )
    make_pkg(r, {
        "formal_math/Chan/Defs/Unimported.lean": (
            "module\n@[expose] public section\n"
            "def brokenUnused (ignored : Nat) : Nat := this_does_not_even_compile\n"
        )
    }, custom_lakefile=real_toml)
    record("2E", "2", "无 globs 的 lakefile.toml 对未导入子模块编译错", run_gate(r, "2"))

    # --- Exp 3A ---
    r = BASE_TMP / "exp3a"
    make_pkg(r, {
        "formal_math/Chan.lean": (
            'module\n'
            'def _a := r"\\"\n'
            'set_option linter.unusedVariables false\n'
            '#eval 1 + 1\n'
            'syntax "my_secret_syn" : term\n'
            'macro_rules | `(my_secret_syn) => `(42)\n'
            'def _b := "\\""\n'
            'def useSecret : Nat := my_secret_syn\n'
        )
    })
    record("3A", "3", 'r"\\" 词法脱同步绕过 gate3 的 #eval/syntax/macro_rules/set_option linter', run_gate(r, "3"))

    # --- Exp 3B ---
    for kind, body in [
        ("partial", "partial def badP (n : Nat) : Nat := badP n"),
        ("unsafe", "unsafe def badU : Nat := 0"),
        ("extern", '@[extern "foo"] opaque badE : Nat'),
        ("implby", "def h0 : Nat := 0\n@[implemented_by h0] def badI : Nat := 1"),
        ("axiom", "axiom badA : False"),
    ]:
        r = BASE_TMP / f"exp3b_{kind}"
        if kind == "extern":
            code = 'module\ndef _a := r"\\"\n@[extern "foo"] opaque badE : Nat\ndef _b := "\\""\n'
        else:
            code = f'module\ndef _a := r"\\"\n{body}\ndef _b := "\\""\n'
        make_pkg(r, {"formal_math/Chan.lean": code})
        record(f"3B-{kind}", "3", f'r"\\" 绕过文本层后测环境层对 {kind} 的兜底', run_gate(r, "3"))

    # --- Exp 3C ---
    r = BASE_TMP / "exp3c"
    make_pkg(r, {
        "formal_math/Chan.lean": (
            "module\n"
            "import Lean\n"
            "run_cmd Lean.logInfo m!\"ran arbitrary meta code\"\n"
        )
    })
    record("3C", "3", "run_cmd 在 Chan 中执行任意元编程", run_gate(r, "3"))

    # --- Exp 6a-A ---
    r = BASE_TMP / "exp6aa"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "opaque opA : Nat := 0\n"
        )
    })
    res6a_raw = run_fm_audit_raw(r, "6a", ["ChanTest.Probe", "Chan.Defs.Fixture"])
    record("6a-A-raw", "6a", "opaqueInfo statement() 序列化 v1", res6a_raw)

    r2 = BASE_TMP / "exp6aa2"
    make_pkg(r2, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "opaque opA : (fun _ : Nat => Nat) 1 := 0\n"
        )
    })
    res6a_raw2 = run_fm_audit_raw(r2, "6a", ["ChanTest.Probe", "Chan.Defs.Fixture"])
    record("6a-A-raw2", "6a", "opaqueInfo 修改类型后 statement() 输出对比", res6a_raw2)

    # --- Exp 6a-B ---
    r = BASE_TMP / "exp6ab"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "def f (x : Nat) : Nat := x\n"
        )
    })
    res_def = run_fm_audit_raw(r, "6a", ["ChanTest.Probe", "Chan.Defs.Fixture"])
    r2 = BASE_TMP / "exp6ab2"
    make_pkg(r2, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "abbrev f (x : Nat) : Nat := x\n"
        )
    })
    res_abbrev = run_fm_audit_raw(r2, "6a", ["ChanTest.Probe", "Chan.Defs.Fixture"])
    record("6a-B-def", "6a", "def f 的 statement 序列化", res_def)
    record("6a-B-abbrev", "6a", "abbrev f 的 statement 序列化", res_abbrev)

    # --- Exp 6a-C ---
    r = BASE_TMP / "exp6ac1"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "theorem t : True := trivial\n"
        )
    })
    res_thm = run_fm_audit_raw(r, "6a", ["ChanTest.Probe", "Chan.Defs.Fixture"])
    r2 = BASE_TMP / "exp6ac2"
    make_pkg(r2, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "axiom t : True\n"
        )
    })
    res_ax = run_fm_audit_raw(r2, "6a", ["ChanTest.Probe", "Chan.Defs.Fixture"])
    record("6a-C-thm", "6a", "theorem t 的 statement 序列化", res_thm)
    record("6a-C-ax", "6a", "axiom t 的 statement 序列化", res_ax)

    # --- Exp 6b-A ---
    r = BASE_TMP / "exp6ba"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": "module\n@[expose] public section\ndef gap (x y : Nat) : Nat := x - y\n",
        "formal_math/verification/garbage-signoffs.yaml": '{"gap":{"Nat.sub":{"count":1,"review":"#999"}}}\n',
    }, git_branch="decl/test-signoff")
    record("6b-A", "6b", "decl/ 分支为门10更新 garbage-signoffs.yaml", run_gate(r, "6b"))

    # --- Exp 7a-A ---
    r = BASE_TMP / "exp7aa"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "structure BspEndpoint where\n"
            "  side : Nat\n  center : Nat\n  divPair : Nat\n"
            "  brokeCenter : Bool\n  afterTypeOne : Bool\n  leftCenter : Bool\n"
            "  retracePrice : Nat\n  firstRetrace : Bool\n"
            "def dummyBsp : BspEndpoint := ⟨0, 0, 0, true, true, true, 0, true⟩\n"
            "end\npublic section\n"
            "theorem fakeRefinement :\n"
            "    dummyBsp.brokeCenter = (dummyBsp.side == 0) ∧\n"
            "    dummyBsp.afterTypeOne = (dummyBsp.side == 0) ∧\n"
            "    dummyBsp.leftCenter = (dummyBsp.side == 0) ∧\n"
            "    dummyBsp.firstRetrace = (dummyBsp.side == 0) :=\n"
            "  ⟨rfl, rfl, rfl, rfl⟩\n"
        ),
        "formal_math/formalization.yaml": json.dumps({"refinements": {"BspEndpoint": "fakeRefinement"}}),
    })
    record("7a-A", "7a", "原版自由 Bool BspEndpoint 用字面量 dummy rfl 伪造精化定理", run_gate(r, "7a"))

    # --- Exp 7a-B ---
    r = BASE_TMP / "exp7ab"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "structure BspEndpoint where\n"
            "  side : Nat\n  brokeCenter : Bool\n  afterTypeOne : Bool\n"
            "  leftCenter : Bool\n  firstRetrace : Bool\n"
            "end\npublic section\n"
            "theorem fakeRefEmpty (e : BspEndpoint) (z : Empty) :\n"
            "    e.brokeCenter = decide (e.side > 0) ∧\n"
            "    e.afterTypeOne = decide (e.side > 0) ∧\n"
            "    e.leftCenter = decide (e.side > 0) ∧\n"
            "    e.firstRetrace = decide (e.side > 0) :=\n"
            "  nomatch z\n"
        ),
        "formal_math/formalization.yaml": json.dumps({"refinements": {"BspEndpoint": "fakeRefEmpty"}}),
    })
    record("7a-B", "7a", "原版自由 Bool BspEndpoint 用 Empty 数据参数空真伪造精化", run_gate(r, "7a"))

    # --- Exp 7a-C ---
    r = BASE_TMP / "exp7ac"
    make_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic section\n"
            "def sneakyTheorem (x : Nat) (h0 : x = 0) (h1 : x = 1) : False :=\n"
            "  Nat.noConfusion (h0.symm.trans h1)\n"
            "def sneakyMirror (P : Nat → Prop) (h : ∀ x, P x) (x : Nat) : P x := h x\n"
        ),
        "formal_math/formalization.yaml": "{}",
    })
    for g in ("7a", "8a", "8b", "9"):
        record(f"7a-C-g{g}", g, f"用 def 代替 theorem 写空真/镜像定理测门 {g}", run_gate(r, g))

    # --- Exp 7a-D ---
    r = BASE_TMP / "exp7ad"
    make_pkg(r, {
        "formal_math/Chan/Exec/Fixture.lean": (
            "module\n@[expose] public section\n"
            "structure ExecState where\n  step : Nat\n"
            "def execRun : List Nat → Nat\n  | [] => 0\n  | _ :: xs => 1 + execRun xs\n"
        ),
        "formal_math/formalization.yaml": "{}",
    })
    record("7a-D", "7a", "Chan/Exec 中写普通 structure+递归函数是否触发自动 thmInfo 误杀", run_gate(r, "7a"))

    # --- Exp 7b-A ---
    r = BASE_TMP / "exp7ba"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "def D (n : Nat) : Prop := n = 0\n"
        ),
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic import Chan.Defs.Fixture\npublic section\n"
            "theorem t : D 0 := Eq.refl 0\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {"t": {"about": ["D"], "mode": "依赖具体定义"}}
        }),
    })
    record("7b-A", "7b", "Astra 经典例 def D n := n = 0; theorem t : D 0 := Eq.refl 0", run_gate(r, "7b"))

    # --- Exp 7b-B ---
    r = BASE_TMP / "exp7bb"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "def D (n : Nat) : Nat := n + 1\n"
        ),
        "formal_math/Chan/Hypotheses/Fixture.lean": (
            "module\npublic import Chan.Defs.Fixture\n@[expose] public section\n"
            "structure PullbackHyp (n : Nat) : Prop where\n  ok : D n = 1\n"
        ),
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic import Chan.Hypotheses.Fixture\npublic section\n"
            "theorem claim (h : PullbackHyp 0) : D 0 = 1 := h.ok\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {"claim": {"about": ["D"], "mode": "依赖具体定义"}}
        }),
    })
    record("7b-B", "7b", "Chan/Hypotheses 定义全 Prop structure 时门7b结果", run_gate(r, "7b"))

    # --- Exp 8a-A ---
    r = BASE_TMP / "exp8aa"
    make_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic section\n"
            "abbrev MirrorStmt : Prop :=\n"
            "  ∀ (P : Nat → Prop), (∀ x, P x) → ∀ x, P x\n"
            "theorem wrapped_mirror : MirrorStmt := fun _ h x => h x\n"
        ),
    })
    record("8a-A", "8a", "用 abbrev 包装全称实例化语句测门8a", run_gate(r, "8a"))

    # --- Exp 8a-B ---
    r = BASE_TMP / "exp8ab"
    make_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic section\n"
            "theorem guarded_mirror (x : Nat) (hx : 0 < x)\n"
            "    (h : ∀ n, 0 < n → n + 1 > 1) : x + 1 > 1 := h x hx\n"
        ),
    })
    record("8a-B", "8a", "全称前提含额外 Prop 守卫测门8a", run_gate(r, "8a"))

    # --- Exp 8a-C ---
    r = BASE_TMP / "exp8ac"
    make_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic import Mathlib.Basic.ExistsUnique\npublic section\n"
            "abbrev MyEU := @ExistsUnique Nat\n"
            "theorem eu_and_true (f : Nat → Nat) (x : Nat) :\n"
            "    ExistsUnique (fun y => y = f x ∧ True) :=\n"
            "  ⟨f x, ⟨rfl, trivial⟩, fun _ h => h.1⟩\n"
            "theorem eu_abbrev (f : Nat → Nat) (x : Nat) :\n"
            "    MyEU (fun y => y = f x) :=\n"
            "  ⟨f x, rfl, fun _ h => h⟩\n"
            "theorem eu_id (f : Nat → Nat) (x : Nat) :\n"
            "    ExistsUnique (fun y => id y = f x) :=\n"
            "  ⟨f x, rfl, fun _ h => h⟩\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {
                "eu_and_true": {"about": [], "mode": "对任意实现成立", "declarative_unique": True},
                "eu_abbrev": {"about": [], "mode": "对任意实现成立", "declarative_unique": True},
                "eu_id": {"about": [], "mode": "对任意实现成立", "declarative_unique": True},
            }
        }),
    }, uses_mathlib=True)
    record("8a-C", "8a", "ExistsUnique 用 ∧ True / abbrev / id y 测 FUNCTION_GRAPH", run_gate(r, "8a"))

    # --- Exp 8b-A ---
    r = BASE_TMP / "exp8ba"
    make_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic section\n"
            "theorem divergence_creates_bsp (d lvl side : Nat) (_hdiv : d > 0) :\n"
            "    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=\n"
            "  ⟨(lvl, side), rfl, rfl⟩\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {"divergence_creates_bsp": {"about": [], "mode": "对任意实现成立"}}
        }),
    })
    record("8b-A", "8b", "省略 necessary 字段测旧病灶 divergence_creates_bsp", run_gate(r, "8b"))

    # --- Exp 8b-B ---
    r = BASE_TMP / "exp8bb"
    make_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic section\n"
            "private theorem helper (d lvl side : Nat) : d > 0 → ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=\n"
            "  fun _ => ⟨(lvl, side), rfl, rfl⟩\n"
            "theorem bsp_eta (d lvl side : Nat) (_hdiv : d > 0) :\n"
            "    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=\n"
            "  helper d lvl side _hdiv\n"
            "theorem bsp_eta_true (d lvl side : Nat) :\n"
            "    ∀ (_hdiv : d > 0), ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=\n"
            "  helper d lvl side\n"
            "theorem bsp_let (d lvl side : Nat) (_hdiv : d > 0) :\n"
            "    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side := by\n"
            "  let _ := _hdiv\n"
            "  exact ⟨(lvl, side), rfl, rfl⟩\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {
                "bsp_eta_true": {"about": [], "mode": "对任意实现成立", "necessary": ["_hdiv"]},
                "bsp_let": {"about": [], "mode": "对任意实现成立", "necessary": ["_hdiv"]},
            }
        }),
    })
    record("8b-B", "8b", "eta-收缩证明项与哑 let _ := _hdiv 测门8b", run_gate(r, "8b"))

    # --- Exp 9A ---
    r = BASE_TMP / "exp9a"
    make_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic section\n"
            "abbrev ContradictoryStmt : Prop := ∀ (x : Nat), x = 0 → x = 1 → False\n"
            "theorem claim : ContradictoryStmt := fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)\n"
        ),
        "formal_math/ChanTest/Evidence.lean": (
            "module\npublic section\n"
            "theorem claim.witness : True := trivial\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {"claim": {"about": [], "mode": "对任意实现成立", "needs_necessity": True}}
        }),
    })
    record("9A", "9", "用 abbrev 包装前提矛盾的空真定理测门9", run_gate(r, "9"))

    # --- Exp 10A ---
    r = BASE_TMP / "exp10a"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "def Price := Nat\n"
            "instance : Sub Price := inferInstanceAs (Sub Nat)\n"
            "instance : Div Price := inferInstanceAs (Div Nat)\n"
            "def gap (x y : Price) : Price := x - y\n"
            "def rate (x y : Price) : Price := x / y\n"
        )
    })
    record("10A", "10", "def Price := Nat 包装后 Nat.sub/Nat.div 测门10", run_gate(r, "10"))

    # --- Exp 10B ---
    r = BASE_TMP / "exp10b"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "def divInt (x y : Int) : Int := x / y\n"
            "def divRat (x y : Rat) : Rat := x / y\n"
            "def truncPred (x : Nat) : Nat := Nat.pred x\n"
            "def boom : Nat := panic! \"boom\"\n"
            "def lastBang (xs : List Nat) : Nat := xs.getLast!\n"
        )
    })
    record("10B", "10", "Int/Rat 总化除零、Nat.pred、panic!、getLast! 测门10", run_gate(r, "10"))

    # --- Exp 10C ---
    r = BASE_TMP / "exp10c"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "def optHead (xs : List (Option Nat)) : Option Nat := xs.head!\n"
            "def optGetD (xs : List (Option Nat)) (i : Nat) : Option Nat := xs.getD i (some 999)\n"
        )
    })
    record("10C", "10", "返回类型为 Option 的 head! 和 getD 测门10", run_gate(r, "10"))

    # --- Exp 10D ---
    r = BASE_TMP / "exp10d"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "def divNeZero (x dt : Nat) (_h : dt ≠ 0) : Nat := x / dt\n"
            "def divGeOne (x dt : Nat) (_h : 1 ≤ dt) : Nat := x / dt\n"
            "def divSucc (x dt : Nat) : Nat := x / (dt + 1)\n"
            "def divSubtype (x : Nat) (dt : { n : Nat // 0 < n }) : Nat := x / dt.1\n"
        )
    })
    record("10D", "10", "合法正除数写法 (dt≠0, 1≤dt, dt+1, Subtype 0<n) 测门10", run_gate(r, "10"))

    # --- Exp 15A ---
    r = BASE_TMP / "exp15a"
    make_pkg(r, {
        "formal_math/ChanDyn/Secret.lean": "module\npublic section\ndef secret : Nat := 1\n",
        "formal_math/Bridge.lean": "module\npublic import ChanDyn.Secret\n",
        "formal_math/Chan/Defs/Leak.lean": (
            "module\npublic import Bridge\n@[expose] public section\ndef x : Nat := secret\n"
        ),
    })
    record("15A", "15", "经由非 Chan 顶层 Bridge 模块导入 ChanDyn 测门15", run_gate(r, "15"))

    # --- Exp 15B ---
    r = BASE_TMP / "exp15b"
    make_pkg(r, {
        "formal_math/Chan/Proofs/Helper.lean": "module\npublic section\ndef h : Nat := 1\n",
        "formal_math/Chan/Audit/Literal/Lit.lean": (
            "module\npublic import Chan.Proofs.Helper\n@[expose] public section\ndef lit : Nat := h\n"
        ),
        "formal_math/ChanChallenge/Ch.lean": (
            "module\npublic import Chan.Audit.Literal.Lit\npublic section\ndef ch : Nat := lit\n"
        ),
    })
    record("15B", "15", "ChanChallenge 经 Chan/Audit/Literal 传递导入 Chan/Proofs 测门15", run_gate(r, "15"))

    # --- Exp 15C ---
    r = BASE_TMP / "exp15c"
    make_pkg(r, {
        "formal_math/ChanDyn/Secret.lean": "module\npublic section\ndef secret : Nat := 1\n",
        "formal_math/Chan.lean": "module\npublic import ChanDyn.Secret\n",
    })
    record("15C", "15", "主库根 Chan.lean 直接导入独立研究库 ChanDyn 测门15", run_gate(r, "15"))

    # --- Exp 15D ---
    r = BASE_TMP / "exp15d"
    make_pkg(r, {
        "formal_math/Chan/Defs/Flag.lean": (
            "module\npublic section\ndef probeFlag : Bool := true\nend\n"
            "@[expose] public section\nend\n"
        ),
    })
    record("15D-empty", "15", "末尾空 @[expose] public section 测门15", run_gate(r, "15"))

    r2 = BASE_TMP / "exp15d2"
    make_pkg(r2, {
        "formal_math/Chan/Defs/Flag.lean": (
            'module\npublic section\ndef probeFlag : Bool := true\n'
            'def _a := r"\\"\ndef _b := " @[expose] public section "\ndef _c := "\\""\n'
        ),
    })
    b = subprocess.run(["lake", "build", "+Chan.Defs.Flag:olean"], cwd=r2 / "formal_math",
                       env=ENV, capture_output=True, text=True, check=False)
    record("15D-desync-build", "15", 'r"\\" 字符串内伪造 @[expose] public section：Lean 编译结果', b)
    record("15D-desync-gate15", "15", 'r"\\" 字符串内伪造 @[expose] public section：门15结果', run_gate(r2, "15"))

    # --- Exp 15E ---
    r = BASE_TMP / "exp15e"
    make_pkg(r, {
        "formal_math/Chan/Defs/Flag.lean": (
            "module\n@[expose] public section\nprivate def hiddenVal : Nat := 7\n"
        ),
        "formal_math/Chan/Thm/Sneaky.lean": (
            "module\nimport all Chan.Defs.Flag\npublic section\n"
            "theorem peek : True := trivial\n"
        ),
    })
    record("15E-g15", "15", "普通 Chan/Thm 文件使用 import all 测门15", run_gate(r, "15"))
    record("15E-g3", "3", "普通 Chan/Thm 文件使用 import all 测门3", run_gate(r, "3"))

    out_path = Path("/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r1_replay_results.json")
    out_path.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2))
    print(f"\nDONE R1 REPLAY: {len(RESULTS)} experiments written to {out_path}", flush=True)


if __name__ == "__main__":
    main()
