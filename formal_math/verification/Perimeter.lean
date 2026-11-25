module

public import Lean

/-!
# 项与战术层的封闭世界

可信源码里每个语法节点的种类、每个可能承担精化的处理器都要在两份入库名单里：

* `verification/syntax-kinds.tsv`：语法种类白名单；
* `verification/elaborators.tsv`：精化器与宏的白名单（逐条写明所属包、判断与依据）。

三道检查用同一对名单：

1. **精化前**（`kindIssues`）：命令语法树的每个节点，种类须在种类名单里，且各处理表给该种类
   登记的每个处理器都在精化器名单里。名单外的节点在精化之前就被拒，被审代码一行不跑。
2. **精化中**（`sealTables`）：每条命令精化前，把各处理表里名单外的处理器登记为已擦除
   （`KeyedDeclsAttribute.ExtensionState.erased`）。宏展开出名单外的语法时，Lean 找不到处理器，
   名单外的精化器不会被调用。`open` 会重新激活作用域内的处理器，所以每条命令前都重做一次。
3. **精化后**（`infoIssues`）：信息树里每个 `TermInfo`、`TacticInfo`、`CommandInfo` 记录的精化器名
   须在精化器名单里（宏即宏声明名）；记录为匿名的节点按语法种类兜底；每个宏展开的产物逐节点再过
   第 1 道。
-/

open Lean Elab Command

namespace FM.Perimeter

public section

structure Lists where
  elaborators : NameSet := {}
  kinds : NameSet := {}
  deriving Inhabited

/-- 名单文件：`#` 开头为注释；每行 `名字<TAB>所属包<TAB>判断<TAB>依据`，判断为「允许」才进名单。 -/
private def readList (path : System.FilePath) : IO NameSet := do
  let mut names : NameSet := {}
  for line in (← IO.FS.readFile path).splitOn "\n" do
    if line.startsWith "#" || line.trimAscii.isEmpty then continue
    match line.splitOn "\t" with
    | name :: _ :: "允许" :: _ => names := names.insert name.toName
    | _ :: _ :: "拒收" :: _ => pure ()
    | _ => throw (IO.userError s!"{path}: 无法解读的名单行：{line}")
  return names

def load (dir : System.FilePath := "verification") : IO Lists := do
  return { elaborators := ← readList (dir / "elaborators.tsv"),
           kinds := ← readList (dir / "syntax-kinds.tsv") }

/-- 各处理表给某语法种类登记的处理器（Lean 4.36.0 中按种类分派的全部 `KeyedDeclsAttribute`）。 -/
def handlers (env : Environment) (kind : Name) : List (String × Name) :=
  (Term.termElabAttribute.getEntries env kind).map (("term", ·.declName)) ++
  (Tactic.tacticElabAttribute.getEntries env kind).map (("tactic", ·.declName)) ++
  (commandElabAttribute.getEntries env kind).map (("command", ·.declName)) ++
  (macroAttribute.getEntries env kind).map (("macro", ·.declName)) ++
  (Do.doElemElabAttribute.getEntries env kind).map (("doElem", ·.declName)) ++
  (Tactic.Grind.grindTacElabAttribute.getEntries env kind).map (("grind", ·.declName)) ++
  (Command.inductiveElabAttr.getEntries env kind).map (("inductive", ·.declName)) ++
  (Tactic.Try.tryTacticElabAttribute.getEntries env kind).map (("try", ·.declName))

/-- 不承担精化、由父节点解释的通用节点。 -/
private def structural (kind : Name) : Bool :=
  kind == nullKind || kind == choiceKind || kind == identKind

/--
战术与命令的配置项在精化期求值（`Lean.Elab.ConfigEval`；部分配置类型如 Mathlib 的
`LinarithConfig` 用 `Meta.evalExpr'` 编译运行）。配置项只许 `+名`、`-名` 与字面量取值；
`native` 一律不许（`decide +native` 编译运行被审代码并引入 `Lean.ofReduceBool`），
旧式 `(config := …)` 不许。
-/
def configIssues (stx : Syntax) : Array String :=
  match stx.getKind with
  | .str _ "posConfigItem" | .str _ "negConfigItem" =>
    if stx[1].getId.eraseMacroScopes == `native then #["配置项不许 native"] else #[]
  | .str _ "valConfigItem" =>
    let key := stx[1].getId.eraseMacroScopes
    let value := stx[3]
    let literal := [`num, `str, `scientific].contains value.getKind ||
      (value.isIdent && [`true, `false].contains value.getId.eraseMacroScopes)
    if key == `native then #["配置项不许 native"]
    else if key == `config then #["不许旧式 (config := …) 配置"]
    else if !literal then #[s!"配置项 {key} 的取值只许字面量"]
    else #[]
  | _ => #[]

