import Lean
/-!
设计咨询 #2312 的原型：源码层「只解析、不精化」。

* `headers <路径>...`：只用 Lean 的头部解析器读 `module` 标记与导入，不加载任何环境。
* `scan <逗号分隔的库导入> <模式> (<模块名>=<路径>)...`：只加载钉选库的环境（不加载任何被审
  模块的 olean），逐条 `parseCommand`；只有作用域命令（namespace/section/end/open）交给 Lean
  精化以维持解析状态，声明、项、战术一律不精化。模式 `check` 输出规则命中，`kinds` 输出语法种类。
-/
open Lean Elab Command

namespace Shape

def libraryRoots : Array Name := #[`Init, `Std, `Mathlib, `Batteries]
def projectRoots : Array Name := #[`Chan, `ChanChallenge, `ChanDyn, `ChanTest, `ChanExplore]

def commandKinds : Array Name :=
  #[`Lean.Parser.Command.moduleDoc, `Lean.Parser.Command.namespace, `Lean.Parser.Command.section,
    `Lean.Parser.Command.end, `Lean.Parser.Command.open, `Lean.Parser.Command.variable,
    `Lean.Parser.Command.universe, `Lean.Parser.Command.include, `Lean.Parser.Command.omit,
    `Lean.Parser.Command.in, `Lean.Parser.Command.declaration, `Lean.Parser.Command.mutual,
    `Lean.Parser.Command.set_option, `Lean.Parser.Command.check, `Lean.Parser.Command.attribute,
    `Lean.Parser.Command.deriving]

def declKinds : Array Name :=
  #[`Lean.Parser.Command.definition, `Lean.Parser.Command.theorem, `Lean.Parser.Command.abbrev,
    `Lean.Parser.Command.opaque, `Lean.Parser.Command.example, `Lean.Parser.Command.inductive,
    `Lean.Parser.Command.classInductive, `Lean.Parser.Command.structure,
    `Lean.Parser.Command.instance]

def attributeNames : Array Name :=
  #[`simp, `ext, `instance, `reducible, `irreducible, `inline, `specialize, `expose, `no_expose,
    `grind, `norm_cast, `push_cast, `refl, `symm, `trans, `gcongr, `gcongrAttr, `mono, `congr,
    `elab_as_elim, `induction_eliminator, `cases_eliminator, `deprecated, `simps, `method_specs]

def derivingClasses : Array Name :=
  #[`DecidableEq, `BEq, `ReflBEq, `LawfulBEq, `Hashable, `Ord, `Repr, `Inhabited, `Nonempty]

/-- 命名的禁用语法种类：占位证明、修饰符，以及第四轮点名的精化期求值入口。纵深防御，不求完备。 -/
def forbiddenKinds : Array Name :=
  #[`Lean.Parser.Term.sorry, `Lean.Parser.Tactic.tacticAdmit, `Lean.Parser.Tactic.tacticSorry,
    `Lean.Parser.Tactic.nativeDecide, `Lean.Parser.Tactic.runTac, `Lean.Parser.Term.runMeta,
    `Lean.Parser.Attr.extern, `Lean.Parser.Command.meta, `Lean.Parser.Command.unsafe,
    `Lean.Parser.Command.partial, `Lean.Parser.Term.unsafe, `Lean.includeStr, `Lean.byElab,
    `Mathlib.Meta.eval_expr, `Mathlib.Tactic.successIfFailWithMsg, `Lean.Parser.Tactic.trace,
    `termSudoSet_option___In_]

def forbiddenAtoms : List String :=
  ["implemented_by", "native_decide", "run_tac", "run_meta", "sudo", "include_str", "by_elab", "eval%"]

def allowedOption (key : Name) : Bool :=
  [`maxRecDepth, `maxHeartbeats, `synthInstance.maxHeartbeats, `synthInstance.maxSize,
    `match.ignoreUnusedAlts].contains key || (`pp).isPrefixOf key

partial def idents (stx : Syntax) : Array Name :=
  if stx.isIdent then #[stx.getId.eraseMacroScopes] else stx.getArgs.flatMap idents

def setting (stx : Syntax) : Option Name :=
  if stx.getNumArgs ≥ 2 && stx[0].isAtom && stx[0].getAtomVal.trimAscii.copy == "set_option" then
    some (idents stx[1] |>.foldl (· ++ ·) .anonymous)
  else none

