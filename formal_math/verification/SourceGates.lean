module

public import Lean
public import verification.Perimeter

open Lean Elab Command

namespace FM

public section

-- 只信 Lean 解析的头部；不把隐式 Init 导入当成源码中的边。
private def readHeader (path : String) :
    IO (Parser.InputContext × HeaderSyntax × Parser.ModuleParserState × MessageLog) := do
  let ctx := Parser.mkInputContext (← IO.FS.readFile path) path
  let (header, ps, msgs) ← Parser.parseHeader ctx
  if msgs.hasErrors then
    for m in msgs.toList do IO.eprintln (← m.toString)
    throw (IO.userError s!"{path}: 头部解析失败")
  return (ctx, header, ps, msgs)

def headers (paths : List String) : IO UInt32 := do
  for path in paths do
    let (ctx, header, _, _) ← readHeader path
    let imports := header.imports false
    let rows := imports.mapIdx fun i imp =>
      let pos := (header.raw[2][i]!).getPos?.getD 0
      Json.arr #[toJson imp.module.toString, toJson (ctx.fileMap.toPosition pos).line, toJson imp.importAll]
    IO.println <| (Json.arr #[toJson path, toJson header.isModule, toJson rows]).compress
  return 0

/-- 审计程序自身；只有它们可以导入 `Lean`、使用 `import all` 与元编程。 -/
def auditTools : Array Name :=
  #[`verification.Audit, `verification.EnvGates, `verification.SourceGates, `verification.Perimeter,
    `verification.Inventory]

/-- 包内可信目录。`ChanExplore` 按同一白名单审，另外只多放行 `#eval`。 -/
private def trustedRoots : Array Name := #[`Chan, `ChanChallenge, `ChanDyn, `ChanTest]

/-- 可信目录允许导入的外部库根。 -/
private def libraryRoots : Array Name := #[`Init, `Std, `Mathlib, `Batteries]

/-- 钉选在 lake-manifest 里但可信目录不许导入的外部库根。导入它们只加载库代码，红后仍继续精化。 -/
private def pinnedRoots : Array Name :=
  #[`Lean, `Lake, `Qq, `Aesop, `Plausible, `ProofWidgets, `LeanSearchClient, `ImportGraph, `Cli]

private def commandKinds : Array Name :=
  #[`Lean.Parser.Command.moduleDoc, `Lean.Parser.Command.namespace, `Lean.Parser.Command.section,
    `Lean.Parser.Command.end, `Lean.Parser.Command.open, `Lean.Parser.Command.variable,
    `Lean.Parser.Command.universe, `Lean.Parser.Command.include, `Lean.Parser.Command.omit,
    `Lean.Parser.Command.in, `Lean.Parser.Command.declaration, `Lean.Parser.Command.mutual,
    `Lean.Parser.Command.set_option, `Lean.Parser.Command.check, `Lean.Parser.Command.attribute,
    `Lean.Parser.Command.deriving]

/-- 只会出现在 Lean 自己生成的命令里（`cmd in` 展开）的内部命令。 -/
private def generatedCommandKinds : Array Name :=
  #[`Lean.Parser.Command.InternalSyntax.end_local_scope]

private def declarations : Array Name :=
  #[`Lean.Parser.Command.definition, `Lean.Parser.Command.theorem, `Lean.Parser.Command.abbrev,
    `Lean.Parser.Command.opaque, `Lean.Parser.Command.example, `Lean.Parser.Command.inductive,
    `Lean.Parser.Command.classInductive, `Lean.Parser.Command.structure,
    `Lean.Parser.Command.instance]

/--
属性白名单，按 Lean `elabAttr` 的取名规则比对（属性宏先展开；`Attr.simple` 取标识符，
其余取语法种类的末段）。注册宏、精化器、解析器、初始化器、派生处理器与改写编译产物的属性
（`macro`、`*_elab`、`*_parser`、`init`、`builtin_*`、`derive_handler`、`implemented_by`、
`extern`、`export`、`csimp` 等）都不在名单里。
-/
private def attributeNames : Array Name :=
  #[`simp, `ext, `instance, `reducible, `irreducible, `inline, `specialize, `expose, `no_expose,
    `grind, `norm_cast, `push_cast, `refl, `symm, `trans, `gcongrAttr, `mono, `congr, `elab_as_elim,
    `induction_eliminator, `cases_eliminator, `deprecated, `simps, `method_specs]

/-- 派生目标类白名单；按解析后的全名比对。 -/
private def derivingClasses : Array Name :=
  #[`DecidableEq, `BEq, `ReflBEq, `LawfulBEq, `Hashable, `Ord, `Repr, `Inhabited, `Nonempty]

