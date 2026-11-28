module

public import Lean
public import Auditor.EnvGates

open Lean Elab

namespace FM

public section

-- 只信 Lean 解析的头部；不把隐式 Init 导入当成源码中的边。解析时不加载任何导入。
private def readHeader (path : String) :
    IO (Option (Parser.InputContext × HeaderSyntax)) := do
  let ctx := Parser.mkInputContext (← IO.FS.readFile path) path
  let (header, _, msgs) ← Parser.parseHeader ctx
  if msgs.hasErrors then
    for m in msgs.toList do IO.eprintln (← m.toString)
    return none
  return some (ctx, header)

/-- 包内可信目录。`ChanExplore` 按同一白名单审，另外只多放行 `#eval`。 -/
private def trustedRoots : Array Name := #[`Chan, `ChanChallenge, `ChanDyn, `ChanTest]

/-- 可信目录允许导入的外部库根。 -/
private def libraryRoots : Array Name := #[`Init, `Std, `Mathlib, `Batteries]

/-- 钉选在 lake-manifest 里但可信目录不许导入的外部库根。导入它们只加载库代码，红后仍继续精化。 -/
private def pinnedRoots : Array Name :=
  #[`Lean, `Lake, `Qq, `Aesop, `Plausible, `ProofWidgets, `LeanSearchClient, `ImportGraph, `Cli]

/-- 头部白名单。第二个返回值为真时不得继续加载导入或精化。 -/
private def headerIssues (mod : Name) (header : HeaderSyntax) :
    Array (Syntax × String × String) × Bool := Id.run do
  let mut issues := #[]
  let mut fatal := false
  if !header.isModule then
    return (#[(header.raw, "MODULE_FIRST", "源码第一条命令必须是 module")], true)
  if !header.raw[1].isNone then
    return (#[(header.raw, "PRELUDE", "禁止 prelude")], true)
  let explore := (`ChanExplore).isPrefixOf mod
  for imp in header.imports false, i in [:header.raw[2].getNumArgs] do
    let ref := header.raw[2][i]
    let root := imp.module.getRoot
    if imp.isMeta || imp.importAll then
      issues := issues.push (ref, if imp.importAll then "IMPORT_ALL" else "META_IMPORT",
        s!"禁止 meta import 或 import all：{imp.module}")
      fatal := true
    else if trustedRoots.contains root || libraryRoots.contains root ||
        (explore && root == `ChanExplore) then
      pure ()
    else if pinnedRoots.contains root then
      issues := issues.push (ref, "IMPORT_PINNED", s!"可信目录不得导入 {imp.module}")
    else
      issues := issues.push (ref, "IMPORT_SOURCE", s!"导入来源不在白名单：{imp.module}")
      fatal := true
  return (issues, fatal)

private def pairs : List String → Option (List (String × String))
  | [] => some []
  | mod :: path :: rest => ((mod, path) :: ·) <$> pairs rest
  | [_] => none

/--
`headers <模块> <路径> ...`：逐个解析文件头，不加载导入、不精化。每个文件一行
`["header", 路径, 模块, isModule, [[导入, 行, importAll, isMeta], ...]]`；头部白名单的发现一行
`["finding", "headers", 路径, 行号, 红码, 说明]`；最后一行 `["result", "headers", 判定, 文件数]`。
-/
def headers (args : List String) : IO UInt32 := do
  let some files := pairs args | throw (IO.userError "headers 需要成对的模块名与路径")
  let mut red := false
  for (mod, path) in files do
    let some (ctx, header) ← readHeader path
      | emitFinding "headers" path "1" "HEADER_PARSE" "文件头解析失败"
        red := true
        continue
    let imports := header.imports false
    let rows := imports.mapIdx fun i imp =>
      let pos := (header.raw[2][i]!).getPos?.getD 0
      Json.arr #[toJson imp.module.toString, toJson (ctx.fileMap.toPosition pos).line,
        toJson imp.importAll, toJson imp.isMeta]
    IO.println <| (Json.arr #[toJson "header", toJson path, toJson mod, toJson header.isModule,
      toJson rows]).compress
    for (ref, code, detail) in (headerIssues mod.toName header).1 do
      let line := (ctx.fileMap.toPosition (ref.getPos?.getD 0)).line
      emitFinding "headers" path (toString line) code detail
      red := true
  IO.println <| (Json.arr #[toJson "result", toJson "headers", toJson (if red then "red" else "green"),
    toJson files.length]).compress
  return if red then 1 else 0

end
end FM
