"""由 inventory.py 的产物生成两份入库名单（维护工具，门禁不调用）。

    python3 formal_math/verification/make_lists.py <inventory.json>

判断规则（逐条写进名单的「依据」列）：

1. 每个候选精化器取它在钉选版本里的声明位置（文件:行）。
2. 静态调用闭包（Inventory.reach）不含精化期求值、宿主机读写、白名单外公理入口的，判「允许」。
3. 闭包命中的，逐条按最短调用链归类（`PATH_RULES`）：只求值库里按名字登记的常量（格式化器、
   文档渲染器、simproc、检索选择器）、只做剖析计时、或只在已被种类白名单／配置规则挡住的子句里
   求值用户项的，判「允许」并写明链路；归不了类的判「拒收」。
4. `REJECT` 里的候选（会在精化期编译运行用户项、改选项不留记录、引入白名单外公理）判「拒收」。
5. `EXTRA` 是语料里没出现、但白名单需要的只读入口，逐条写依据。

语法种类：语料里出现过、且各处理表为它登记的处理器全都「允许」的，判「允许」；无处理器的结构
节点注明由父节点精化器解释。
"""

import json
import sys
from pathlib import Path

TOOLCHAIN = Path.home() / ".elan/toolchains/leanprover--lean4---v4.36.0/src/lean"
PACKAGES = Path(__file__).resolve().parent.parent / ".lake/packages"
PACKAGE = {"Init": "lean4", "Lean": "lean4", "Std": "lean4", "Lake": "lean4", "Mathlib": "mathlib",
           "Batteries": "batteries", "Aesop": "aesop", "Qq": "Qq", "Plausible": "plausible",
           "ProofWidgets": "proofwidgets", "ImportGraph": "importGraph", "LeanSearchClient": "LeanSearchClient"}

PATH_RULES = [
    ("Lean.profileitIO", "只经 profileitIO 做剖析计时（unsafeBaseIO 不运行用户项）"),
    ("Lean.PrettyPrinter.runForNodeKind",
     "只经格式化器按语法种类求值库里登记的 formatter 常量（Lean/PrettyPrinter/Basic.lean:20）"),
    ("Lean.Doc.inlineRendererFor", "只经文档渲染器求值库里登记的渲染常量"),
    ("Lean.Meta.Simp.getSimprocFromDecl",
     "只按名字求值已登记的 simproc；simproc 须由 `simproc` 命令与 meta 声明定义，均不在白名单"),
    ("Lean.LibrarySuggestions.getSelector", "只求值库里登记的检索选择器"),
    ("Aesop.Frontend.elabConfigUnsafe",
     "只在 `(config := …)`、`(simp_config := …)` 子句里求值用户项；这些子句的语法种类不在种类白名单"),
    ("Aesop.appendStatsToStatsFileIfEnabled", "只在统计选项开启时写统计文件；该选项不在选项白名单"),
    ("Lean.Elab.Tactic.elabNativeDecideCore",
     "只在 `+native` 配置下编译运行判定程序；该配置被 Perimeter.configIssues 拦截，环境层另查 Lean.ofReduceBool"),
    ("Lean.Elab.ConfigEval.evalMetaEval",
     "只对配置值求值；配置项只许 `+名`、`-名` 与字面量（Perimeter.configIssues）"),
]

REJECT = {
    "Lean.Elab.Command.elabEval": ("lean4", "Lean/Elab/BuiltinEvalCommand.lean",
                                   "`#eval` 在精化期编译并运行用户项（含 IO）"),
    "Lean.Elab.Term.elabIncludeStr": ("lean4", "Lean/Elab/BuiltinTerm.lean:431",
                                      "`include_str` 经 evalTerm 求值用户项并读宿主机文件"),
    "Lean.Elab.Term.elabUnsafe": ("lean4", "Lean/Elab/BuiltinNotation.lean:555",
                                  "项级 `unsafe` 生成 unsafe 辅助声明与 implemented_by"),
    "Lean.Elab.Term.elabRunElab": ("lean4", "Lean/Elab/BuiltinNotation.lean", "`run_elab` 运行用户元程序"),
    "Lean.Elab.Tactic.evalRunTac": ("lean4", "Lean/Elab/Tactic/BuiltinTactic.lean", "`run_tac` 运行用户元程序"),
    "Lean.Elab.Tactic.evalNativeDecide": ("lean4", "Lean/Elab/Tactic/Decide.lean",
                                          "编译运行判定程序并引入 Lean.ofReduceBool"),
    "Mathlib.Meta.elabEvalExpr": ("mathlib", "Mathlib/Tactic/Eval.lean:41", "`eval%` 经 evalExpr 运行用户项"),
    "Mathlib.Tactic.elabSudoSetOption": ("mathlib", "Mathlib/Tactic/SudoSetOption.lean:50",
                                         "`sudo set_option` 直改 Core.Context.options，不经 elabSetOption、不留 OptionInfo"),
    "Mathlib.Tactic.elabTrace": ("mathlib", "Mathlib/Tactic/Trace.lean:24", "`trace` 经 evalExpr 运行用户项"),
    "Mathlib.Tactic.successIfFailWithMsg": ("mathlib", "Mathlib/Tactic/SuccessIfFailWithMsg.lean",
                                            "`success_if_fail_with_msg` 经 evalTerm 运行用户项"),
    "Mathlib.Tactic.ByElab.elabByElab": ("mathlib", "Mathlib/Tactic/ByElab.lean",
                                         "`by_elab` 运行用户写的 TermElabM 元程序"),
}