private def forbidden : Array Name :=
  #[`Lean.Parser.Term.sorry, `Lean.Parser.Tactic.tacticAdmit, `Lean.Parser.Tactic.tacticSorry,
    `Lean.Parser.Tactic.nativeDecide, `Lean.Parser.Tactic.runTac, `Lean.Parser.Term.runMeta,
    `Lean.Parser.Attr.extern, `Lean.Parser.Command.meta, `Lean.Parser.Command.unsafe]

private partial def placeholder (stx : Syntax) : Option Syntax :=
  if #[`Lean.Parser.Term.sorry, `Lean.Parser.Tactic.tacticAdmit,
       `Lean.Parser.Tactic.tacticSorry].contains stx.getKind ||
    (stx.isIdent && stx.getId == `sorryAx) then some stx
  else stx.getArgs.findSome? placeholder

private partial def idents (stx : Syntax) : Array Name :=
  if stx.isIdent then #[stx.getId.eraseMacroScopes] else stx.getArgs.flatMap idents

/--
凡是首个子节点为 `set_option` 关键字的语法节点都按选项设置处理，不按节点种类列名单：
命令、项、战术、`grind` 内以及今后新增的同形语法位置都在此列。
-/
private def setting (stx : Syntax) : Option Name :=
  if stx.getNumArgs ≥ 2 && stx[0].isAtom && stx[0].getAtomVal.trimAscii.copy == "set_option" then
    some (idents stx[1] |>.foldl (· ++ ·) .anonymous)
  else none

/-- 可信源码允许设置的普通选项；不影响内核检查、告警与受控选项。 -/
private def allowedOption (key : Name) : Bool :=
  [`maxRecDepth, `maxHeartbeats, `synthInstance.maxHeartbeats, `synthInstance.maxSize,
    `match.ignoreUnusedAlts].contains key || (`pp).isPrefixOf key

