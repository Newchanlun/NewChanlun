"""针对 R2 中受脚手架 ChanTest.lean 缺失干扰的门2/门1/门15用例的精准复验脚本。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

WT = Path("/Users/silencehan/.t3/worktrees/NewChanlun/infra-2312-b-env-gates-2428b08ce810d112")
VER = WT / "formal_math/verification"
BASE_TMP = Path("/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_fixup_sandbox")

ENV = os.environ.copy()
ENV["TMPDIR"] = "/Volumes/AgentStorage/fm/r2/2312-r2-tmp/tmp"
ENV["PATH"] = f"{Path.home() / '.elan/bin'}:{ENV.get('PATH', '')}"
ENV.pop("GITHUB_HEAD_REF", None)


def make_clean_pkg(repo: Path, files: dict[str, str], custom_lakefile: str | None = None):
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
    (fm / "Chan").mkdir()
    if custom_lakefile is not None:
        (fm / "lakefile.toml").write_text(custom_lakefile)
    else:
        (fm / "lakefile.toml").write_text(
            'name = "fixup"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
            '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
            'linter.unusedVariables = true\n\n'
            '[[lean_lib]]\nname = "Chan"\nglobs = ["Chan.*"]\n\n'
            '[[lean_lib]]\nname = "ChanTest"\nroots = ["ChanTest.Probe"]\nglobs = ["ChanTest.+"]\n\n'
            '[[lean_exe]]\nname = "fm_audit"\nroot = "verification.Audit"\n\n'
            '[[lean_lib]]\nname = "FMEnvGates"\nroots = ["verification.EnvGates"]\n'
        )
    for rel, content in files.items():
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content)


def run_gate(repo: Path, gate: str):
    return subprocess.run(
        [sys.executable, str(repo / "formal_math/verification/run_gates.py"),
         "--repo-root", str(repo), "--gate", gate],
        cwd=repo, env=ENV, capture_output=True, text=True, check=False, timeout=300,
    )


def run_build(repo: Path, *extra_args):
    return subprocess.run(
        ["lake", "build", *extra_args],
        cwd=repo / "formal_math", env=ENV, capture_output=True, text=True, check=False, timeout=300,
    )


RESULTS = []


def rec(cid, gate, desc, res):
    RESULTS.append({"id": cid, "gate": gate, "desc": desc, "rc": res.returncode,
                    "stdout": res.stdout.strip(), "stderr": res.stderr.strip()})
    print(f"[{cid}] gate={gate} rc={res.returncode} | {desc}", flush=True)
    if res.stdout.strip():
        for l in res.stdout.strip().splitlines()[:5]:
            print(f"    OUT: {l}", flush=True)
    if res.stderr.strip():
        for l in res.stderr.strip().splitlines()[:5]:
            print(f"    ERR: {l}", flush=True)


def main():
    BASE_TMP.mkdir(parents=True, exist_ok=True)

    # 1. Clean A1: s!"{'"'}" bypasses gate 2 completely (rc=0)!
    r = BASE_TMP / "a1_clean"
    make_clean_pkg(r, {
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
    rec("A1-clean-build", "2", '干净 lakefile 下 s!"{\'"\'}" + unused (α) lake build --wfail', run_build(r, "--wfail"))
    rec("A1-clean-g2", "2", '干净 lakefile 下 s!"{\'"\'}" 绕过门2 (关闭 linter.unusedVariables + 开启 autoImplicit)', run_gate(r, "2"))

    # 2. Clean A5: top-level linter.all = false
    r = BASE_TMP / "a5_clean"
    toml = (
        'name = "fixup"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
        '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n'
        'linter.all = false\n\n'
        '[[lean_lib]]\nname = "Chan"\nglobs = ["Chan.*"]\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nroots = ["ChanTest.Probe"]\nglobs = ["ChanTest.+"]\n'
    )
    make_clean_pkg(r, {
        "formal_math/Chan.lean": "module\ndef unused (ignored : Nat) : Nat := 0\n"
    }, custom_lakefile=toml)
    rec("A5-clean-g2", "2", "干净 lakefile 下顶层 [leanOptions] linter.all = false 测门2", run_gate(r, "2"))

    # 3. Clean A6: moreLeanArgs = ["-Dlinter.all=false"]
    r = BASE_TMP / "a6_clean"
    toml = (
        'name = "fixup"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
        '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n\n'
        '[[lean_lib]]\nname = "Chan"\nglobs = ["Chan.*"]\n'
        'moreLeanArgs = ["-Dlinter.all=false"]\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nroots = ["ChanTest.Probe"]\nglobs = ["ChanTest.+"]\n'
    )
    make_clean_pkg(r, {
        "formal_math/Chan.lean": "module\ndef unused (ignored : Nat) : Nat := 0\n"
    }, custom_lakefile=toml)
    rec("A6-clean-g2", "2", '干净 lakefile 下 moreLeanArgs = ["-Dlinter.all=false"] 测门2', run_gate(r, "2"))

    # 4. Clean A6b: moreLeanArgs = ["-DwarningAsError=false"]
    r = BASE_TMP / "a6b_clean"
    toml = (
        'name = "fixup"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
        '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n\n'
        '[[lean_lib]]\nname = "Chan"\nglobs = ["Chan.*"]\n'
        'moreLeanArgs = ["-DwarningAsError=false"]\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nroots = ["ChanTest.Probe"]\nglobs = ["ChanTest.+"]\n'
    )
    make_clean_pkg(r, {
        "formal_math/Chan.lean": "module\ndef unused (ignored : Nat) : Nat := 0\n"
    }, custom_lakefile=toml)
    rec("A6b-clean-g2", "2", '干净 lakefile 下 moreLeanArgs = ["-DwarningAsError=false"] 测门2', run_gate(r, "2"))

    # 5. Clean A6c: top-level moreLeanArgs = ["-D", "linter.unusedVariables=false"] & weakLeanArgs = ["-Dlinter.all=false"]
    r = BASE_TMP / "a6c_clean"
    toml = (
        'name = "fixup"\ndefaultTargets = ["Chan", "ChanTest"]\n'
        'moreLeanArgs = ["-Dlinter.all=false"]\n\n'
        '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n\n'
        '[[lean_lib]]\nname = "Chan"\nglobs = ["Chan.*"]\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nroots = ["ChanTest.Probe"]\nglobs = ["ChanTest.+"]\n'
    )
    make_clean_pkg(r, {
        "formal_math/Chan.lean": "module\ndef unused (ignored : Nat) : Nat := 0\n"
    }, custom_lakefile=toml)
    rec("A6c-clean-g2", "2", '干净 lakefile 下顶层 moreLeanArgs = ["-Dlinter.all=false"] 测门2', run_gate(r, "2"))

    # 6. Clean A6d: top-level leanOptions with dotted key "linter.unusedVariables" in lib?
    # And what about `moreLeanArgs = ["-D", "linter.unusedVariables=false"]` (should be caught)
    # vs `moreLeanArgs = ["-D", "linter.unusedVariables", ...]`? Let's test `-Dlinter.unusedVariables=false` in `lean_lib` `leanOptions` with quoted key!
    r = BASE_TMP / "a6d_clean"
    toml = (
        'name = "fixup"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
        '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n\n'
        '[[lean_lib]]\nname = "Chan"\nglobs = ["Chan.*"]\n'
        'moreLeanArgs = ["-D", "warningAsError=false", "-D", "linter.all=false"]\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nroots = ["ChanTest.Probe"]\nglobs = ["ChanTest.+"]\n'
    )
    make_clean_pkg(r, {
        "formal_math/Chan.lean": "module\ndef unused (ignored : Nat) : Nat := 0\n"
    }, custom_lakefile=toml)
    rec("A6d-clean-g2", "2", 'moreLeanArgs 组合 -D warningAsError=false + -D linter.all=false 测门2', run_gate(r, "2"))

    # 7. Clean A6e: lakefile.toml with extra `[[require]]` local path dependency!
    r = BASE_TMP / "a6e_extra_dep"
    evil = r / "evil_dep"
    evil.mkdir(parents=True)
    (evil / "lakefile.toml").write_text('name = "Evil"\ndefaultTargets = ["Evil"]\n[[lean_lib]]\nname = "Evil"\n')
    (evil / "Evil.lean").write_text("module\npublic section\naxiom evilAx : False\n")
    toml = (
        'name = "fixup"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
        '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n\n'
        '[[require]]\nname = "Evil"\npath = "../evil_dep"\n\n'
        '[[lean_lib]]\nname = "Chan"\nglobs = ["Chan.*"]\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nroots = ["ChanTest.Probe"]\nglobs = ["ChanTest.+"]\n'
    )
    make_clean_pkg(r, {
        "formal_math/Chan.lean": "module\npublic section\ndef ok : Nat := 0\n"
    }, custom_lakefile=toml)
    rec("A6e-g1-before", "1", "lakefile.toml 增加本地 [[require]] path=../evil_dep（不改 manifest）先跑门1", run_gate(r, "1"))
    rec("A6e-g2", "2", "lakefile.toml 增加本地 [[require]] path=../evil_dep 跑门2", run_gate(r, "2"))
    rec("A6e-g1-after", "1", "跑完门2后再跑门1（检验 lake build 是否改写 manifest）", run_gate(r, "1"))

    # 8. Clean G2-decidable: unexposed deriving DecidableEq in Chan/Defs + empty @[expose]
    r = BASE_TMP / "g2_dec_clean"
    make_clean_pkg(r, {
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
    rec("G2-clean-build", "15", "未 expose 的 deriving DecidableEq 跨模块 decide 编译核验", run_build(r))
    rec("G2-clean-g15", "15", "未 expose 的 deriving DecidableEq + 末尾空 @[expose] 门15结果", run_gate(r, "15"))

    # 9. Clean A2-g2+g3: s!"{'"'}" in Chan/Defs hiding `set_option linter.unusedVariables false` + `#eval`
    r = BASE_TMP / "a2_clean"
    make_clean_pkg(r, {
        "formal_math/Chan.lean": (
            'module\n'
            'import Lean\n'
            'def _a : String := s!"{\'"\'}"\n'
            'set_option linter.unusedVariables false\n'
            'set_option autoImplicit true\n'
            '#eval 1 + 1\n'
            'run_cmd Lean.logInfo (toString (1 + 1))\n'
            'declare_syntax_cat sneaky_cat\n'
            'infixl:65 " +++ " => Nat.add\n'
            'def _b : Char := \'"\'\n'
            'def useOp (ignored : α) : Nat := 2 +++ 3\n'
        )
    })
    rec("A2-clean-g2", "2", '干净 lakefile 下 s!"{\'"\'}" 同时击穿门2', run_gate(r, "2"))
    rec("A2-clean-g3", "3", '干净 lakefile 下 s!"{\'"\'}" 同时击穿门3', run_gate(r, "3"))

    # 10. Verify `s!"{'"'}"` with macro_rules & syntax containing quotes?
    # Notice: syntax "my_syn" : term has TWO quotes inside the desynced zone!
    # The first quote CLOSES the desynced string, exposing `my_syn` (harmless identifier!),
    # and the second quote RE-OPENS the desynced string, swallowing `: term` and `macro_rules`!
    r = BASE_TMP / "a2_syntax_quotes"
    make_clean_pkg(r, {
        "formal_math/Chan.lean": (
            'module\n'
            'def _a : String := s!"{\'"\'}"\n'
            'syntax "my_secret_syn" : term\n'
            'macro_rules | `(my_secret_syn) => `(42)\n'
            'def _b : Char := \'"\'\n'
            'def useSecret : Nat := my_secret_syn\n'
        )
    })
    rec("A2-syn-build", "3", 's!"{\'"\'}" 隐藏带双引号的 syntax + macro_rules 编译核验', run_build(r, "--wfail"))
    rec("A2-syn-g3", "3", 's!"{\'"\'}" 隐藏带双引号的 syntax + macro_rules 绕过门3', run_gate(r, "3"))

    out = Path("/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_fixup_results.json")
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2))
    print(f"\nDONE FIXUP: {len(RESULTS)} experiments", flush=True)


if __name__ == "__main__":
    main()