EXTRA = {
    "Lean.Elab.Command.elabPrintAxioms": ("lean4", "Lean/Elab/Print.lean",
                                         "`#print axioms` 只读环境并输出公理列表；只许出现在 Chan/Final 的 #guard_msgs 内"),
}
EXTRA_KINDS = {
    "Lean.Parser.Command.printAxioms": ("lean4", "处理器 Lean.Elab.Command.elabPrintAxioms（允许）"),
}


def source_file(module):
    parts = module.split(".")
    pkg = PACKAGE.get(parts[0], "?")
    rel = "/".join(parts) + ".lean"
    if pkg == "lean4":
        return pkg, (f"src/lean/lake/{rel}" if parts[0] == "Lake" else f"src/lean/{rel}")
    directory = {"mathlib": "mathlib", "batteries": "batteries", "aesop": "aesop", "Qq": "Qq",
                 "plausible": "plausible"}.get(pkg, pkg)
    return pkg, f".lake/packages/{directory}/{rel}"


def judge(name, decl):
    pkg, path = source_file(decl["module"]) if decl.get("module") else ("?", "?")
    where = f"{path}:{decl.get('line', 0)}"
    if name in REJECT:
        p, file, why = REJECT[name]
        return p, "拒收", f"{file}；{why}"
    if not decl.get("present"):
        return pkg, "拒收", "钉选环境里找不到该声明，无法复核"
    paths = decl.get("paths") or []
    if not paths:
        return pkg, "允许", f"{where}；静态调用闭包不含精化期求值、宿主机读写、白名单外公理入口"
    reasons = []
    for chain in paths:
        rule = next((why for key, why in PATH_RULES if key in chain), None)
        if rule is None:
            return pkg, "拒收", f"{where}；调用链 {' → '.join(chain)} 未能归类，需人工复核后再补入"
        if rule not in reasons:
            reasons.append(rule)
    return pkg, "允许", f"{where}；静态闭包命中危险入口，链路均已归类：" + "；".join(reasons)


def main():
    inv = json.loads(Path(sys.argv[1]).read_text())
    here = Path(__file__).resolve().parent
    decls = inv["decls"]
    # 属性应用在信息树里也留 CommandInfo，「精化器」是属性的注册函数（initFn）；属性另有白名单，
    # Perimeter.infoIssues 只核对命令类语法上的 CommandInfo，这里同样不收。
    attribute_infos = {n for n, uses in inv["elaborators"].items()
                       if uses and all(not k.startswith("Lean.Parser.Command.") and cat == "command"
                                       for cat, k in uses)}
    names = (set(inv["elaborators"]) - attribute_infos) | {
        n for v in inv["kinds"].values() for _, n in v["handlers"]}
    names.discard("")
    names.discard("[anonymous]")
    rows, verdict = [], {}
    for name in sorted(names | set(REJECT)):
        pkg, ruling, why = judge(name, decls.get(name, {}))
        verdict[name] = ruling
        rows.append((name, pkg, ruling, why))
    for name, (pkg, file, why) in EXTRA.items():
        verdict[name] = "允许"
        rows.append((name, pkg, "允许", f"{file}；{why}"))
    header = ("# 精化器与宏白名单（Lean 4.36.0 与钉选包）。由 make_lists.py 自 inventory.py 的语料产物生成；\n"
              "# 列：名字、所属包、判断（允许／拒收）、依据（声明位置与理由）。名单外的精化器一律红。\n")
    (here / "elaborators.tsv").write_text(header + "".join("\t".join(r) + "\n" for r in sorted(rows)))
    kinds = []
    for kind, info in sorted(inv["kinds"].items()):
        handlers = info["handlers"]
        pkg = PACKAGE.get(kind.split(".")[0], "lean4")
        if not handlers:
            kinds.append((kind, pkg, "允许", "无处理器：结构节点，由父节点的精化器解释"))
            continue
        bad = [n for _, n in handlers if verdict.get(n) != "允许"]
        listed = "、".join(f"{n}（{t}）" for t, n in handlers)
        kinds.append((kind, pkg, "拒收" if bad else "允许",
                      f"处理器 {listed}" + (f"；其中拒收 {'、'.join(bad)}" if bad else "，均允许")))
    for kind, (pkg, why) in EXTRA_KINDS.items():
        kinds.append((kind, pkg, "允许", why))
    header = ("# 语法种类白名单。由 make_lists.py 生成；列：种类、所属包、判断、依据（登记的处理器）。\n")
    (here / "syntax-kinds.tsv").write_text(header + "".join("\t".join(r) + "\n" for r in sorted(kinds)))
    allowed = sum(1 for r in rows if r[2] == "允许")
    print(f"精化器 {len(rows)} 条：允许 {allowed}，拒收 {len(rows) - allowed}；"
          f"种类 {len(kinds)} 条：允许 {sum(1 for k in kinds if k[2] == '允许')}")
    for r in rows:
        if r[2] == "拒收":
            print("拒收", r[0], r[3])


if __name__ == "__main__":
    main()
