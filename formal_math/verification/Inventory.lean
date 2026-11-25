module

public import Lean
import verification.Perimeter

/-!
# 精化器白名单的候选收集（维护工具）

`fm_audit inventory <模块> <路径>` 精化一份**已知合法**的语料文件，不做任何门禁检查，输出：

* 表层与信息树里出现过的语法种类，及各处理表（项、战术、命令、宏、`do` 元素、`grind` 战术、
  归纳精化、`try?`）给这些种类登记的处理器；
* 信息树里实际承担精化的精化器名（`TermInfo`、`TacticInfo`、`CommandInfo` 的 `elaborator`，
  宏即宏声明名）；
* 每个处理器与精化器的所在模块、声明行，以及静态调用闭包里命中的危险常量
  （精化期求值、读写宿主机、未经信息树记录的选项改写入口、白名单外公理）。

这是生成 `elaborators.tsv` 与 `syntax-kinds.tsv` 候选的工具，门禁本身从不调用它。语料由维护者
挑选；它会照常精化语料（与 `lean` 编译该文件无异），所以只用于入库的合法夹具与 `Chan/` 源码。
-/

open Lean Elab Command

namespace FM.Inventory

public section

structure Seen where
  kinds : NameSet := {}
  elaborators : Std.HashSet (String × Name × Name) := {}

private partial def kindsOf (stx : Syntax) : NameSet → NameSet
  | s => match stx with
    | .node _ k args => args.foldl (fun s a => kindsOf a s) (s.insert k)
    | _ => s

private partial def visit (ref : IO.Ref Seen) : InfoTree → IO Unit
  | .context _ t => visit ref t
  | .hole _ => pure ()
  | .node info children => do
    let push (cat : String) (i : ElabInfo) := ref.modify fun s =>
      { s with kinds := kindsOf i.stx s.kinds,
               elaborators := s.elaborators.insert (cat, i.elaborator, i.stx.getKind) }
    match info with
    | .ofTermInfo i => push "term" i.toElabInfo
    | .ofTacticInfo i => push "tactic" i.toElabInfo
    | .ofCommandInfo i => push "command" i.toElabInfo
    | .ofMacroExpansionInfo i => ref.modify fun s =>
        { s with kinds := kindsOf i.output (kindsOf i.stx s.kinds) }
    | _ => pure ()
    for c in children do visit ref c

