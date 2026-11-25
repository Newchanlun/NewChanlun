module

public import Lean

open Lean Elab

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

private def commandKinds : Array Name :=
  #[`Lean.Parser.Command.moduleDoc, `Lean.Parser.Command.namespace, `Lean.Parser.Command.section,
    `Lean.Parser.Command.end, `Lean.Parser.Command.open, `Lean.Parser.Command.variable,
    `Lean.Parser.Command.universe, `Lean.Parser.Command.include, `Lean.Parser.Command.in,
    `Lean.Parser.Command.declaration, `Lean.Parser.Command.mutual, `Lean.Parser.Command.set_option,
    `Lean.Parser.Command.check]

private def declarations : Array Name :=
  #[`Lean.Parser.Command.definition, `Lean.Parser.Command.theorem, `Lean.Parser.Command.abbrev,
    `Lean.Parser.Command.opaque, `Lean.Parser.Command.example, `Lean.Parser.Command.inductive,
    `Lean.Parser.Command.structure, `Lean.Parser.Command.instance]

private def forbidden : Array Name :=
  #[`Lean.Parser.Term.sorry, `Lean.Parser.Tactic.tacticAdmit, `Lean.Parser.Tactic.tacticSorry,
    `Lean.Parser.Tactic.nativeDecide, `Lean.Parser.Tactic.runTac, `Lean.Parser.Term.runMeta,
    `Lean.Parser.Command.unsafe, `Lean.Parser.Command.partial, `Lean.Parser.Attr.extern]

private partial def placeholder (stx : Syntax) : Option Syntax :=
  if #[`Lean.Parser.Term.sorry, `Lean.Parser.Tactic.tacticAdmit,
       `Lean.Parser.Tactic.tacticSorry].contains stx.getKind ||
    (stx.isIdent && stx.getId == `sorryAx) then some stx
  else stx.getArgs.findSome? placeholder

private def setting (stx : Syntax) : Option Name :=
  if #[`Lean.Parser.Command.set_option, `Lean.Parser.Term.set_option,
       `Lean.Parser.Tactic.set_option].contains stx.getKind then
    some stx[1].getId
  else none

private def allowedCommand (mod : Name) (stx : Syntax) : Bool :=
  commandKinds.contains stx.getKind ||
    (stx.getKind == `Lean.Parser.Command.eval && (`ChanExplore).isPrefixOf mod) ||
    (stx.getKind == `Lean.guardMsgsCmd && (`Chan.Final).isPrefixOf mod)

private partial def inspect (mod : Name) (stx : Syntax) (command : Bool) :
    Array (Syntax × String × String) := Id.run do
  let kind := stx.getKind
  let mut issues := #[]
  if command && !allowedCommand mod stx then
    issues := issues.push (stx, "3", s!"命令不在白名单：{kind}")
  if kind == `Lean.Parser.Command.declaration && !declarations.contains stx[1].getKind then
    issues := issues.push (stx[1], "3", s!"声明不在白名单：{stx[1].getKind}")
  if forbidden.contains kind ||
      stx.isAtom && ["implemented_by", "native_decide", "run_tac", "run_meta"].contains stx.getAtomVal ||
      stx.isIdent && ["implemented_by", "command_elab", "term_elab",
        "tactic", "builtin_command_elab", "builtin_term_elab", "builtin_tactic"].contains stx.getId.toString then
    issues := issues.push (stx, "3", s!"源码含禁用语法：{kind}")
  if let some key := setting stx then
    if key == `autoImplicit || key == `relaxedAutoImplicit || (`linter).isPrefixOf key then
      issues := issues.push (stx, "2", s!"禁止在源码设置 {key}")
      if (`linter).isPrefixOf key then
        issues := issues.push (stx, "3", s!"禁止在源码设置 {key}")
    else if ![`maxRecDepth, `maxHeartbeats].contains key && !(`pp).isPrefixOf key then
      issues := issues.push (stx, "3", s!"选项不在白名单：{key}")
  -- 复合命令内仍按命令验白名单，不能用 in、mutual 或 #guard_msgs 藏命令。
  for i in [:stx.getArgs.size] do
    let child := stx[i]
    if kind == `Lean.Parser.Command.mutual && i == 1 then
      for cmd in child.getArgs do issues := issues ++ inspect mod cmd true
    else
      let nested := (kind == `Lean.Parser.Command.in && (i == 0 || i == 2)) ||
        (kind == `Lean.guardMsgsCmd && i == 3)
      issues := issues ++ inspect mod child nested
  return issues

private def exposure (stx : Syntax) : Bool :=
  stx.getKind == `Lean.Parser.Command.section &&
    stx[0][0].getArgs.any (fun a => a.isAtom && a.getAtomVal == "expose") &&
    stx[0][1][0].getAtomVal == "public"

private def walk (ctx : Parser.InputContext) (mod : Name) (auditTool : Bool) :
    Frontend.FrontendM (Bool × Array (Syntax × String × String)) := do
  let mut issues := #[]
  let mut exposes := false
  repeat
    Frontend.updateCmdPos
    let state ← Frontend.getCommandState
    let ps ← Frontend.getParserState
    let scope := state.scopes.head!
    let (cmd, next, msgs) := Parser.parseCommand ctx
      { env := state.env, options := scope.opts, currNamespace := scope.currNamespace,
        openDecls := scope.openDecls } ps {}
    if msgs.hasErrors then
      for m in msgs.toList do IO.eprintln (← m.toString)
      throw (IO.userError s!"{ctx.fileName}: 命令解析失败")
    if cmd.getKind == `Lean.Parser.Command.eoi then break
    exposes := exposes || exposure cmd
    let found := if auditTool then
        ((placeholder cmd).map fun s => (s, "3", "审计工具不能使用占位证明")).toArray
      else inspect mod cmd true
    issues := issues ++ found
    -- 不执行已经被拒绝的命令或项。已拒绝的文件不会进入构建或环境门。
    if found.any (fun (_, gate, _) => gate == "3") then break
    if Parser.isTerminalCommand cmd then
      throw (IO.userError s!"{ctx.fileName}: 文件头之后的终止命令")
    Frontend.setParserState next
    Frontend.elabCommandAtFrontend cmd
    let state ← Frontend.getCommandState
    if state.messages.hasErrors then
      for m in state.messages.toList do
        if m.severity == .error then IO.eprintln (← m.toString)
      issues := issues.push (cmd, "build", "语法已解析，Lean 拒绝精化该命令")
      break
  return (exposes, issues)

unsafe def source (mod : Name) (path : String) : IO UInt32 := do
  let (ctx, header, ps, msgs) ← readHeader path
  let opts := (Elab.async.set {} false).setBool `linter.unusedVariables true
    |>.setBool `autoImplicit false |>.setBool `relaxedAutoImplicit false
  enableInitializersExecution
  let (env, msgs) ← processHeader header opts msgs ctx (mainModule := mod)
  if msgs.hasErrors then
    for m in msgs.toList do IO.eprintln (← m.toString)
    throw (IO.userError s!"{path}: 导入加载失败")
  let auditTool := [`verification.Audit, `verification.EnvGates, `verification.SourceGates].contains mod
  let ((exposes, issues), _) ← ((walk ctx mod auditTool).run { inputCtx := ctx }).run {
    commandState := Command.mkState env msgs opts, parserState := ps, cmdPos := ps.pos }
  let lines := issues.map fun (stx, gate, detail) =>
    Json.arr #[toJson gate, toJson (ctx.fileMap.toPosition (stx.getPos?.getD 0)).line, toJson detail]
  IO.println <| (toJson (exposes, lines)).compress
  return 0

end
end FM