def stripRoot (n : Name) : Name := n.replacePrefix `_root_ .anonymous

/-- 规则命中：(语法节点, 规则码, 说明)。 -/
partial def inspect (mod : Name) (stx : Syntax) (command guarded : Bool) :
    Array (Syntax × String × String) := Id.run do
  let kind := stx.getKind
  let final := (`Chan.Final).isPrefixOf mod
  let mut issues := #[]
  if command then
    let ok := commandKinds.contains kind ||
      (final && (kind == `Lean.guardMsgsCmd || kind == `Lean.Parser.Command.printAxioms))
    if !ok then issues := issues.push (stx, "COMMAND", s!"命令不在白名单：{kind}")
    if !guarded && kind == `Lean.Parser.Command.printAxioms then
      issues := issues.push (stx, "COMMAND", "#print axioms 只许出现在 #guard_msgs 内")
    if guarded && ![`Lean.Parser.Command.check, `Lean.Parser.Command.printAxioms].contains kind then
      issues := issues.push (stx, "GUARD", s!"#guard_msgs 内只许 #check 与 #print axioms：{kind}")
  if kind == `Lean.Parser.Command.declaration && !declKinds.contains stx[1].getKind then
    issues := issues.push (stx[1], "DECL", s!"声明不在白名单：{stx[1].getKind}")
  if kind == `Lean.Parser.Command.section && !stx[0][3].isNone then
    issues := issues.push (stx, "MODIFIER", "禁止 meta section")
  if forbiddenKinds.contains kind then
    issues := issues.push (stx, "FORBIDDEN", s!"禁用语法：{kind}")
  if stx.isAtom && forbiddenAtoms.contains stx.getAtomVal.trimAscii.copy then
    issues := issues.push (stx, "FORBIDDEN", s!"禁用记号：{stx.getAtomVal}")
  if stx.isIdent && stripRoot stx.getId.eraseMacroScopes == `sorryAx then
    issues := issues.push (stx, "FORBIDDEN", "sorryAx 标识符")
  if kind == `Lean.guardMsgsCmd && !stx[2].isNone then
    issues := issues.push (stx, "GUARD", "#guard_msgs 只许不带规格的精确匹配写法")
  if let some key := setting stx then
    if key == `autoImplicit || key == `relaxedAutoImplicit || (`linter).isPrefixOf key then
      issues := issues.push (stx, "OPTION", s!"禁止设置受控选项 {key}")
    else if !allowedOption key then
      issues := issues.push (stx, "OPTION", s!"选项不在白名单：{key}")
  -- 战术配置：native 与旧式 (config := …) 不许。
  match kind with
  | .str _ "posConfigItem" | .str _ "negConfigItem" =>
    if stx[1].getId.eraseMacroScopes == `native then
      issues := issues.push (stx, "FORBIDDEN", "配置项 native")
  | .str _ "valConfigItem" =>
    let key := stx[1].getId.eraseMacroScopes
    if key == `native || key == `config then
      issues := issues.push (stx, "FORBIDDEN", s!"配置项 {key}")
  | _ => pure ()
  if kind == ``Parser.Term.attrInstance then
    let attr := stx[1]
    let name := if attr.getKind == ``Parser.Attr.simple then attr[0].getId.eraseMacroScopes
      else match attr.getKind with
        | .str _ s => .mkSimple s
        | _ => .anonymous
    if !attributeNames.contains name then
      issues := issues.push (stx, "ATTRIBUTE", s!"属性不在白名单：{name}")
  if kind == `Lean.Parser.Command.eraseAttr && !attributeNames.contains stx[1].getId.eraseMacroScopes then
    issues := issues.push (stx, "ATTRIBUTE", s!"属性不在白名单：{stx[1].getId}")
  if kind == `Lean.Parser.Command.derivingClass then
    let target := stx[1]
    if !(target.isIdent && derivingClasses.contains (stripRoot target.getId.eraseMacroScopes)) then
      issues := issues.push (stx, "DERIVING", s!"派生目标类不在白名单：{target}")
  for i in [:stx.getArgs.size] do
    let child := stx[i]
    if kind == `Lean.Parser.Command.mutual && i == 1 then
      for cmd in child.getArgs do issues := issues ++ inspect mod cmd true guarded
    else if kind == `Lean.guardMsgsCmd && i == 4 then
      issues := issues ++ inspect mod child true true
    else
      let nested := kind == `Lean.Parser.Command.in && (i == 0 || i == 2)
      issues := issues ++ inspect mod child nested guarded
  return issues

partial def kindsOf (stx : Syntax) (acc : NameSet) : NameSet :=
  match stx with
  | .node _ k args => args.foldl (fun a s => kindsOf s a) (acc.insert k)
  | _ => acc