/-- 第 1 道：语法树逐节点过种类名单与处理器名单。 -/
partial def kindIssues (lists : Lists) (env : Environment) (fallback stx : Syntax) :
    Array (Syntax × String × String) :=
  match stx with
  | .node _ kind args => Id.run do
    let ref := if stx.getPos?.isSome then stx else fallback
    let mut issues := #[]
    issues := issues ++ (configIssues stx).map fun d => (ref, "3", d)
    unless structural kind do
      if !lists.kinds.contains kind then
        issues := issues.push (ref, "3", s!"语法种类不在白名单：{kind}")
      for (table, h) in handlers env kind do
        unless lists.elaborators.contains h do
          issues := issues.push (ref, "3", s!"精化器不在白名单：{h}（{table}，种类 {kind}）")
    for a in args do issues := issues ++ kindIssues lists env ref a
    return issues
  | _ => #[]

private def eraseOutside {γ} (lists : Lists) (attr : KeyedDeclsAttribute γ) (env : Environment) :
    Environment :=
  attr.ext.modifyState env fun s =>
    { s with erased := s.table.fold (init := s.erased) fun acc _ entries =>
        entries.foldl (init := acc) fun acc e =>
          if lists.elaborators.contains e.declName then acc else acc.insert e.declName }

/-- 第 2 道：擦除各处理表里名单外的处理器。 -/
def sealTables (lists : Lists) (env : Environment) : Environment :=
  env |> eraseOutside lists Term.termElabAttribute |> eraseOutside lists Tactic.tacticElabAttribute
    |> eraseOutside lists commandElabAttribute |> eraseOutside lists macroAttribute
    |> eraseOutside lists Do.doElemElabAttribute |> eraseOutside lists Tactic.Grind.grindTacElabAttribute
    |> eraseOutside lists Command.inductiveElabAttr |> eraseOutside lists Tactic.Try.tryTacticElabAttribute

private def commandKind (env : Environment) (kind : SyntaxNodeKind) : Bool :=
  ((Parser.parserExtension.getState env).categories.find? `command).any (·.kinds.contains kind)

/-- 第 3 道：信息树里实际承担精化的精化器名与宏展开产物。 -/
partial def infoIssues (lists : Lists) (env : Environment) (fallback : Syntax) :
    InfoTree → Array (Syntax × String × String)
  | .context _ t => infoIssues lists env fallback t
  | .hole _ => #[]
  | .node info children => Id.run do
    let ref (stx : Syntax) := if stx.getPos?.isSome then stx else fallback
    let check (i : ElabInfo) : Array (Syntax × String × String) :=
      if i.elaborator.isAnonymous then
        match i.stx with
        | .node _ k _ =>
          if structural k || lists.kinds.contains k then #[]
          else #[(ref i.stx, "3", s!"语法种类不在白名单：{k}")]
        | _ => #[]
      else if lists.elaborators.contains i.elaborator then #[]
      else #[(ref i.stx, "3", s!"精化器不在白名单：{i.elaborator}（种类 {i.stx.getKind}）")]
    let mut issues := match info with
      | .ofTermInfo i => check i.toElabInfo
      | .ofTacticInfo i => check i.toElabInfo
      -- 属性应用也留 CommandInfo（「精化器」是属性注册函数）；属性另有白名单，只核对命令类语法。
      | .ofCommandInfo i => if commandKind env i.stx.getKind then check i.toElabInfo else #[]
      | .ofMacroExpansionInfo i => kindIssues lists env (ref i.stx) i.output
      | _ => #[]
    for c in children do issues := issues ++ infoIssues lists env fallback c
    return issues

end
end FM.Perimeter
