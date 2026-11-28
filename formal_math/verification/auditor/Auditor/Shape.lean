module

public import Lean
public import Auditor.EnvGates

/-!
源码形状门（#2312 第四片）：只解析、不精化。诚实作者断言，规则与「不防什么」见 `runner/README.md`。

* `shape-plan <模块> <路径> ...`：只解析文件头，按 Lean 模块制的导入规则算出每个文件在真实构建里会加载的
  库模块集合（直接导入全部算；经被审模块传下来的只算 `public import`），供运行脚本按集合分组。
* `shape <库模块>... -- <模块> <路径> ...`：一个进程只加载这一组库导入的环境（钉选库，不加载任何被审模块），
  逐条解析命令；只把作用域命令（`namespace`、`section`、`end`、`open`）交给 Lean 处理以维持解析状态，
  声明、项、战术一律不精化。每条命令的语法树过白名单与禁用清单。
-/

open Lean Elab Command

namespace FM.Shape

/-- 命令白名单（旧 `SourceGates.commandKinds` 原样）。 -/
private def commandKinds : Array Name :=
  #[`Lean.Parser.Command.moduleDoc, `Lean.Parser.Command.namespace, `Lean.Parser.Command.section,
    `Lean.Parser.Command.end, `Lean.Parser.Command.open, `Lean.Parser.Command.variable,
    `Lean.Parser.Command.universe, `Lean.Parser.Command.include, `Lean.Parser.Command.omit,
    `Lean.Parser.Command.in, `Lean.Parser.Command.declaration, `Lean.Parser.Command.mutual,
    `Lean.Parser.Command.set_option, `Lean.Parser.Command.check, `Lean.Parser.Command.attribute,
    `Lean.Parser.Command.deriving]

/-- 声明种类白名单（旧 `SourceGates.declarations` 原样）。 -/
private def declKinds : Array Name :=
  #[`Lean.Parser.Command.definition, `Lean.Parser.Command.theorem, `Lean.Parser.Command.abbrev,
    `Lean.Parser.Command.opaque, `Lean.Parser.Command.example, `Lean.Parser.Command.inductive,
    `Lean.Parser.Command.classInductive, `Lean.Parser.Command.structure,
    `Lean.Parser.Command.instance]

/--
修饰符白名单：`declModifiers` 各槽位里允许出现的语法种类。`meta`、`unsafe`、`partial` 不在名单里
（旧实现把它们列在禁用种类里；`partial` 在源码层一律不许，派生处理器生成的 `partial` 由环境层按证书豁免）。
-/
private def modifierKinds : Array Name :=
  #[`Lean.Parser.Command.docComment, `Lean.Parser.Term.attributes, `Lean.Parser.Command.private,
    `Lean.Parser.Command.public, `Lean.Parser.Command.protected, `Lean.Parser.Command.noncomputable,
    `Lean.Parser.Command.nonrec]

/--
属性白名单（旧 `SourceGates.attributeNames` 原样）。按 Lean `elabAttr` 的取名规则比对：`Attr.simple`
取标识符，其余取语法种类的末段。旧实现先展开属性宏再取名；本门只解析，不展开（见 README 出入表）。
-/
private def attributeNames : Array Name :=
  #[`simp, `ext, `instance, `reducible, `irreducible, `inline, `specialize, `expose, `no_expose,
    `grind, `norm_cast, `push_cast, `refl, `symm, `trans, `gcongrAttr, `mono, `congr, `elab_as_elim,
    `induction_eliminator, `cases_eliminator, `deprecated, `simps, `method_specs]

/-- 派生目标类白名单（旧 `SourceGates.derivingClasses` 原样），比对写出来的标识符（去掉 `_root_`）。 -/
private def derivingClasses : Array Name :=
  #[`DecidableEq, `BEq, `ReflBEq, `LawfulBEq, `Hashable, `Ord, `Repr, `Inhabited, `Nonempty]

/--
点名的禁用清单：给走捷径的作者看的提示，不是防线；漏一个的后果由沙箱与内核重放承担（见 README）。
按表层记号查：占位证明、精化期求值入口、求值命令。
-/
private def forbiddenAtoms : Array String :=
  #["sorry", "admit", "native_decide", "include_str", "eval%", "by_elab", "run_tac", "run_cmd", "run_meta",
    "run_elab", "sudo", "trace", "success_if_fail_with_msg", "#eval", "#eval!", "#exit"]