/-- 门 2 管受控选项，门 3 管其余选项的白名单。 -/
private def optionIssues (ref : Syntax) (key : Name) : Array (Syntax × String × String) :=
  if key == `autoImplicit || key == `relaxedAutoImplicit then
    #[(ref, "2", s!"禁止设置受控选项 {key}")]
  else if (`linter).isPrefixOf key then
    #[(ref, "2", s!"禁止设置受控选项 {key}"), (ref, "3", s!"禁止设置受控选项 {key}")]
  else if allowedOption key then #[]
  else #[(ref, "3", s!"选项不在白名单：{key}")]

private def allowedCommand (mod : Name) (generated : Bool) (stx : Syntax) : Bool :=
  commandKinds.contains stx.getKind ||
    -- 只读命令，只许出现在 Chan/Final 的 #guard_msgs 里（inspect 另查嵌套位置）。
    (stx.getKind == `Lean.Parser.Command.printAxioms && (`Chan.Final).isPrefixOf mod) ||
    (generated && generatedCommandKinds.contains stx.getKind) ||
    (stx.getKind == `Lean.guardMsgsCmd && (`Chan.Final).isPrefixOf mod)

/--
纯语法检查。`generated` 为真时检查的是 Lean 实际精化的命令（含宏与精化器生成的命令）：
同一白名单，只是 `partial` 交给环境层按生成来源判定（派生处理器会生成 `partial def`）。
`guarded` 为真时处于 `#guard_msgs` 之内，声明会借期望消息吞掉告警，一律不许。
-/
private partial def inspect (mod : Name) (stx : Syntax) (command generated guarded : Bool) :
    Array (Syntax × String × String) := Id.run do
  let kind := stx.getKind
  let mut issues := #[]
  if command && !allowedCommand mod generated stx then
    issues := issues.push (stx, "3", s!"命令不在白名单：{kind}")
  if command && !guarded && kind == `Lean.Parser.Command.printAxioms then
    issues := issues.push (stx, "3", "#print axioms 只许出现在 #guard_msgs 内")
  if command && guarded &&
      ![`Lean.Parser.Command.check, `Lean.Parser.Command.printAxioms].contains kind then
    issues := issues.push (stx, "3", s!"#guard_msgs 内只许 #check 与 #print axioms：{kind}")
  if kind == `Lean.Parser.Command.declaration && !declarations.contains stx[1].getKind then
    issues := issues.push (stx[1], "3", s!"声明不在白名单：{stx[1].getKind}")
  if kind == `Lean.Parser.Command.section && !stx[0][3].isNone then
    issues := issues.push (stx, "3", "禁止 meta section")
  if forbidden.contains kind || (!generated && kind == `Lean.Parser.Command.partial) ||
      stx.isAtom && ["implemented_by", "native_decide", "run_tac", "run_meta"].contains stx.getAtomVal ||
      stx.isIdent && stx.getId.eraseMacroScopes == `sorryAx then
    issues := issues.push (stx, "3", s!"源码含禁用语法：{kind}")
  -- 规格元素一律不许：substring、drop、whitespace、ordering、按严重度过滤都会放宽精确匹配。
  if kind == `Lean.guardMsgsCmd && !stx[2].isNone then
    issues := issues.push (stx, "3", "#guard_msgs 只许不带规格的精确匹配写法")
  if let some key := setting stx then
    issues := issues ++ optionIssues stx key
  -- 复合命令内仍按命令验白名单，不能用 in、mutual 或 #guard_msgs 藏命令。
  for i in [:stx.getArgs.size] do
    let child := stx[i]
    if kind == `Lean.Parser.Command.mutual && i == 1 then
      for cmd in child.getArgs do issues := issues ++ inspect mod cmd true generated guarded
    else if kind == `Lean.guardMsgsCmd && i == 4 then
      issues := issues ++ inspect mod child true generated true
    else
      let nested := kind == `Lean.Parser.Command.in && (i == 0 || i == 2)
      issues := issues ++ inspect mod child nested generated guarded
  return issues

private partial def collect (p : Syntax → Bool) (stx : Syntax) : Array Syntax :=
  (if p stx then #[stx] else #[]) ++ stx.getArgs.flatMap (collect p)

/-- 与 `Lean.Elab.elabAttr` 相同的取名规则：先展开属性宏。 -/
private def attributeName (attr : Syntax) : CommandElabM (Option Name) := do
  let attr ← try liftMacroM <| expandMacros attr catch _ => pure attr
  if attr.getKind == ``Parser.Attr.simple then return some attr[0].getId.eraseMacroScopes
  match attr.getKind with
  | .str _ s => return some (.mkSimple s)
  | _ => return none

/-- 属性与派生目标类要在当前作用域里解析，放在精化器单子里查。 -/
private def scopedIssues (stx : Syntax) : CommandElabM (Array (Syntax × String × String)) := do
  let mut issues := #[]
  for inst in collect (·.getKind == ``Parser.Term.attrInstance) stx do
    let name ← attributeName inst[1]
    unless name.any attributeNames.contains do
      issues := issues.push (inst, "3", s!"属性不在白名单：{name.getD inst[1].getKind}")
  for erase in collect (·.getKind == `Lean.Parser.Command.eraseAttr) stx do
    unless attributeNames.contains erase[1].getId.eraseMacroScopes do
      issues := issues.push (erase, "3", s!"属性不在白名单：{erase[1].getId}")
  for cls in collect (·.getKind == `Lean.Parser.Command.derivingClass) stx do
    let target := cls[1]
    let resolved ← if target.isIdent then
        try some <$> resolveGlobalConstNoOverload target catch _ => pure none
      else pure none
    unless resolved.any derivingClasses.contains do
      issues := issues.push (cls, "3", s!"派生目标类不在白名单：{target}")
  return issues

private def commandCategory (env : Environment) (kind : SyntaxNodeKind) : Bool :=
  ((Parser.parserExtension.getState env).categories.find? `command).any (·.kinds.contains kind)

/--
Lean 实际精化过的东西都记在信息树里：每条被精化的命令（含宏展开与精化器生成的命令）留
`CommandInfo`，每次选项设置都经 `Lean.Elab.elabSetOption` 留 `OptionInfo`。逐节点过白名单。
-/
private partial def elaborated (mod : Name) (env : Environment) (fallback : Syntax) :
    InfoTree → CommandElabM (Array (Syntax × String × String))
  | .context _ t => elaborated mod env fallback t
  -- Lean 没留下内容的空洞（如 decreasing_by 证明的战术信息）无从核对；其中手写的部分已过表层检查。
  | .hole _ => return #[]
  | .node info children => do
    let mut issues := #[]
    match info with
    | .ofCommandInfo ci =>
      if commandCategory env ci.stx.getKind then
        let ref := if ci.stx.getPos?.isSome then ci.stx else fallback
        issues := (inspect mod ci.stx true true false).map fun (s, g, d) =>
          (if s.getPos?.isSome then s else ref, g, d)
        issues := issues ++ ((← scopedIssues ci.stx).map fun (s, g, d) =>
          (if s.getPos?.isSome then s else ref, g, d))
    | .ofOptionInfo oi =>
      issues := optionIssues (if oi.stx.getPos?.isSome then oi.stx else fallback) oi.optionName
    | _ => pure ()
    for child in children do
      issues := issues ++ (← elaborated mod env fallback child)
    return issues

private def exposure (stx : Syntax) : Bool :=
  stx.getKind == `Lean.Parser.Command.section &&
    stx[0][0].getArgs.any (fun a => a.isAtom && a.getAtomVal == "expose") &&
    stx[0][1][0].getAtomVal == "public"

private def gate3Blocked (issues : Array (Syntax × String × String)) : Bool :=
  issues.any fun (_, gate, _) => gate == "3"

/--
`preCheck` 为假只供 `selfcheck` 用固定样例核对展开后检查本身；命令行入口恒为真。
-/
private def controlled (opts : Options) : List (Name × String) := Id.run do
  let mut out := []
  for (k, v) in opts do
    if k == `autoImplicit || k == `relaxedAutoImplicit || (`linter).isPrefixOf k then
      out := (k, s!"{v}") :: out
  return out

