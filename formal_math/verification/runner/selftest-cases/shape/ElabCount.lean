import Lean
/-!
自测专用（不进审计程序）：用真实前端精化被审文件，数顶层命令数，供「只解析与真实精化命令数一致」比对。
用法：`lean --run ElabCount.lean <模块> <路径>`（自测每个进程只给一个文件），搜索路径须含钉选库与本次构建的被审产物。
每个文件一行 `["elab", 路径, 命令数, 有无错误]`。
-/
open Lean Elab

unsafe def main (args : List String) : IO UInt32 := do
  enableInitializersExecution
  initSearchPath (← findSysroot)
  let mut rest := args
  while h : rest.length ≥ 2 do
    let mod := rest[0]
    let path := rest[1]
    rest := rest.drop 2
    let ctx := Parser.mkInputContext (← IO.FS.readFile path) path
    let (header, ps, msgs) ← Parser.parseHeader ctx
    let (env, msgs) ← processHeader header {} msgs ctx (mainModule := mod.toName)
    let s ← IO.processCommands ctx ps (Command.mkState env msgs {})
    let cmds := s.commands.filter (!·.isOfKind ``Parser.Command.eoi)
    IO.println <| (Json.arr #[toJson "elab", toJson path, toJson cmds.size,
      toJson s.commandState.messages.hasErrors]).compress
  return 0