/-- 精化期求值、宿主机读写、白名单外公理的入口常量。 -/
def dangers : Array Name :=
  #[``Lean.Elab.Term.evalTerm, ``Lean.Meta.evalExpr, ``Lean.Meta.evalExpr', ``Lean.Meta.evalExprCore,
    ``Lean.Environment.evalConst, ``Lean.Environment.evalConstCheck, ``Lean.evalConst,
    ``Lean.evalConstCheck, ``IO.FS.readFile, ``IO.FS.readBinFile, ``IO.FS.writeFile,
    ``IO.FS.Handle.mk, ``IO.Process.spawn, ``IO.Process.output, ``IO.Process.run,
    `Lean.ofReduceBool, `Lean.ofReduceNat, `Lean.trustCompiler, ``unsafeBaseIO, ``unsafeIO]

/--
静态调用闭包：从每个危险常量沿「被引用」反向图走，标出能到达它的定义。只看定义与 opaque
的值（含 `implemented_by` 目标），不看定理证明。动态派发（处理表查找）不在静态图上，因此一个
精化器的闭包只含它自己直接或经辅助函数调用的代码。
-/
def reach (env : Environment) : Std.HashMap Name (Array Name) := Id.run do
  let mut rev : Std.HashMap Name (Array Name) := {}
  for (n, c) in env.constants.toList do
    let mut used := match c with
      | .defnInfo d => d.value.getUsedConstants
      | .opaqueInfo d => d.value.getUsedConstants
      | _ => #[]
    if let some impl := Compiler.getImplementedBy? env n then used := used.push impl
    for u in used do rev := rev.insert u ((rev.getD u #[]).push n)
  let mut out : Std.HashMap Name (Array Name) := {}
  for d in dangers do
    let mut seen : NameSet := {}
    let mut todo := #[d]
    while h : todo.size > 0 do
      let n := todo.back
      todo := todo.pop
      if seen.contains n then continue
      seen := seen.insert n
      out := out.insert n ((out.getD n #[]).push d)
      todo := todo ++ rev.getD n #[]
  return out

/-- 从 `src` 沿值里的常量引用找到 `dst` 的最短调用链（作依据用）。 -/
def pathTo (env : Environment) (src dst : Name) : Array Name := Id.run do
  let used (n : Name) : Array Name :=
    let base := match env.find? n with
      | some (.defnInfo d) => d.value.getUsedConstants
      | some (.opaqueInfo d) => d.value.getUsedConstants
      | _ => #[]
    match Compiler.getImplementedBy? env n with
    | some i => base.push i
    | none => base
  let mut parent : Std.HashMap Name Name := {}
  let mut queue := #[src]
  let mut i := 0
  let mut found := false
  while i < queue.size && i < 200000 && !found do
    let n := queue[i]!
    i := i + 1
    for u in used n do
      if u == src || parent.contains u then continue
      parent := parent.insert u n
      if u == dst then found := true; break
      queue := queue.push u
  if !found then return #[]
  let mut path := #[dst]
  let mut cur := dst
  while cur != src do
    cur := parent.getD cur src
    path := path.push cur
  return path.reverse

private def location (env : Environment) (n : Name) : IO (String × Nat) := do
  let mod := ((env.getModuleIdxFor? n).bind (env.header.moduleNames[·.toNat]?)).getD .anonymous
  let line ← try
      let (r, _) ← (findDeclarationRanges? n : CoreM _).toIO { fileName := "", fileMap := default } { env }
      pure (r.map (·.range.pos.line) |>.getD 0)
    catch _ => pure 0
  return (mod.toString, line)

unsafe def run (mod : Name) (path : String) : IO UInt32 := do
  let ctx := Parser.mkInputContext (← IO.FS.readFile path) path
  let (header, ps, msgs) ← Parser.parseHeader ctx
  let opts := Elab.async.set {} false
  enableInitializersExecution
  let (env, msgs) ← processHeader header opts msgs ctx (mainModule := mod)
  let ref ← IO.mkRef ({} : Seen)
  let loop : Frontend.FrontendM Unit := do
    repeat
      Frontend.updateCmdPos
      let state ← Frontend.getCommandState
      let scope := state.scopes.head!
      let (cmd, next, _) := Parser.parseCommand ctx
        { env := state.env, options := scope.opts, currNamespace := scope.currNamespace,
          openDecls := scope.openDecls } (← Frontend.getParserState) {}
      if cmd.getKind == `Lean.Parser.Command.eoi then break
      ref.modify fun s => { s with kinds := kindsOf cmd s.kinds }
      Frontend.setParserState next
      Frontend.elabCommandAtFrontend cmd
      let st ← Frontend.getCommandState
      let infos := (st.infoState.substituteLazy).get
      for t in infos.trees do visit ref (t.substitute infos.assignment)
  let (_, s) ← (loop.run { inputCtx := ctx }).run {
    commandState := Command.mkState env msgs opts, parserState := ps, cmdPos := ps.pos }
  let env := s.commandState.env
  let seen ← ref.get
  for imp in Elab.HeaderSyntax.imports header false do
    IO.println <| (Json.arr #[toJson "import", toJson imp.module.toString]).compress
  for k in seen.kinds do
    let hs := FM.Perimeter.handlers env k
    IO.println <| (Json.arr #[toJson "kind", toJson k.toString,
      toJson (hs.map fun (t, n) => #[t, n.toString])]).compress
  for (cat, n, k) in seen.elaborators do
    IO.println <| (Json.arr #[toJson "elab", toJson cat, toJson n.toString, toJson k.toString]).compress
  return 0

/-- 读入一个只含导入的文件的环境，对标准输入里的每个名字给出所在模块、声明行与危险常量。 -/
unsafe def scan (path : String) : IO UInt32 := do
  let ctx := Parser.mkInputContext (← IO.FS.readFile path) path
  let (header, _, _) ← Parser.parseHeader ctx
  -- 读私有分片：精化器多为私有或不公开定义体，公开视图里看不到它们的值。
  let env := (← importModules (Elab.HeaderSyntax.imports header) {} (level := .private)).setExporting false
  let hits := reach env
  for line in (← (← IO.getStdin).readToEnd).splitOn "\n" do
    let n := line.trimAscii.copy.toName
    if n.isAnonymous then continue
    let (m, l) ← location env n
    let ds := hits.getD n #[]
    let paths := if ds.isEmpty then #[] else ds.toList.eraseDups.toArray.map fun d => pathTo env n d
    IO.println <| (Json.arr #[toJson n.toString, toJson m, toJson l,
      toJson (ds.map (·.toString)), toJson (env.contains n),
      toJson (paths.map fun p => p.map (·.toString))]).compress
  return 0

end
end FM.Inventory