/-- 本命令新增的常量（第二阶段的本地常量表）。 -/
private def localNames (env : Environment) : NameSet :=
  env.constants.foldStage2 (fun s n _ => s.insert n) {}

/--
派生证书：本命令新增、声明范围落在某个派生目标类语法节点（`derivingClass`）之内的常量。
派生处理器在 `withRef` 该节点下精化生成的命令，手写声明的范围在它自己的语法上。
-/
private def derivedBy (ctx : Parser.InputContext) (cmd : Syntax) (fresh : Array Name) :
    CommandElabM (Array Name) := do
  let spans := (collect (·.getKind == `Lean.Parser.Command.derivingClass) cmd).filterMap fun c => do
    return (ctx.fileMap.toPosition (← c.getPos?), ctx.fileMap.toPosition (← c.getTailPos?))
  if spans.isEmpty then return #[]
  let le (x y : Position) := x.line < y.line || (x.line == y.line && x.column ≤ y.column)
  let inside (p a b : Position) := le a p && le p b
  fresh.filterM fun n => do
    let some r ← findDeclarationRanges? n | return false
    return spans.any fun (a, b) => inside r.range.pos a b

/-- 源码层的 partial 来源：只许派生证书里的辅助函数与结构／良基递归定义的编译影子。 -/
private def partialIssues (cmd : Syntax) (fresh : Array Name) (derived : Array Name) :
    CommandElabM (Array (Syntax × String × String)) := do
  let env ← getEnv
  let mut issues := #[]
  for n in fresh do
    let some info := env.find? n | continue
    unless info.isPartial do continue
    let source := (Compiler.isUnsafeRecName? n).getD n
    let recursive ← match env.find? source with
      | some (.defnInfo d) => pure (d.safety == .safe) <&&> liftCoreM (Meta.isRecursiveDefinition source)
      | _ => pure false
    unless recursive || derived.contains source do
      issues := issues.push (cmd, "3", s!"partial 定义 {n}：源定义 {source} 不是派生产物或结构／良基递归")
  return issues

private def walk (ctx : Parser.InputContext) (mod : Name) (auditTool preCheck : Bool)
    (lists : Perimeter.Lists) :
    Frontend.FrontendM (Bool × Array (Syntax × String × String) × Array Name) := do
  let mut issues := #[]
  let mut exposes := false
  let mut derived := #[]
  -- 一条命令被拒后，余下命令只做精化前的检查、不再精化，让其他门（如门 2 的局部选项）仍有读数。
  let mut stopped := false
  repeat
    Frontend.updateCmdPos
    let state ← Frontend.getCommandState
    let ps ← Frontend.getParserState
    let scope := state.scopes.head!
    let (cmd, next, msgs) := Parser.parseCommand ctx
      { env := state.env, options := scope.opts, currNamespace := scope.currNamespace,
        openDecls := scope.openDecls } ps {}
    if msgs.hasErrors then
      if stopped then break  -- 前面的命令没有精化，后文解析不出来不另作判断。
      for m in msgs.toList do IO.eprintln (← m.toString)
      throw (IO.userError s!"{ctx.fileName}: 命令解析失败")
    if cmd.getKind == `Lean.Parser.Command.eoi then break
    exposes := exposes || exposure cmd
    let found ← if auditTool then
        pure ((placeholder cmd).map fun s => (s, "3", "审计工具不能使用占位证明")).toArray
      else if preCheck then
        -- 精化之前：命令白名单 + 语法种类与处理器白名单；名单外的节点不进入精化。
        pure <| inspect mod cmd true false false ++ Perimeter.kindIssues lists state.env cmd cmd ++
          (← Frontend.runCommandElabM (scopedIssues cmd))
      else pure #[]
    issues := issues ++ found
    -- 不执行已经被拒绝的命令或项。已拒绝的文件不会进入构建或环境门。
    if stopped || gate3Blocked found then
      stopped := true
      if Parser.isTerminalCommand cmd then break
      Frontend.setParserState next
      continue
    if Parser.isTerminalCommand cmd then
      throw (IO.userError s!"{ctx.fileName}: 文件头之后的终止命令")
    Frontend.setParserState next
    let before := localNames state.env
    let optionsBefore := controlled scope.opts
    -- 精化之中：各处理表里名单外的处理器擦除；宏展开出的名单外语法找不到处理器。
    -- selfcheck 要先精化样例里的宏定义本身，不封表。
    if !auditTool && preCheck then
      Frontend.runCommandElabM <| modifyEnv (Perimeter.sealTables lists)
    Frontend.elabCommandAtFrontend cmd
    let state ← Frontend.getCommandState
    unless auditTool do
      let fresh := (localNames state.env).toArray.filter (!before.contains ·)
      let mine ← Frontend.runCommandElabM (derivedBy ctx cmd fresh)
      derived := derived ++ mine
      let partials ← Frontend.runCommandElabM (partialIssues cmd fresh mine)
      -- 占位证明按 Lean 自己打的 `hasSorry` 标签认，不看名字怎么写。
      let sorries := state.messages.toList.filter (·.data.hasTag (· == `hasSorry)) |>.map fun _ =>
        (cmd, "3", "声明使用了占位证明（sorry）")
      -- 命令级的受控选项前后须一致；项内局部改了又恢复的看不见，见 README。
      let optionsAfter := controlled (state.scopes.headD default).opts
      let drift := if optionsAfter != optionsBefore then
          #[(cmd, "2", s!"命令前后受控选项不一致：{optionsBefore} → {optionsAfter}")] else #[]
      let infosFinal := (state.infoState.substituteLazy).get
      let perimeter := infosFinal.trees.toArray.flatMap fun t =>
        Perimeter.infoIssues lists state.env cmd (t.substitute infosFinal.assignment)
      let extra := partials ++ sorries.toArray ++ drift ++ perimeter
      let extra := extra.filter fun (s, g, d) =>
        !found.any fun (s', g', d') => g == g' && d == d' && s.getPos? == s'.getPos?
      issues := issues ++ extra
      if preCheck && gate3Blocked extra then stopped := true
      -- 异步登记的子树（如 decreasing_by 的证明）先等齐再展开空洞。
      let infos := (state.infoState.substituteLazy).get
      let after ← Frontend.runCommandElabM do
        let env ← getEnv
        infos.trees.toArray.flatMapM fun t => elaborated mod env cmd (t.substitute infos.assignment)
      -- 表层已报过的同一处不重复报。
      let fresh := after.filter fun (s, g, d) =>
        !found.any fun (s', g', d') => g == g' && d == d' && s.getPos? == s'.getPos?
      issues := issues ++ fresh
      if preCheck && gate3Blocked fresh then stopped := true
    if state.messages.hasErrors then
      for m in state.messages.toList do
        if m.severity == .error then IO.eprintln (← m.toString)
      issues := issues.push (cmd, "build", "语法已解析，Lean 拒绝精化该命令")
      break
  return (exposes, issues, derived)

/-- 头部白名单。第二个返回值为真时不得继续加载导入或精化。 -/
private def headerIssues (mod : Name) (header : HeaderSyntax) :
    Array (Syntax × String × String) × Bool := Id.run do
  let mut issues := #[]
  let mut fatal := false
  if !header.isModule then
    return (#[(header.raw, "3", "源码第一条命令必须是 module")], true)
  if !header.raw[1].isNone then
    return (#[(header.raw, "3", "禁止 prelude")], true)
  let explore := (`ChanExplore).isPrefixOf mod
  for imp in header.imports false, i in [:header.raw[2].getNumArgs] do
    let ref := header.raw[2][i]
    let root := imp.module.getRoot
    if imp.isMeta || imp.importAll then
      issues := issues.push (ref, "3", s!"禁止 meta import 或 import all：{imp.module}")
      fatal := true
    else if trustedRoots.contains root || libraryRoots.contains root ||
        (explore && root == `ChanExplore) then
      pure ()
    else if pinnedRoots.contains root then
      issues := issues.push (ref, "3", s!"可信目录不得导入 {imp.module}")
    else
      issues := issues.push (ref, "3", s!"导入来源不在白名单：{imp.module}")
      fatal := true
  return (issues, fatal)

/-- olean 位于工具链或钉选包目录时才算库代码；其余（本包构建产物）一律视为被审代码。 -/
private def libraryModule (roots : Array String) (mod : Name) : IO Bool := do
  let path := (← IO.FS.realPath (← findOLean mod)).toString
  return roots.any fun root => path.startsWith (root ++ "/")

/--
不运行任何初始化器读入导入闭包，找出被审代码的模块：登记到 `interpretedModInits`，让随后的
`processHeader` 跳过它们的 `[init]`；若其中有 `meta` 声明（宏、精化器等只能是 `meta`），
拒绝精化，审计期不执行任何被审代码。
-/
private def quarantine (header : HeaderSyntax) (opts : Options) :
    IO (Option String) := do
  let env ← importModules header.imports opts (loadExts := false) (level := .private)
  let sysroot ← IO.FS.realPath ((← findSysroot) / "lib" / "lean")
  let packages ← if ← System.FilePath.isDir (".lake" / "packages") then
      pure #[(← IO.FS.realPath (".lake" / "packages")).toString]
    else pure #[]
  let roots := #[sysroot.toString] ++ packages
  for mod in env.header.moduleNames, data in env.header.moduleData do
    if ← libraryModule roots mod then continue
    interpretedModInits.modify (·.insert mod)
    if let some n := data.constNames.find? (isMarkedMeta env ·) then
      return some s!"导入的本地模块 {mod} 含 meta 声明 {n}，审计拒绝执行被审代码"
  return none

unsafe def source (mod : Name) (path gate : String) : IO UInt32 := do
  let (ctx, header, ps, msgs) ← readHeader path
  let opts := (Elab.async.set {} false).setBool `linter.unusedVariables true
    |>.setBool `autoImplicit false |>.setBool `relaxedAutoImplicit false
  let auditTool := auditTools.contains mod
  let lists ← Perimeter.load
  let (early, fatal) := if auditTool then (#[], false) else headerIssues mod header
  let report (exposes : Bool) (issues : Array (Syntax × String × String))
      (derived : Array Name := #[]) : IO UInt32 := do
    let lines := issues.map fun (stx, gate, detail) =>
      Json.arr #[toJson gate, toJson (ctx.fileMap.toPosition (stx.getPos?.getD 0)).line, toJson detail]
    IO.println <| (Json.arr #[toJson exposes, toJson lines,
      toJson (derived.map (·.toString))]).compress
    let has (g : String) := issues.any fun (_, number, _) => number == g
    let blocked := has "3" || has "build"
    return match gate with
      | "2" => if has "2" || has "build" then 1 else if blocked then 2 else 0
      | "3" => if has "3" then 1 else if blocked then 2 else 0
      | "15" => if blocked then 2
        else if !header.isModule || ((`Chan.Defs).isPrefixOf mod && !exposes) then 1 else 0
      | _ => if issues.isEmpty then 0 else 1
  if fatal then return ← report false early
  if let some detail ← quarantine header opts then
    return ← report false (early.push (header.raw, "3", detail))
  enableInitializersExecution
  let (env, msgs) ← processHeader header opts msgs ctx (mainModule := mod)
  if msgs.hasErrors then
    for m in msgs.toList do IO.eprintln (← m.toString)
    throw (IO.userError s!"{path}: 导入加载失败")
  let ((exposes, issues, derived), _) ← ((walk ctx mod auditTool true lists).run { inputCtx := ctx }).run {
    commandState := Command.mkState env msgs opts, parserState := ps, cmdPos := ps.pos }
  report exposes (early ++ issues) derived

/-- 不经表层预检，直接精化一段固定样例，核对展开后检查能看到宏生成的命令与选项。 -/
private def selfcheckSource : String := "import Lean
open Lean in
macro \"fm_selfcheck\" : command => do
  let a ← `(set_option linter.unusedVariables false)
  let b ← `(@[implemented_by Nat.succ] def fmSelfcheckImpl (n : Nat) : Nat := n)
  let c ← `(#print Nat)
  let d ← `(theorem fmSelfcheckThm : 1 = 1 := by rfl')
  return ⟨mkNullNode #[a, b, c, d]⟩
fm_selfcheck
"

unsafe def selfcheck : IO UInt32 := do
  let ctx := Parser.mkInputContext selfcheckSource "<selfcheck>"
  let (header, ps, msgs) ← Parser.parseHeader ctx
  let opts := Elab.async.set {} false
  enableInitializersExecution
  let (env, msgs) ← processHeader header opts msgs ctx (mainModule := `Chan.Thm.SelfCheck)
  if msgs.hasErrors then
    for m in msgs.toList do IO.eprintln (← m.toString)
    return 2
  let lists ← Perimeter.load
  let ((_, issues, _), _) ← ((walk ctx `Chan.Thm.SelfCheck false false lists).run { inputCtx := ctx }).run {
    commandState := Command.mkState env msgs opts, parserState := ps, cmdPos := ps.pos }
  -- 宏定义本身（第 3 行）不在白名单；这里只看宏展开所在的第 9 行。
  let expanded := issues.filter fun (stx, _, _) =>
    (ctx.fileMap.toPosition (stx.getPos?.getD 0)).line == 9
  let expected := [("2", "禁止设置受控选项 linter.unusedVariables"),
    ("3", "属性不在白名单：implemented_by"), ("3", "命令不在白名单：Lean.Parser.Command.print"),
    ("3", "选项不在白名单：smartUnfolding")]
  for (gate, detail) in expected do
    let hit := expanded.any fun (_, g, d) => g == gate && d == detail
    IO.println s!"{if hit then "通过" else "失败"}\t门 {gate}\t{detail}"
  for (_, g, d) in issues do IO.eprintln s!"[{g}] {d}"
  return if expected.all (fun (g, d) => expanded.any fun (_, g', d') => g == g' && d == d') then 0 else 1

end
end FM
