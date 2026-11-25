"""NewChanlun #2312 (head 0b99173677) 第二轮全新深度对抗绕过与边界实测套件。
完全只读引用工作树门禁，所有临时沙箱与结果落在 /Volumes/AgentStorage/fm/r2/2312-r2-tmp/。
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

WT = Path("/Users/silencehan/.t3/worktrees/NewChanlun/infra-2312-b-env-gates-2428b08ce810d112")
VER = WT / "formal_math/verification"
BASE_TMP = Path("/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_sandbox")
PKG_LINK = (WT / "formal_math/.lake/packages").resolve()

ENV = os.environ.copy()
ENV["TMPDIR"] = "/Volumes/AgentStorage/fm/r2/2312-r2-tmp/tmp"
ENV["PATH"] = f"{Path.home() / '.elan/bin'}:{ENV.get('PATH', '')}"
ENV.pop("GITHUB_HEAD_REF", None)


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=AdvR2",
         "-c", "user.email=advr2@example.invalid", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )


def make_pkg(repo: Path, files: dict[str, str], uses_mathlib=False, extra_libs=(),
             custom_lakefile: str | None = None, git_branch: str | None = None,
             pre_git_files: dict[str, str] | None = None,
             delete_before_commit: list[str] | None = None):
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
            if p.parts[0] != "verification":
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
            'name = "advr2"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
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

    if delete_before_commit:
        for rel in delete_before_commit:
            p = repo / rel
            if p.exists():
                p.unlink()

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
        git(repo, "add", "-A")
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


def run_build(repo: Path, *extra_args):
    return subprocess.run(
        ["lake", "build", *extra_args],
        cwd=repo / "formal_math", env=ENV, capture_output=True, text=True, check=False, timeout=300,
    )


def lock_hashes(repo: Path, mods: list[str]):
    fm = repo / "formal_math"
    b = subprocess.run(["lake", "build", *(f"+{m}:olean" for m in mods)],
                       cwd=fm, env=ENV, capture_output=True, text=True, check=False, timeout=300)
    if b.returncode != 0:
        return None, b
    res = subprocess.run(["lake", "exe", "fm_audit", "6a", *mods],
                         cwd=fm, env=ENV, input="{}", capture_output=True, text=True, check=False, timeout=300)
    if res.returncode != 0:
        return None, res
    out = {}
    for line in res.stdout.splitlines():
        name, mod, stmt = json.loads(line)
        payload = json.dumps(stmt, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        out[name] = (hashlib.sha256(payload).hexdigest(), stmt)
    return out, res


RESULTS = []


def record(case_id: str, gate: str, desc: str, res: subprocess.CompletedProcess, extra=None):
    entry = {
        "id": case_id,
        "gate": gate,
        "desc": desc,
        "rc": res.returncode,
        "stdout": res.stdout.strip(),
        "stderr": res.stderr.strip(),
    }
    if extra is not None:
        entry["extra"] = extra
    RESULTS.append(entry)
    print(f"[{case_id}] gate={gate} rc={res.returncode} | {desc}", flush=True)
    if entry["stdout"]:
        for line in entry["stdout"].splitlines()[:6]:
            print(f"    OUT: {line}", flush=True)
    if entry["stderr"]:
        for line in entry["stderr"].splitlines()[:6]:
            print(f"    ERR: {line}", flush=True)
    if extra is not None:
        print(f"    EXTRA: {extra}", flush=True)


def main():
    BASE_TMP.mkdir(parents=True, exist_ok=True)
    Path(ENV["TMPDIR"]).mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # SECTION A: Lexer & Gate 1/2/3/15 bypasses
    # =========================================================================

    # A1: Interpolated string s!"{'"'}" desyncs LEX and bypasses gate 2!
    r = BASE_TMP / "a1_interp_g2"
    make_pkg(r, {
        "formal_math/Chan.lean": (
            'module\n'
            'def _a : String := s!"{\'"\'}"\n'
            'set_option linter.unusedVariables false\n'
            'set_option autoImplicit true\n'
            'set_option relaxedAutoImplicit true\n'
            'def _b : Char := \'"\'\n'
            'def unused (ignored : α) : Nat := 0\n'
        )
    })
    record("A1-build", "2", 's!"{\'"\'}" 合法性编译核验', run_build(r, "--wfail"))
    record("A1-g2", "2", 's!"{\'"\'}" 词法脱同步绕过门2 (关闭 linter.unusedVariables 并开启 autoImplicit)', run_gate(r, "2"))

    # A2: Interpolated string s!"{'"'}" bypasses gate 3 (#eval, run_cmd, syntax, macro, initialize)!
    r = BASE_TMP / "a2_interp_g3"
    make_pkg(r, {
        "formal_math/Chan.lean": (
            'module\n'
            'import Lean\n'
            'def _a : String := s!"{\'"\'}"\n'
            'set_option linter.unusedVariables false\n'
            '#eval 1 + 1\n'
            'run_cmd Lean.logInfo (toString (1 + 1))\n'
            'declare_syntax_cat sneaky_cat\n'
            'infixl:65 " +++ " => Nat.add\n'
            'def _b : Char := \'"\'\n'
            'def useOp : Nat := 2 +++ 3\n'
        )
    })
    record("A2-build", "3", 's!"{\'"\'}" 隐藏 #eval/run_cmd/declare_syntax_cat/infixl 编译核验', run_build(r, "--wfail"))
    record("A2-g3", "3", 's!"{\'"\'}" 词法脱同步绕过门3 (注入 #eval/run_cmd/syntax/infixl/set_option linter)', run_gate(r, "3"))

    # A3: Interpolated string s!"{r"\"}" desyncs LEX!
    r = BASE_TMP / "a3_interp_raw_g3"
    make_pkg(r, {
        "formal_math/Chan.lean": (
            'module\n'
            'def _a : String := s!"{r"\\"}"\n'
            '#eval 40 + 2\n'
            'def _b : Char := \'"\'\n'
        )
    })
    record("A3-build", "3", 's!"{r"\\"}" 编译核验', run_build(r, "--wfail"))
    record("A3-g3", "3", 's!"{r"\\"}" 词法脱同步绕过门3 #eval', run_gate(r, "3"))

    # A4: Block comment edge cases: /- -/- -/ and /- /- -/ -/ and unicode char '\x22'
    r = BASE_TMP / "a4_comment_edge"
    make_pkg(r, {
        "formal_math/Chan.lean": (
            'module\n'
            '/- -/- #eval 1 -/\n'
            'def ok1 : Nat := 1\n'
        )
    })
    record("A4a-build", "3", '块注释 /- -/- #eval 1 -/ Lean 解析行为', run_build(r))
    record("A4a-g3", "3", '块注释 /- -/- #eval 1 -/ 门3行为', run_gate(r, "3"))

    r = BASE_TMP / "a4b_comment_desync"
    make_pkg(r, {
        "formal_math/Chan.lean": (
            'module\n'
            '/- /-/-/\n'
            '#eval 1 + 1\n'
            'def ok2 : Nat := 2\n'
        )
    })
    record("A4b-build", "3", '块注释 /- /-/-/ + #eval 1 + 1 Lean 编译行为', run_build(r))
    record("A4b-g3", "3", '块注释 /- /-/-/ + #eval 1 + 1 门3行为', run_gate(r, "3"))

    r = BASE_TMP / "a4c_guillemet"
    make_pkg(r, {
        "formal_math/Chan.lean": (
            'module\n'
            'def «set_option» : Nat := 1\n'
            'def «axiom» : Nat := 2\n'
            'def okChar : Char := \'\\x22\'\n'
            'def multiLine : String := "line1\n#eval 1\nset_option linter.unusedVariables false\nline4"\n'
            'def rawMulti : String := r#"line1\n#eval 1\n-/\n"#\n'
        )
    })
    record("A4c-build", "3", '法语引号标识符/\\x22/跨行字符串/原始字符串 编译核验', run_build(r, "--wfail"))
    record("A4c-g3", "3", '法语引号标识符/\\x22/跨行字符串/原始字符串 门3是否误报', run_gate(r, "3"))

    r = BASE_TMP / "a4d_guillemet_opt"
    make_pkg(r, {
        "formal_math/Chan.lean": (
            'module\n'
            'set_option «linter».«unusedVariables» false\n'
            'def unused (ignored : Nat) : Nat := 0\n'
        )
    })
    record("A4d-g2", "2", 'set_option «linter».«unusedVariables» false 测门2', run_gate(r, "2"))

    # A5: Gate 2 lakefile.toml linter.all = false in top-level [leanOptions]
    r = BASE_TMP / "a5_linter_all_top"
    toml_a5 = (
        'name = "advr2"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
        '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n'
        'linter.all = false\n\n'
        '[[lean_lib]]\nname = "Chan"\nglobs = ["Chan.*"]\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nglobs = ["ChanTest.*"]\n'
    )
    make_pkg(r, {
        "formal_math/Chan.lean": "module\ndef unused (ignored : Nat) : Nat := 0\n"
    }, custom_lakefile=toml_a5)
    record("A5-g2", "2", "lakefile.toml 顶层 [leanOptions] 增加 linter.all = false 压制未用变量警告", run_gate(r, "2"))

    # A6: Gate 2 lakefile.toml moreLeanArgs = ["-Dlinter.all=false"] and ["-DwarningAsError=false"]
    r = BASE_TMP / "a6_more_lean_args_linter_all"
    toml_a6 = (
        'name = "advr2"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
        '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n\n'
        '[[lean_lib]]\nname = "Chan"\nglobs = ["Chan.*"]\n'
        'moreLeanArgs = ["-Dlinter.all=false"]\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nglobs = ["ChanTest.*"]\n'
    )
    make_pkg(r, {
        "formal_math/Chan.lean": "module\ndef unused (ignored : Nat) : Nat := 0\n"
    }, custom_lakefile=toml_a6)
    record("A6-g2", "2", 'lakefile.toml moreLeanArgs = ["-Dlinter.all=false"] 绕过门2', run_gate(r, "2"))

    r = BASE_TMP / "a6b_more_lean_args_split"
    toml_a6b = (
        'name = "advr2"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
        '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n\n'
        '[[lean_lib]]\nname = "Chan"\nglobs = ["Chan.*"]\n'
        'moreLeanArgs = ["-D", "warningAsError=false"]\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nglobs = ["ChanTest.*"]\n'
    )
    make_pkg(r, {
        "formal_math/Chan.lean": "module\ndef unused (ignored : Nat) : Nat := 0\n"
    }, custom_lakefile=toml_a6b)
    record("A6b-g2", "2", 'lakefile.toml moreLeanArgs = ["-D", "warningAsError=false"] 测门2', run_gate(r, "2"))

    # A7: Gate 1 fake path dependency in lake-manifest.json keeping same rev
    r = BASE_TMP / "a7_manifest_path"
    make_pkg(r, {})
    evil_dir = r / "evil_pkg"
    evil_dir.mkdir()
    (evil_dir / "lakefile.toml").write_text('name = "Cli"\n[[lean_lib]]\nname = "Cli"\n')
    (evil_dir / "Cli.lean").write_text("module\n")
    mf_path = r / "formal_math/lake-manifest.json"
    mf = json.loads(mf_path.read_text())
    for p in mf["packages"]:
        if p["name"] == "Cli":
            p["type"] = "path"
            p["dir"] = "../evil_pkg"
    mf_path.write_text(json.dumps(mf, indent=2))
    record("A7-g1", "1", "lake-manifest.json 把 Cli 篡改为 type=path 指向本地包但保留 rev 测门1", run_gate(r, "1"))

    # =========================================================================
    # SECTION B: Gate 6a Statement Lock probing
    # =========================================================================

    def compare_6a(case_id, code1, code2, desc, path="formal_math/Chan/Defs/Fixture.lean", mod="Chan.Defs.Fixture"):
        r1 = BASE_TMP / f"{case_id}_1"
        r2 = BASE_TMP / f"{case_id}_2"
        make_pkg(r1, {path: code1})
        make_pkg(r2, {path: code2})
        h1, res1 = lock_hashes(r1, ["ChanTest.Probe", mod])
        h2, res2 = lock_hashes(r2, ["ChanTest.Probe", mod])
        if h1 is None or h2 is None:
            record(case_id, "6a", desc + " (BUILD/AUDIT FAILED)", res1 if h1 is None else res2)
            return
        same_keys = set(h1.keys()) == set(h2.keys())
        same_hashes = {k: h1[k][0] for k in h1} == {k: h2[k][0] for k in h2}
        diff_info = {
            "same_keys": same_keys,
            "same_hashes": same_hashes,
            "h1_keys": sorted(h1.keys()),
            "h2_keys": sorted(h2.keys()),
            "changed": sorted(k for k in h1.keys() & h2.keys() if h1[k][0] != h2[k][0]),
            "unchanged": sorted(k for k in h1.keys() & h2.keys() if h1[k][0] == h2[k][0]),
        }
        record(case_id, "6a", desc, res2, extra=diff_info)

    compare_6a(
        "B1_let_vs_have",
        "module\n@[expose] public section\ndef f (x : Nat) : Nat := let y := x + 1; y\n",
        "module\n@[expose] public section\ndef f (x : Nat) : Nat := have y := x + 1; y\n",
        "def 内 let vs have (letE nondep 标志改变，影响 zeta 展开) 哈希是否不变",
    )
    compare_6a(
        "B2_hyp_unexpose",
        "module\n@[expose] public section\ndef H (n : Nat) : Prop := n = 0\n",
        "module\npublic section\ndef H (n : Nat) : Prop := n = 0\n",
        "Chan/Hypotheses 中 public 定义去掉 @[expose] 后门6a哈希是否不变",
        path="formal_math/Chan/Hypotheses/Fixture.lean",
        mod="Chan.Hypotheses.Fixture",
    )
    compare_6a(
        "B3_protected",
        "module\n@[expose] public section\ndef f (x : Nat) : Nat := x\n",
        "module\n@[expose] public section\nprotected def f (x : Nat) : Nat := x\n",
        "def 改为 protected def 哈希是否不变",
    )
    compare_6a(
        "B4_private",
        "module\n@[expose] public section\ndef f (x : Nat) : Nat := x\n",
        "module\n@[expose] public section\nprivate def f (x : Nat) : Nat := x\n",
        "def 改为 private def 哈希是否改变",
    )
    compare_6a(
        "B5_noncomputable",
        "module\n@[expose] public section\ndef f (x : Nat) : Nat := x\n",
        "module\n@[expose] public section\nnoncomputable def f (x : Nat) : Nat := x\n",
        "def 改为 noncomputable def 哈希是否不变",
    )
    compare_6a(
        "B6_irreducible",
        "module\n@[expose] public section\ndef f (x : Nat) : Nat := x\n",
        "module\n@[expose] public section\n@[irreducible] def f (x : Nat) : Nat := x\n",
        "def 改为 @[irreducible] def 哈希是否改变",
    )
    compare_6a(
        "B7_structure_field",
        "module\n@[expose] public section\nstructure S where\n  a : Nat\n  b : Nat\n",
        "module\n@[expose] public section\nstructure S where\n  a : Nat\n  c : Nat\n",
        "structure 改字段名 b -> c 哈希/键是否改变",
    )
    compare_6a(
        "B8_structure_to_class",
        "module\n@[expose] public section\nstructure S where\n  a : Nat\n",
        "module\n@[expose] public section\nclass S where\n  a : Nat\n",
        "structure 改为 class 哈希是否改变",
    )
    compare_6a(
        "B9_mutual",
        "module\n@[expose] public section\nmutual\n  def even : Nat → Bool | 0 => true | n+1 => odd n\n  def odd : Nat → Bool | 0 => false | n+1 => even n\nend\n",
        "module\n@[expose] public section\nmutual\n  def even : Nat → Bool | 0 => false | n+1 => odd n\n  def odd : Nat → Bool | 0 => true | n+1 => even n\nend\n",
        "mutual 递归改定义体哈希是否改变",
    )
    compare_6a(
        "B10_opaque_val",
        "module\n@[expose] public section\nopaque opA : Nat := 0\n",
        "module\n@[expose] public section\nopaque opA : Nat := 1\n",
        "opaque 改定义值哈希是否改变",
    )

    # =========================================================================
    # SECTION C: Gate 6b Branch Prefix & Signoff Permissions
    # =========================================================================

    # C1: decl/ modifying all allowed paths including Proxy, sources, signoffs
    r = BASE_TMP / "c1_decl_all"
    make_pkg(r, {
        "formal_math/Chan/Proxy/Ema.lean": "module\n",
        "formal_math/sources/glossary.yaml": "{}\n",
        "formal_math/verification/garbage-signoffs.yaml": '{"gap":{"Nat.sub":{"count":1,"review":"#1"}}}\n',
    }, git_branch="decl/all-allowed")
    record("C1-g6b", "6b", "decl/ 修改 Chan/Proxy + sources + garbage-signoffs.yaml 应绿", run_gate(r, "6b"))

    # C2: proof/ modifying Exec, Final.lean, Chan.lean
    r = BASE_TMP / "c2_proof_all"
    make_pkg(r, {
        "formal_math/Chan/Exec/Model.lean": "module\n",
        "formal_math/Chan/Final.lean": "module\n",
        "formal_math/Chan.lean": "module\n-- updated\n",
    }, git_branch="proof/all-allowed")
    record("C2-g6b", "6b", "proof/ 修改 Chan/Exec + Chan/Final.lean + Chan.lean 应绿", run_gate(r, "6b"))

    # C3: infra/ modifying existing garbage-signoffs.yaml must be RED
    r = BASE_TMP / "c3_infra_tamper_signoffs"
    make_pkg(r, {
        "formal_math/verification/garbage-signoffs.yaml": '{"gap":{"Nat.sub":{"count":1,"review":"sneaky"}}}\n',
    }, git_branch="infra/tamper")
    record("C3-g6b", "6b", "infra/ 篡改已有 garbage-signoffs.yaml 必须红", run_gate(r, "6b"))

    # C4: infra/ initializing empty signoffs when absent in base -> must be GREEN
    r = BASE_TMP / "c4_infra_init_empty"
    make_pkg(r, {
        "formal_math/verification/garbage-signoffs.yaml": "{}\n",
        "formal_math/ChanExplore/Try.lean": "module\n",
    }, git_branch="infra/init-empty", delete_before_commit=["formal_math/verification/garbage-signoffs.yaml"])
    record("C4-g6b", "6b", "infra/ 在基线缺失时初始化空 garbage-signoffs.yaml + ChanExplore 应绿", run_gate(r, "6b"))

    # C5: infra/ initializing NON-EMPTY signoffs when absent in base -> must be RED
    r = BASE_TMP / "c5_infra_init_nonempty"
    make_pkg(r, {
        "formal_math/verification/garbage-signoffs.yaml": '{"gap":{"Nat.sub":{"count":1,"review":"sneaky"}}}\n',
    }, git_branch="infra/init-nonempty", delete_before_commit=["formal_math/verification/garbage-signoffs.yaml"])
    record("C5-g6b", "6b", "infra/ 首次初始化非空 garbage-signoffs.yaml 必须红", run_gate(r, "6b"))

    # C6: infra/ modifying lean-toolchain or lake-manifest.json
    r = BASE_TMP / "c6_infra_toolchain"
    make_pkg(r, {
        "formal_math/lean-toolchain": "leanprover/lean4:v4.36.0\n",
        "formal_math/Chan/Smoke.lean": "module\n",
    }, git_branch="infra/bump")
    record("C6-g6b", "6b", "infra/ 修改 lean-toolchain / Chan/Smoke.lean 的门6b行为", run_gate(r, "6b"))

    # =========================================================================
    # SECTION D: Gate 7a / 7b Probing
    # =========================================================================

    # D1: Gate 7a node detection for def, instance, opaque, private def, manual mk.inj
    r = BASE_TMP / "d1_node_kinds"
    make_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic section\n"
            "structure FakeS where\n  x : Nat\n"
            "class MyPropClass : Prop where\n  ok : True\n"
            "instance instProp : MyPropClass := ⟨trivial⟩\n"
            "opaque opProp : True := trivial\n"
            "def defProp : True := trivial\n"
            "private def privDefProp : True := trivial\n"
            "theorem FakeS.mk.inj_fake (a b : Nat) (h : FakeS.mk a = FakeS.mk b) : a = b := by cases h; rfl\n"
        ),
        "formal_math/formalization.yaml": "{}",
    })
    record("D1-g7a", "7a", "def / instance(Prop) / opaque(Prop) / private def / 手写相似构造器名 是否全被门7a捕获", run_gate(r, "7a"))

    # D2: Gate 7a Chan/Exec realistic inductive + deriving + termination_by + proof subterms
    r = BASE_TMP / "d2_exec_realistic"
    make_pkg(r, {
        "formal_math/Chan/Exec/Fixture.lean": (
            "module\n@[expose] public section\n"
            "inductive Dir where\n  | up\n  | down\n  deriving DecidableEq, Repr, BEq\n"
            "structure Bar where\n  lo : Nat\n  hi : Nat\n  valid : lo ≤ hi\n  deriving DecidableEq\n"
            "def countdown (n : Nat) : Nat :=\n"
            "  if h : n = 0 then 0 else countdown (n - 1)\n"
            "termination_by n\n"
            "def firstElem (arr : Array Nat) (h : 0 < arr.size) : Nat := arr[0]\n"
        ),
        "formal_math/formalization.yaml": "{}",
    })
    record("D2-g7a", "7a", "Chan/Exec 真实复杂 inductive/deriving/termination_by/下标证明 是否触发门7a误杀", run_gate(r, "7a"))
    record("D2-g9", "9", "Chan/Exec 真实复杂 inductive/deriving/termination_by/下标证明 是否触发门9误杀", run_gate(r, "9"))

    # D3: Gate 7a bypass free Bool/Prop via `def Flag := Bool` and `Id Bool`!
    r = BASE_TMP / "d3_flag_def_bypass"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "def Flag := Bool\n"
            "def MyPred := Prop\n"
            "structure BspEndpoint where\n"
            "  side : Nat\n"
            "  brokeCenter : Flag\n"
            "  afterTypeOne : Id Bool\n"
            "  leftCenter : MyPred\n"
        ),
        "formal_math/formalization.yaml": "{}",
    })
    record("D3-build", "7a", "def Flag := Bool / Id Bool / def MyPred := Prop 合法编译核验", run_build(r, "--wfail"))
    record("D3-g7a", "7a", "用 def Flag := Bool / Id Bool / def MyPred := Prop 绕过门7a自由判据检查", run_gate(r, "7a"))

    # D4: Gate 7a FALSE POSITIVE on legitimate polymorphic structure with typeclass [LinearOrder P] or Nat param!
    r = BASE_TMP / "d4_poly_struct_fp"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\npublic import Mathlib.Order.Basic\n@[expose] public section\n"
            "structure GoodBar (P : Type) [LinearOrder P] where\n"
            "  lo : P\n  hi : P\n  isUp : Bool\n"
            "  h_up : isUp = decide (lo ≤ hi)\n"
            "end\npublic section\n"
            "theorem goodBar_ref (P : Type) [LinearOrder P] (e : GoodBar P) :\n"
            "    e.isUp = decide (e.lo ≤ e.hi) := e.h_up\n"
        ),
        "formal_math/formalization.yaml": json.dumps({"refinements": {"GoodBar": "goodBar_ref"}}),
    }, uses_mathlib=True)
    record("D4-build", "7a", "带 [LinearOrder P] 的合法精化结构编译核验", run_build(r, "--wfail"))
    record("D4-g7a", "7a", "带 [LinearOrder P] 的合法精化结构是否被门7a refines 误杀", run_gate(r, "7a"))

    r = BASE_TMP / "d4b_val_param_fp"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "structure Window (k : Nat) where\n"
            "  raw : Nat\n  inRange : Bool\n"
            "  h_in : inRange = (raw < k)\n"
            "end\npublic section\n"
            "theorem window_ref (k : Nat) (e : Window k) : e.inRange = (e.raw < k) := e.h_in\n"
        ),
        "formal_math/formalization.yaml": json.dumps({"refinements": {"Window": "window_ref"}}),
    })
    record("D4b-g7a", "7a", "带值参数 (k : Nat) 的合法精化结构是否被门7a refines 误杀", run_gate(r, "7a"))

    # D5: Gate 7a forging refines with False.elim / Subsingleton / Nonempty / non-prop
    r = BASE_TMP / "d5_forge_refines"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "structure BadS1 where\n  raw : Nat\n  flag : Bool\n  bot : False\n"
            "end\npublic section\n"
            "theorem ref1 (e : BadS1) : e.flag = (e.raw == 0) := False.elim e.bot\n"
        ),
        "formal_math/formalization.yaml": json.dumps({"refinements": {"BadS1": "ref1"}}),
    })
    record("D5a-g7a", "7a", "结构内嵌 bot : False 字段 + False.elim 伪造精化测门7a", run_gate(r, "7a"))

    r = BASE_TMP / "d5b_nonprop_ref"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "structure BadS2 where\n  raw : Nat\n  flag : Bool\n"
            "def fakeRef (e : BadS2) : Bool := e.flag\n"
        ),
        "formal_math/formalization.yaml": json.dumps({"refinements": {"BadS2": "fakeRef"}}),
    })
    record("D5b-g7a", "7a", "用非 Prop def 充当 refinements 测门7a", run_gate(r, "7a"))

    r = BASE_TMP / "d5c_subsingleton_ref"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "structure BadS3 where\n  raw : Nat\n  flag : Bool\n"
            "end\npublic section\n"
            "theorem fakeRefSub (e : BadS3) (_ : Subsingleton BadS3) (_ : Nonempty BadS3) :\n"
            "    e.flag = (e.raw == 0) := sorry\n"
        ),
        "formal_math/formalization.yaml": json.dumps({"refinements": {"BadS3": "fakeRefSub"}}),
    })
    record("D5c-g7a", "7a", "加 Subsingleton/Nonempty 额外参数伪造精化测门7a", run_gate(r, "7a"))

    # D6: Gate 7b Chan/Hypotheses using `cases h` / `match h with | ⟨hok⟩ => hok`!
    r = BASE_TMP / "d6_hyp_cases_crash"
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
            "theorem claim (h : PullbackHyp 0) : D 0 = 1 := by\n"
            "  cases h with\n  | mk hok => exact hok\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {"claim": {"about": ["D"], "mode": "依赖具体定义"}}
        }),
    })
    record("D6a-build", "7b", "Chan/Hypotheses structure 用 cases h 解构 编译核验", run_build(r, "--wfail"))
    record("D6a-g7b", "7b", "Chan/Hypotheses structure 用 cases h 解构 是否令门7b崩溃退2", run_gate(r, "7b"))

    r = BASE_TMP / "d6b_hyp_inductive_crash"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "def D (n : Nat) : Nat := n + 1\n"
        ),
        "formal_math/Chan/Hypotheses/Fixture.lean": (
            "module\npublic import Chan.Defs.Fixture\n@[expose] public section\n"
            "inductive PullbackInd (n : Nat) : Prop where\n  | mk (ok : D n = 1)\n"
        ),
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic import Chan.Hypotheses.Fixture\npublic section\n"
            "theorem claim (h : PullbackInd 0) : D 0 = 1 := by\n"
            "  cases h with\n  | mk hok => exact hok\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {"claim": {"about": ["D"], "mode": "依赖具体定义"}}
        }),
    })
    record("D6b-g7b", "7b", "Chan/Hypotheses 普通 Prop inductive 是否令门7b崩溃退2", run_gate(r, "7b"))

    r = BASE_TMP / "d6c_hyp_alias_crash"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "def D (n : Nat) : Nat := n + 1\n"
        ),
        "formal_math/Chan/Hypotheses/Fixture.lean": (
            "module\npublic import Chan.Defs.Fixture\n@[expose] public section\n"
            "structure PullbackHyp (n : Nat) : Prop where\n  ok : D n = 1\n"
            "def HypAlias (n : Nat) : Prop := PullbackHyp n\n"
        ),
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic import Chan.Hypotheses.Fixture\npublic section\n"
            "theorem claim (h : HypAlias 0) : D 0 = 1 := h.ok\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {"claim": {"about": ["D"], "mode": "依赖具体定义"}}
        }),
    })
    record("D6c-g7b", "7b", "Chan/Hypotheses 别名包装 structure (HypAlias) 是否令门7b崩溃退2", run_gate(r, "7b"))

    # =========================================================================
    # SECTION E: Gate 8a / 8b / 9 Bypasses
    # =========================================================================

    # E1: Wrapping statements in structure projection / class instance / Prod.fst bypasses 8a, 8b, 9!
    r = BASE_TMP / "e1_struct_proj_bypass"
    make_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\n@[expose] public section\n"
            "structure StmtBox where\n  prop : Prop\n"
            "def mirrorBox : StmtBox := ⟨∀ (P : Nat → Prop), (∀ x, P x) → ∀ x, P x⟩\n"
            "def bspBox : StmtBox := ⟨∀ (d lvl side : Nat) (_hdiv : d > 0), ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side⟩\n"
            "class VacClass where\n  prop : Prop\n"
            "instance : VacClass := ⟨∀ (x : Nat), x = 0 → x = 1 → False⟩\n"
            "def pairStmt : Prop × Prop := (∀ (x : Nat), x = 0 → x = 1 → False, True)\n"
            "end\npublic section\n"
            "theorem wrapped_mirror : mirrorBox.prop := fun _ h x => h x\n"
            "theorem wrapped_bsp : bspBox.prop := fun _ lvl side _ => ⟨(lvl, side), rfl, rfl⟩\n"
            "theorem wrapped_vac_class : VacClass.prop := fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)\n"
            "theorem wrapped_vac_pair : pairStmt.1 := fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)\n"
        ),
        "formal_math/ChanTest/Evidence.lean": (
            "module\npublic section\n"
            "theorem wrapped_mirror.witness : True := trivial\n"
            "theorem wrapped_bsp.witness : True := trivial\n"
            "theorem wrapped_vac_class.witness : True := trivial\n"
            "theorem wrapped_vac_pair.witness : True := trivial\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {
                "wrapped_mirror": {"about": [], "mode": "对任意实现成立", "needs_necessity": True},
                "wrapped_bsp": {"about": [], "mode": "对任意实现成立", "needs_necessity": True},
                "wrapped_vac_class": {"about": [], "mode": "对任意实现成立", "needs_necessity": True},
                "wrapped_vac_pair": {"about": [], "mode": "对任意实现成立", "needs_necessity": True},
            }
        }),
    })
    record("E1-build", "8a", "structure/class/Prod.fst 包装空真与镜像定理 编译核验", run_build(r, "--wfail"))
    record("E1-g8a", "8a", "structure/class/Prod.fst 包装镜像定理绕过门8a", run_gate(r, "8a"))
    record("E1-g8b", "8b", "structure/class/Prod.fst 包装无用前提定理绕过门8b", run_gate(r, "8b"))
    record("E1-g9", "9", "structure/class/Prod.fst 包装矛盾空真定理仅用 True 见证绕过门9与必要性检查", run_gate(r, "9"))

    # E2: let / have / fun / True ∧ wrapping statements
    r = BASE_TMP / "e2_let_have_fun_and"
    make_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic section\n"
            "theorem let_wrap : let T := Nat; ∀ (x : T), x = 0 → x = 1 → False :=\n"
            "  fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)\n"
            "theorem have_wrap : have T := Nat; ∀ (x : T), x = 0 → x = 1 → False :=\n"
            "  fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)\n"
            "theorem fun_wrap : (fun T => ∀ (x : T), x = 0 → x = 1 → False) Nat :=\n"
            "  fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)\n"
            "theorem and_wrap : True ∧ (∀ (x : Nat), x = 0 → x = 1 → False) :=\n"
            "  ⟨trivial, fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩\n"
        ),
        "formal_math/ChanTest/Evidence.lean": (
            "module\npublic section\n"
            "theorem let_wrap.witness : True := trivial\n"
            "theorem have_wrap.witness : True := trivial\n"
            "theorem fun_wrap.witness : True := trivial\n"
            "theorem and_wrap.witness : True := trivial\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {
                "let_wrap": {"about": [], "mode": "对任意实现成立", "needs_necessity": True},
                "have_wrap": {"about": [], "mode": "对任意实现成立", "needs_necessity": True},
                "fun_wrap": {"about": [], "mode": "对任意实现成立", "needs_necessity": True},
                "and_wrap": {"about": [], "mode": "对任意实现成立", "needs_necessity": True},
            }
        }),
    })
    record("E2-g9", "9", "let / have / fun / True ∧ 包装矛盾空真定理测门9", run_gate(r, "9"))

    # E3: Gate 8a ExistsUnique & premiseInstance bypass variants
    r = BASE_TMP / "e3_g8a_variants"
    make_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic import Mathlib.Basic.ExistsUnique\npublic section\n"
            "theorem eu_eq_zero (f : Nat → Nat) (x : Nat) :\n"
            "    ExistsUnique (fun y => y = f x ∧ 0 = 0) :=\n"
            "  ⟨f x, ⟨rfl, rfl⟩, fun _ h => h.1⟩\n"
            "theorem eu_dup (f : Nat → Nat) (x : Nat) :\n"
            "    ExistsUnique (fun y => y = f x ∧ y = f x) :=\n"
            "  ⟨f x, ⟨rfl, rfl⟩, fun _ h => h.1⟩\n"
            "theorem eu_manual_rev (f : Nat → Nat) (x : Nat) :\n"
            "    ∃ y, (∀ z, z = f x → z = y) ∧ y = f x :=\n"
            "  ⟨f x, fun _ h => h, rfl⟩\n"
            "theorem eu_manual_id (f : Nat → Nat) (x : Nat) :\n"
            "    ∃ y, y = f x ∧ ∀ z, z = f x → id z = y :=\n"
            "  ⟨f x, rfl, fun _ h => h⟩\n"
            "theorem eu_pair (f : Nat → Nat) (x : Nat) :\n"
            "    ExistsUnique (fun y => (y, ()) = (f x, ())) :=\n"
            "  ⟨f x, rfl, fun _ h => congrArg Prod.fst h⟩\n"
            "def AliasNat := Nat\n"
            "theorem alias_mirror (P : Nat → Prop) (x : AliasNat) (h : ∀ n : Nat, P n) : P x := h x\n"
            "theorem conj_mirror (P : Nat → Prop) (h : (∀ n, P n) ∧ True) (x : Nat) : P x := h.1 x\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {
                "eu_eq_zero": {"about": [], "mode": "对任意实现成立", "declarative_unique": True},
                "eu_dup": {"about": [], "mode": "对任意实现成立", "declarative_unique": True},
                "eu_manual_rev": {"about": [], "mode": "对任意实现成立", "declarative_unique": True},
                "eu_manual_id": {"about": [], "mode": "对任意实现成立", "declarative_unique": True},
                "eu_pair": {"about": [], "mode": "对任意实现成立", "declarative_unique": True},
                "alias_mirror": {"about": [], "mode": "对任意实现成立"},
                "conj_mirror": {"about": [], "mode": "对任意实现成立"},
            }
        }),
    }, uses_mathlib=True)
    record("E3-g8a", "8a", "ExistsUnique 多种变体与 AliasNat/合取前提镜像测门8a", run_gate(r, "8a"))

    # E4: Gate 8b bypasses via Function.const / have / subterm beta / And.left / subterm helper!
    r = BASE_TMP / "e4_g8b_bypasses"
    make_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic section\n"
            "private theorem mkEq {d lvl : Nat} (_ : d > 0) : lvl = lvl := rfl\n"
            "theorem bsp_const (d lvl side : Nat) :\n"
            "    d > 0 → ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=\n"
            "  Function.const (d > 0) ⟨(lvl, side), rfl, rfl⟩\n"
            "theorem bsp_have (d lvl side : Nat) (_hdiv : d > 0) :\n"
            "    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side := by\n"
            "  have _ := _hdiv\n"
            "  exact ⟨(lvl, side), rfl, rfl⟩\n"
            "theorem bsp_sub_beta (d lvl side : Nat) (_hdiv : d > 0) :\n"
            "    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=\n"
            "  ⟨(lvl, side), (fun _ => rfl) _hdiv, rfl⟩\n"
            "theorem bsp_and_left (d lvl side : Nat) (_hdiv : d > 0) :\n"
            "    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=\n"
            "  ⟨(lvl, side), And.left ⟨rfl, _hdiv⟩, rfl⟩\n"
            "theorem bsp_sub_helper (d lvl side : Nat) (_hdiv : d > 0) :\n"
            "    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=\n"
            "  ⟨(lvl, side), mkEq _hdiv, rfl⟩\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {
                "_private.Chan.Thm.Fixture.0.mkEq": {"about": [], "mode": "对任意实现成立", "doc_only": {"1": "测试辅助"}},
            }
        }),
    })
    record("E4-build", "8b", "门8b五种隐藏无用前提手法 编译核验", run_build(r, "--wfail"))
    record("E4-g8b", "8b", "Function.const / have / subterm beta / And.left / subterm helper 绕过门8b", run_gate(r, "8b"))

    # E5: Gate 8b recursive proof does not crash proofHead fuel
    r = BASE_TMP / "e5_g8b_rec"
    make_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic section\n"
            "theorem rec_thm (n : Nat) (h : n = n) : n + 0 = n :=\n"
            "  match n with\n  | 0 => h\n  | k + 1 => congrArg Nat.succ (rec_thm k rfl)\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {"rec_thm": {"about": [], "mode": "对任意实现成立"}}
        }),
    })
    record("E5-g8b", "8b", "递归证明在门8b proofHead 下是否正常（不爆 fuel 退2）", run_gate(r, "8b"))

    # =========================================================================
    # SECTION F: Gate 10 Garbage Values (Misses & False Positives)
    # =========================================================================

    # F1: Missed garbage operations (Rat.inv, Int.tdiv/ediv/fdiv, List.headD, Array.get!, Option.get!, panic!, etc.)
    r = BASE_TMP / "f1_g10_misses"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\npublic import Init.Data.Rat.Basic\n@[expose] public section\n"
            "def invRat (y : Rat) : Rat := y.inv\n"
            "def intTdiv (x y : Int) : Int := Int.tdiv x y\n"
            "def intEdiv (x y : Int) : Int := Int.ediv x y\n"
            "def intFdiv (x y : Int) : Int := Int.fdiv x y\n"
            "def natMod (x y : Nat) : Nat := x % y\n"
            "def headD_fn (xs : List Nat) : Nat := xs.headD 0\n"
            "def getLastD_fn (xs : List Nat) : Nat := xs.getLastD 0\n"
            "def arrBang (xs : Array Nat) (i : Nat) : Nat := xs[i]!\n"
            "def arrGetBang (xs : Array Nat) (i : Nat) : Nat := xs.get! i\n"
            "def listGetBang (xs : List Nat) (i : Nat) : Nat := xs.get! i\n"
            "def optGetBang (o : Option Nat) : Nat := o.get!\n"
            "def optPanic (xs : List (Option Nat)) : Option Nat := if xs.isEmpty then panic! \"x\" else xs.head!\n"
            "def optLastBang (xs : List (Option Nat)) : Option Nat := xs.getLast!\n"
            "def optGetIdxBang (xs : List (Option Nat)) (i : Nat) : Option Nat := xs[i]!\n"
            "def intToNat (x : Int) : Nat := x.toNat\n"
        ),
    })
    record("F1-build", "10", "门10各类垃圾值表达式编译核验", run_build(r, "--wfail"))
    record("F1-g10", "10", "Rat.inv / Int.tdiv/ediv/fdiv / headD / getLastD / Array.get! / Option 返回夹带 panic!/head!/getLast!/get! 测门10", run_gate(r, "10"))

    # F2: Type alias wrapping Int / Rat / Nat.pred
    r = BASE_TMP / "f2_g10_aliases"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\npublic import Init.Data.Rat.Basic\n@[expose] public section\n"
            "def MyInt := Int\n"
            "def MyRat := Rat\n"
            "instance : Div MyInt := inferInstanceAs (Div Int)\n"
            "instance : Div MyRat := inferInstanceAs (Div Rat)\n"
            "def rInt (x y : MyInt) : MyInt := x / y\n"
            "def rRat (x y : MyRat) : MyRat := x / y\n"
        ),
    })
    record("F2-g10", "10", "MyInt / MyRat 类型别名除法测门10", run_gate(r, "10"))

    # F3: Legitimate safe operations false-positive check (Fin indexing, 0 < dt on Int/Rat, dt > 0, if h : dt ≠ 0, Subtype)
    r = BASE_TMP / "f3_g10_safe_fp"
    make_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\npublic import Init.Data.Rat.Basic\n@[expose] public section\n"
            "def safeNatNeZero (x dt : Nat) (_h : dt ≠ 0) : Nat := x / dt\n"
            "def safeNatZeroNe (x dt : Nat) (_h : 0 ≠ dt) : Nat := x / dt\n"
            "def safeNatGt (x dt : Nat) (_h : dt > 0) : Nat := x / dt\n"
            "def safeNatAdd1 (x dt : Nat) : Nat := x / (dt + 1)\n"
            "def safeNat1Add (x dt : Nat) : Nat := x / (1 + dt)\n"
            "def safeNatSub (x : Nat) (dt : { n : Nat // 0 < n }) : Nat := x / dt.val\n"
            "def safeNatSubNe (x : Nat) (dt : { n : Nat // n ≠ 0 }) : Nat := x / dt.1\n"
            "def safeNatDite (x dt : Nat) : Nat := if _h : dt ≠ 0 then x / dt else 0\n"
            "def safeFinList (xs : List Nat) (i : Fin xs.length) : Nat := xs[i]\n"
            "def safeFinArr (xs : Array Nat) (i : Fin xs.size) : Nat := xs[i]\n"
            "def safeFinDiv (x : Nat) (i : Fin 5) : Nat := x / (i.1 + 1)\n"
            "def safeIntPos (x dt : Int) (_h : 0 < dt) : Int := x / dt\n"
            "def safeRatPos (x dt : Rat) (_h : 0 < dt) : Rat := x / dt\n"
            "def safeRatSubPos (x : Rat) (dt : { q : Rat // 0 < q }) : Rat := x / dt.val\n"
            "def safeRatLit (x : Rat) : Rat := x / (2 : Rat)\n"
        ),
    })
    record("F3-build", "10", "合法安全写法集合编译核验", run_build(r, "--wfail"))
    record("F3-g10", "10", "合法安全写法（含 Int/Rat 0 < dt、Fin 下标、dite、Subtype）门10误报核查", run_gate(r, "10"))

    # =========================================================================
    # SECTION G: Gate 15 Module & Visibility Probing
    # =========================================================================

    # G1: Unexposed `structure` or `instance` in Chan/Defs with empty `@[expose] public section`!
    r = BASE_TMP / "g1_unexposed_struct"
    make_pkg(r, {
        "formal_math/Chan/Defs/Flag.lean": (
            "module\npublic section\n"
            "structure HiddenBox where\n  val : Nat\n"
            "end\n@[expose] public section\nend\n"
        ),
        "formal_math/ChanTest/UseBox.lean": (
            "module\npublic import Chan.Defs.Flag\npublic section\n"
            "def useBox (b : HiddenBox) : Nat := b.val\n"
        ),
    })
    record("G1-build", "15", "未 expose 的 structure 跨模块访问 编译测试", run_build(r))
    record("G1-g15", "15", "未 expose 的 structure + 末尾空 @[expose] 门15行为", run_gate(r, "15"))

    # G2: Unexposed `instance` / `deriving DecidableEq` in Chan/Defs with empty `@[expose]`!
    r = BASE_TMP / "g2_unexposed_instance"
    make_pkg(r, {
        "formal_math/Chan/Defs/Flag.lean": (
            "module\npublic section\n"
            "inductive Color where | red | blue deriving DecidableEq\n"
            "end\n@[expose] public section\nend\n"
        ),
        "formal_math/ChanTest/UseColor.lean": (
            "module\npublic import Chan.Defs.Flag\npublic section\n"
            "example : Color.red = Color.red := by decide\n"
        ),
    })
    record("G2-build", "15", "未 expose 的 deriving DecidableEq 跨模块 decide 编译测试", run_build(r))
    record("G2-g15", "15", "未 expose 的 deriving DecidableEq + 末尾空 @[expose] 门15行为", run_gate(r, "15"))

    # G3: public import all / meta import all / meta import
    r = BASE_TMP / "g3_meta_import_all"
    make_pkg(r, {
        "formal_math/Chan/Defs/Flag.lean": "module\n@[expose] public section\nprivate def secret : Nat := 1\n",
        "formal_math/Chan/Thm/Sneaky.lean": (
            "module\nmeta import all Chan.Defs.Flag\npublic section\ntheorem ok : True := trivial\n"
        ),
    })
    record("G3-g15", "15", "meta import all 测门15", run_gate(r, "15"))
    record("G3-g3", "3", "meta import all 测门3", run_gate(r, "3"))

    # G4: ChanChallenge -> Chan.Defs -> Lean transitive external leak
    r = BASE_TMP / "g4_challenge_trans_ext"
    make_pkg(r, {
        "formal_math/Chan/Defs/UseLean.lean": "module\npublic import Lean\n@[expose] public section\ndef x : Nat := 1\n",
        "formal_math/ChanChallenge/Claim.lean": "module\npublic import Chan.Defs.UseLean\npublic section\ndef y : Nat := x\n",
    })
    record("G4-g15", "15", "ChanChallenge 经 Chan.Defs 传递导入 Lean 测门15", run_gate(r, "15"))

    # G5: Chan/Defs with s!"{'"'}" faking @[expose] public section (no defs vs with def)
    r = BASE_TMP / "g5_interp_expose"
    make_pkg(r, {
        "formal_math/Chan/Defs/Flag.lean": (
            'module\npublic section\n'
            'def probeFlag : Bool := true\n'
            'def _a : String := s!"{\'"\'}"\n'
            'def _b : String := " @[expose] public section "\n'
            'def _c : Char := \'"\'\n'
        ),
    })
    record("G5-g15", "15", 's!"{\'"\'}" 伪造 @[expose] public section 测门15环境兜底', run_gate(r, "15"))

    # G6: Chan/Defs private import of another Chan/Defs module + public import
    r = BASE_TMP / "g6_bridge_subdir"
    make_pkg(r, {
        "formal_math/ChanDyn/Secret.lean": "module\npublic section\ndef secret : Nat := 1\n",
        "formal_math/Helper/Bridge.lean": "module\npublic import ChanDyn.Secret\n",
        "formal_math/Chan/Defs/Leak.lean": "module\npublic import Helper.Bridge\n@[expose] public section\ndef x : Nat := secret\n",
    })
    record("G6-g15", "15", "子目录非 Chan 桥接 Helper/Bridge.lean 测门15", run_gate(r, "15"))

    # G7: Chan/Defs with opaque definition (no defnInfo) + empty @[expose]
    r = BASE_TMP / "g7_public_import_chan_defs"
    make_pkg(r, {
        "formal_math/Chan/Defs/A.lean": "module\npublic section\nabbrev hiddenAbbrev : Bool := true\nend\n@[expose] public section\nend\n",
        "formal_math/ChanTest/UseA.lean": "module\npublic import Chan.Defs.A\npublic section\nexample : hiddenAbbrev = true := by decide\n",
    })
    record("G7-build", "15", "无 @[expose] 的 abbrev 跨模块 decide 编译测试", run_build(r))
    record("G7-g15", "15", "无 @[expose] 的 abbrev + 末尾空 @[expose] 门15行为", run_gate(r, "15"))

    out_path = Path("/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_results.json")
    out_path.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2))
    print(f"\nDONE R2 ADVERSARIAL: {len(RESULTS)} experiments written to {out_path}", flush=True)


if __name__ == "__main__":
    main()