/-- 没有独有记号的禁用语法种类：项级 `unsafe`（它的记号与修饰符 `unsafe` 相同）。 -/
private def forbiddenKinds : Array Name := #[`Lean.Parser.Term.unsafe]

/-- 可信源码允许设置的普通选项（旧 `SourceGates.allowedOption` 原样）。 -/
private def allowedOption (key : Name) : Bool :=
  [`maxRecDepth, `maxHeartbeats, `synthInstance.maxHeartbeats, `synthInstance.maxSize,
    `match.ignoreUnusedAlts].contains key || (`pp).isPrefixOf key

/-- 受控选项（门 2 的源码部分）。 -/
private def controlledOption (key : Name) : Bool :=
  key == `autoImplicit || key == `relaxedAutoImplicit || (`linter).isPrefixOf key

private partial def idents (stx : Syntax) : Array Name :=
  if stx.isIdent then #[stx.getId.eraseMacroScopes] else stx.getArgs.flatMap idents

/--
凡是首个子节点为 `set_option` 关键字的语法节点都按选项设置处理，不按节点种类列名单：
命令、项、战术、`grind` 内都在此列（旧 `SourceGates.setting` 原样）。
-/
private def setting (stx : Syntax) : Option Name :=
  if stx.getNumArgs ≥ 2 && stx[0].isAtom && stx[0].getAtomVal.trimAscii.copy == "set_option" then
    some (idents stx[1] |>.foldl (· ++ ·) .anonymous)
  else none

private def stripRoot (n : Name) : Name := n.replacePrefix `_root_ .anonymous

/--
旧式配置子句，按记号形状查、不按语法种类列名单（同 `setting`）：节点的前三个子节点依次是记号 `(`、
一个名字以 `config` 结尾的记号或标识符、记号 `:=`。钉选库里实际存在的是核心 `Lean.Parser.Tactic.config`
（`(config := …)`，被 `plausible`、Batteries 的 `congr`／`rcongr` 等复用）、Aesop 的
`(config := …)`／`(simp_config := …)` 子句；前两类的取值在精化期经 `declare_config_elab` 编译求值（独审 r1
甲-1）。新式 `optConfig` 里键为 `config` 的 `valConfigItem` 形状相同，一并判红（上一版也查它）。返回子句名。
-/
private def legacyConfig (stx : Syntax) : Option String :=
  if stx.getNumArgs ≥ 3 && stx[0].isAtom && stx[0].getAtomVal.trimAscii.copy == "(" &&
      stx[2].isAtom && stx[2].getAtomVal.trimAscii.copy == ":=" then
    let key := if stx[1].isAtom then stx[1].getAtomVal.trimAscii.copy
      else if stx[1].isIdent then stx[1].getId.eraseMacroScopes.toString else ""
    if key.endsWith "config" then some key else none
  else none

private def attributeName (attr : Syntax) : Name :=
  if attr.getKind == ``Parser.Attr.simple then attr[0].getId.eraseMacroScopes
  else match attr.getKind with
    | .str _ s => .mkSimple s
    | _ => .anonymous

/-- 一条发现：(语法节点, 规则码, 说明)。 -/
abbrev Issue := Syntax × String × String

/-- Lean 4.36 的可选 docComment 在第 0 槽，原始正文是 commentBody 的首个 atom。
默认匹配把换行换成空格，所以同时检查逐行头和折叠成一行的 ` --- ` 消息分隔符。 -/
private def guardExpectsDiagnostic (stx : Syntax) : Bool :=
  let body := stx[0][0][1][0].getAtomVal
  let diagnostic (s : String) :=
    let line := s.trimAsciiStart.copy
    line.startsWith "warning:" || line.startsWith "error:"
  (body.splitOn "\n").any diagnostic ||
    ((body.replace "⏎\n" "\n" |>.replace "\n" " ").splitOn " --- ").any diagnostic

/--
对一条命令的语法树做白名单与禁用检查。`command` 为真时该节点处于命令位置（顶层、`in` 两侧、`mutual` 内、
`#guard_msgs` 内）；`guarded` 为真时处于 `#guard_msgs` 之内。
-/
private partial def inspect (mod : Name) (stx : Syntax) (command guarded : Bool) : Array Issue := Id.run do
  let kind := stx.getKind
  let final := (`Chan.Final).isPrefixOf mod
  let mut issues := #[]
  if command then
    let ok := commandKinds.contains kind ||
      (final && (kind == `Lean.guardMsgsCmd || kind == `Lean.Parser.Command.printAxioms))
    if !ok then issues := issues.push (stx, "SHAPE_COMMAND", s!"命令不在白名单：{kind}")
    if !guarded && kind == `Lean.Parser.Command.printAxioms then
      issues := issues.push (stx, "SHAPE_GUARD_MSGS", "#print axioms 只许出现在 #guard_msgs 内")
    if guarded && ![`Lean.Parser.Command.check, `Lean.Parser.Command.printAxioms].contains kind then
      issues := issues.push (stx, "SHAPE_GUARD_MSGS", s!"#guard_msgs 内只许 #check 与 #print axioms：{kind}")
  if kind == `Lean.guardMsgsCmd && !stx[2].isNone then
    issues := issues.push (stx, "SHAPE_GUARD_MSGS", "#guard_msgs 只许不带规格的精确匹配写法")
  if kind == `Lean.guardMsgsCmd && guardExpectsDiagnostic stx then
    issues := issues.push (stx, "SHAPE_GUARD_MSGS", "#guard_msgs 不得匹配 warning: 或 error: 消息")
  if kind == `Lean.Parser.Command.declaration && !declKinds.contains stx[1].getKind then
    issues := issues.push (stx[1], "SHAPE_DECL", s!"声明不在白名单：{stx[1].getKind}")
  if kind == `Lean.Parser.Command.declModifiers then
    for slot in stx.getArgs do
      unless slot.isNone do
        let k := if slot.getKind == nullKind then slot[0].getKind else slot.getKind
        unless modifierKinds.contains k do
          issues := issues.push (slot, "SHAPE_MODIFIER", s!"修饰符不在白名单：{k}")
  if kind == `Lean.Parser.Command.section && !stx[0][3].isNone then
    issues := issues.push (stx, "SHAPE_MODIFIER", "禁止 meta section")
  if forbiddenKinds.contains kind then
    issues := issues.push (stx, "SHAPE_FORBIDDEN", s!"禁用语法：{kind}")
  if stx.isAtom && forbiddenAtoms.contains stx.getAtomVal.trimAscii.copy then
    issues := issues.push (stx, "SHAPE_FORBIDDEN", s!"禁用记号：{stx.getAtomVal.trimAscii}")
  if stx.isIdent && stripRoot stx.getId.eraseMacroScopes == `sorryAx then
    issues := issues.push (stx, "SHAPE_FORBIDDEN", "禁用标识符：sorryAx")
  if let some key := setting stx then
    if controlledOption key then
      issues := issues.push (stx, "SHAPE_OPTION_CONTROLLED", s!"禁止设置受控选项 {key}")
    else if !allowedOption key then
      issues := issues.push (stx, "SHAPE_OPTION", s!"选项不在白名单：{key}")
  -- 战术配置：`+native`、`(native := …)` 不许；旧式配置子句见 `legacyConfig`。
  if let some key := legacyConfig stx then
    issues := issues.push (stx, "SHAPE_FORBIDDEN", s!"禁用旧式配置子句 ({key} := …)")
  match kind with
  | .str _ "posConfigItem" | .str _ "negConfigItem" =>
    if stx[1].getId.eraseMacroScopes == `native then
      issues := issues.push (stx, "SHAPE_FORBIDDEN", "禁用配置项 native")
  | .str _ "valConfigItem" =>
    if stx[1].getId.eraseMacroScopes == `native then
      issues := issues.push (stx, "SHAPE_FORBIDDEN", "禁用配置项 native")
  | _ => pure ()
  if kind == ``Parser.Term.attrInstance then
    let name := attributeName stx[1]
    unless attributeNames.contains name do
      issues := issues.push (stx, "SHAPE_ATTRIBUTE", s!"属性不在白名单：{name}")
  if kind == `Lean.Parser.Command.eraseAttr && !attributeNames.contains stx[1].getId.eraseMacroScopes then
    issues := issues.push (stx, "SHAPE_ATTRIBUTE", s!"属性不在白名单：{stx[1].getId}")
  if kind == `Lean.Parser.Command.derivingClass then
    let target := stx[1]
    unless target.isIdent && derivingClasses.contains (stripRoot target.getId.eraseMacroScopes) do
      issues := issues.push (stx, "SHAPE_DERIVING", s!"派生目标类不在白名单：{target}")
  -- 复合命令内仍按命令验白名单，不能用 in、mutual 或 #guard_msgs 藏命令。
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

private partial def collect (p : Syntax → Bool) (stx : Syntax) : Array Syntax :=
  (if p stx then #[stx] else #[]) ++ stx.getArgs.flatMap (collect p)

/-- 旧门 15 源码层的判据（`SourceGates.exposure` 原样）：`@[expose] public section`。 -/
private def exposure (stx : Syntax) : Bool :=
  stx.getKind == `Lean.Parser.Command.section &&
    stx[0][0].getArgs.any (fun a => a.isAtom && a.getAtomVal == "expose") &&
    stx[0][1][0].getAtomVal == "public"

/-- 维持解析状态所需的作用域命令；只有它们交给 Lean 处理。 -/
private def scopeKinds : Array Name :=
  #[`Lean.Parser.Command.namespace, `Lean.Parser.Command.section, `Lean.Parser.Command.end,
    `Lean.Parser.Command.open]

/--
只处理作用域命令。被审命名空间在库环境里不存在，`open` 整条失败时逐个名字重试并忽略失败；其余失败也
忽略（真实构建会报同一处错，由第 6 步判红）。
-/
private def scopeElab (cmd : Syntax) : CommandElabM Unit := do
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

private structure Result where
  commands : Nat := 0
  issues : Array (Nat × String × String) := #[]
  derives : Array (Position × Position) := #[]
  exposes : Bool := false

private def walk (ctx : Parser.InputContext) (mod : Name) : Frontend.FrontendM Result := do
  let mut r : Result := {}
  let line (s : Syntax) (fallback : Syntax) :=
    (ctx.fileMap.toPosition (s.getPos?.getD (fallback.getPos?.getD 0))).line
  repeat
    Frontend.updateCmdPos
    let state ← Frontend.getCommandState
    let ps ← Frontend.getParserState
    let scope := state.scopes.head!
    let (cmd, next, msgs) := Parser.parseCommand ctx
      { env := state.env, options := scope.opts, currNamespace := scope.currNamespace,
        openDecls := scope.openDecls } ps {}
    if msgs.hasErrors then
      let some m := msgs.toList.find? (·.severity == .error) | break
      r := { r with issues := r.issues.push (m.pos.line, "SHAPE_PARSE", s!"解析失败：{← m.data.toString}") }
      break
    if cmd.getKind == ``Parser.Command.eoi then break
    -- 同一处的同一条发现只报一次（`choice` 节点的几个候选会各带一份同样的记号）。
    let found := (inspect mod cmd true false).foldl (init := #[]) fun acc (s, c, d) =>
      if acc.any (fun (s', c', d') => c == c' && d == d' && s.getPos? == s'.getPos?) then acc
      else acc.push (s, c, d)
    let spans := (collect (·.getKind == `Lean.Parser.Command.derivingClass) cmd).filterMap fun c => do
      return (ctx.fileMap.toPosition (← c.getPos?), ctx.fileMap.toPosition (← c.getTailPos?))
    r := { r with commands := r.commands + 1, exposes := r.exposes || exposure cmd,
                  derives := r.derives ++ spans,
                  issues := r.issues ++ found.map fun (s, c, d) => (line s cmd, c, d) }
    Frontend.setParserState next
    -- `#exit` 与文件头之后的 `import` 是终止命令，已经按命令白名单判红；Lean 在这里也停止处理。
    if Parser.isTerminalCommand cmd then break
    if scopeKinds.contains cmd.getKind then
      Frontend.runCommandElabM (scopeElab cmd)
  return r

private def readHeader (path : String) :
    IO (Parser.InputContext × HeaderSyntax × Parser.ModuleParserState × MessageLog) := do
  let ctx := Parser.mkInputContext (← IO.FS.readFile path) path
  let (header, ps, msgs) ← Parser.parseHeader ctx
  if msgs.hasErrors then throw (IO.userError s!"{path}: 文件头解析失败（第 4 步应已判红）")
  return (ctx, header, ps, msgs)

private def pairs : List String → Option (List (String × String))
  | [] => some []
  | mod :: path :: rest => ((mod, path) :: ·) <$> pairs rest
  | [_] => none

/--
一个文件在真实构建里会加载的库模块（不含 `Init`）。真实构建按模块制加载（`Lean.importModulesCore`）：
文件自己的直接导入全部加载；被审模块 `B` 只以「私有」级别被加载，它的导入里只有 `public import` 继续往下传。
-/
private partial def libraries (headers : Std.HashMap Name (Array Import)) (mod : Name) : Array Name := Id.run do
  let mut libs : NameSet := {}
  let mut seen : NameSet := {}
  let mut todo : Array (Name × Bool) := #[(mod, true)]
  while h : todo.size > 0 do
    let (cur, root) := todo.back
    todo := todo.pop
    for imp in headers.getD cur #[] do
      unless root || imp.isExported do continue
      if headers.contains imp.module then
        unless seen.contains imp.module do
          seen := seen.insert imp.module
          todo := todo.push (imp.module, false)
      else libs := libs.insert imp.module
  return libs.toArray.qsort Name.lt

/-- `shape-plan <模块> <路径> ...`：每个文件一行 `["plan", 路径, 模块, [库模块, ...]]`。 -/
public def plan (args : List String) : IO UInt32 := do
  let some files := pairs args | throw (IO.userError "shape-plan 需要成对的模块名与路径")
  let mut headers : Std.HashMap Name (Array Import) := {}
  for (mod, path) in files do
    let (_, header, _, _) ← readHeader path
    headers := headers.insert mod.toName (header.imports false)
  for (mod, path) in files do
    let libs := libraries headers mod.toName
    IO.println <| (Json.arr #[toJson "plan", toJson path, toJson mod,
      toJson (libs.map (·.toString))]).compress
  IO.println <| (Json.arr #[toJson "result", toJson "shape-plan", toJson "green",
    toJson files.length]).compress
  return 0