def scopeKinds : Array Name :=
  #[`Lean.Parser.Command.namespace, `Lean.Parser.Command.section, `Lean.Parser.Command.end,
    `Lean.Parser.Command.open]

/-- 只精化作用域命令。`open` 里出现被审命名空间（库环境里不存在）时逐个重试、忽略失败。 -/
def scopeElab (cmd : Syntax) : CommandElabM Unit := do
  try elabCommand cmd
  catch _ =>
    if cmd.getKind == `Lean.Parser.Command.open then
      let decl := cmd[1]
      let (isScoped, ids) :=
        if decl.getKind == `Lean.Parser.Command.openSimple then (false, decl[0].getArgs)
        else if decl.getKind == `Lean.Parser.Command.openScoped then (true, decl[1].getArgs)
        else (false, #[])
      for id in ids do
        let id : Ident := ⟨id⟩
        let one ← if isScoped then `(open scoped $id:ident) else `(open $id:ident)
        try elabCommand one catch _ => pure ()

structure Result where
  commands : Nat := 0
  scopeCmds : Nat := 0
  issues : Array (Nat × String × String) := #[]
  kinds : NameSet := {}
  parseError : Option String := none

partial def walk (ctx : Parser.InputContext) (mod : Name) : Frontend.FrontendM Result := do
  let mut r : Result := {}
  repeat
    Frontend.updateCmdPos
    let state ← Frontend.getCommandState
    let ps ← Frontend.getParserState
    let scope := state.scopes.head!
    let (cmd, next, msgs) := Parser.parseCommand ctx
      { env := state.env, options := scope.opts, currNamespace := scope.currNamespace,
        openDecls := scope.openDecls } ps {}
    if msgs.hasErrors then
      let first ← (msgs.toList.filter (·.severity == .error)).head!.toString
      r := { r with parseError := some first }
      break
    if Parser.isTerminalCommand cmd then break
    r := { r with commands := r.commands + 1, kinds := kindsOf cmd r.kinds }
    let found := inspect mod cmd true false
    r := { r with issues := r.issues ++ found.map fun (s, c, d) =>
      ((ctx.fileMap.toPosition (s.getPos?.getD (cmd.getPos?.getD 0))).line, c, d) }
    Frontend.setParserState next
    if scopeKinds.contains cmd.getKind then
      r := { r with scopeCmds := r.scopeCmds + 1 }
      Frontend.runCommandElabM (scopeElab cmd)
  return r

def headerIssues (header : HeaderSyntax) : Array (Nat × String × String) := Id.run do
  let mut issues := #[]
  if !header.isModule then issues := issues.push (1, "HEADER", "源码第一条命令必须是 module")
  if !header.raw[1].isNone then issues := issues.push (1, "HEADER", "禁止 prelude")
  for imp in header.imports false do
    let root := imp.module.getRoot
    if imp.isMeta || imp.importAll then
      issues := issues.push (1, "IMPORT", s!"禁止 meta import 或 import all：{imp.module}")
    else if !(projectRoots.contains root || libraryRoots.contains root) then
      issues := issues.push (1, "IMPORT", s!"导入来源不在白名单：{imp.module}")
  return issues

def readHeader (path : String) :
    IO (Parser.InputContext × HeaderSyntax × Parser.ModuleParserState × MessageLog) := do
  let ctx := Parser.mkInputContext (← IO.FS.readFile path) path
  let (header, ps, msgs) ← Parser.parseHeader ctx
  return (ctx, header, ps, msgs)

def headers (paths : List String) : IO UInt32 := do
  for path in paths do
    let (_, header, _, msgs) ← readHeader path
    let imports := (header.imports false).map fun imp => imp.module.toString
    IO.println <| (Json.arr #[toJson path, toJson header.isModule, toJson msgs.hasErrors,
      toJson imports]).compress
  return 0

unsafe def scan (libs : String) (mode : String) (items : List String) : IO UInt32 := do
  let libImports : Array Import := (libs.splitOn ",").toArray.filterMap fun s =>
    if s.isEmpty then none else some { module := s.toName }
  let imports := if libImports.any (·.module == `Init) then libImports
    else #[({ module := `Init } : Import)] ++ libImports
  enableInitializersExecution
  let t0 ← IO.monoMsNow
  let env ← importModules imports {} (loadExts := true) (level := .exported)
  let t1 ← IO.monoMsNow
  IO.eprintln s!"imported {env.header.moduleNames.size} modules in {t1 - t0} ms"
  for item in items do
    let [modStr, path] := item.splitOn "=" | throw (IO.userError s!"bad item {item}")
    let mod := modStr.toName
    let (ctx, header, ps, msgs) ← readHeader path
    let mut early := headerIssues header
    if msgs.hasErrors then early := early.push (1, "PARSE", "头部解析失败")
    let t2 ← IO.monoMsNow
    let (r, _) ← ((walk ctx mod).run { inputCtx := ctx }).run {
      commandState := Command.mkState (env.setMainModule mod) {} {}, parserState := ps, cmdPos := ps.pos }
    let t3 ← IO.monoMsNow
    let issues := early ++ r.issues
    let issueJson := issues.map fun (line, code, detail) => Json.arr #[toJson line, toJson code, toJson detail]
    let kinds := if mode == "kinds" then r.kinds.toArray.map (·.toString) |>.qsort (· < ·) else #[]
    IO.println <| (Json.mkObj [("path", toJson path), ("module", toJson modStr),
      ("commands", toJson r.commands), ("scope_cmds", toJson r.scopeCmds),
      ("parse_error", toJson r.parseError), ("issues", Json.arr issueJson),
      ("kinds", toJson kinds), ("ms", toJson (t3 - t2))]).compress
  return 0

end Shape

unsafe def main (args : List String) : IO UInt32 := do
  match args with
  | "headers" :: paths => Shape.headers paths
  | "scan" :: libs :: mode :: items => Shape.scan libs mode items
  | _ => IO.eprintln "usage: headers <paths> | scan <libs> <check|kinds> <mod=path>..."; return 2