/--
`shape <库模块>... -- <模块> <路径> ...`：每个文件一行 `["file", 路径, 模块, 命令数]`；每个派生目标类语法节点
一行 `["derive", 路径, 模块, 起行, 起列, 止行, 止列]`；发现一行 `["finding", "shape", 路径, 行号, 红码, 说明]`；
最后 `["result", "shape", 判定, 文件数]`。
-/
public unsafe def shape (args : List String) : IO UInt32 := do
  let (libs, rest) := args.span (· != "--")
  let some files := pairs (rest.drop 1) | throw (IO.userError "shape 需要 <库模块>... -- <模块> <路径> ...")
  if rest.isEmpty then throw (IO.userError "shape 缺少 --")
  -- 与 `HeaderSyntax.imports` 给非 prelude 文件补的隐式导入相同。
  let imports := #[({ module := `Init } : Import), { module := `Init, isMeta := true }] ++
    libs.toArray.map fun l => { module := l.toName }
  -- 库里没有的模块是被审文件写错了导入，判红；其余加载失败归无法判定。
  let missing ← libs.filterM fun l => do
    match ← (findOLean l.toName).toBaseIO with
    | .ok path => return !(← path.pathExists)
    | .error _ => return true
  unless missing.isEmpty do
    for (mod, path) in files do
      IO.println <| (Json.arr #[toJson "file", toJson path, toJson mod, toJson (0 : Nat)]).compress
      emitFinding "shape" path "1" "SHAPE_IMPORT" s!"钉选库里没有这些模块：{missing}"
    IO.println <| (Json.arr #[toJson "result", toJson "shape", toJson "red", toJson files.length]).compress
    return 1
  enableInitializersExecution
  let env ← importModules imports {} (loadExts := true) (level := .exported)
  let mut red := false
  for (mod, path) in files do
    let (ctx, _, ps, _) ← readHeader path
    let opts := Elab.async.set {} false
    let (r, _) ← ((walk ctx mod.toName).run { inputCtx := ctx }).run {
      commandState := Command.mkState (env.setMainModule mod.toName) {} opts, parserState := ps,
      cmdPos := ps.pos }
    let mut issues := r.issues
    if (`Chan.Defs).isPrefixOf mod.toName && !r.exposes then
      issues := issues.push (1, "SHAPE_EXPOSE", "Chan/Defs 下的文件须用 @[expose] public section")
    IO.println <| (Json.arr #[toJson "file", toJson path, toJson mod, toJson r.commands]).compress
    for (a, b) in r.derives do
      IO.println <| (Json.arr #[toJson "derive", toJson path, toJson mod, toJson a.line, toJson a.column,
        toJson b.line, toJson b.column]).compress
    for (line, code, detail) in issues do
      emitFinding "shape" path (toString line) code detail
      red := true
  IO.println <| (Json.arr #[toJson "result", toJson "shape", toJson (if red then "red" else "green"),
    toJson files.length]).compress
  return if red then 1 else 0

end FM.Shape
