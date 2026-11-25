import Lean
import Lean.Replay
open Lean

/-- 环境层公理闭包：只读常量图，不调内核。 -/
partial def axiomsOf (env : Environment) (root : Name) : IO (Array Name) := do
  let mut seen : NameSet := {}
  let mut axs : Array Name := #[]
  let mut todo := #[root]
  repeat
    if todo.isEmpty then break
    let n := todo.back!
    todo := todo.pop
    if seen.contains n then continue
    seen := seen.insert n
    let some ci := env.find? n | continue
    if ci matches .axiomInfo _ then axs := axs.push n
    todo := todo ++ ci.type.getUsedConstants
    if let some v := ci.value? (allowOpaque := true) then todo := todo ++ v.getUsedConstants
  return axs

unsafe def main (args : List String) : IO UInt32 := do
  let libDir :: mode :: mods := args | return 2
  initSearchPath (← findSysroot) [libDir]
  let mods := mods.toArray.map String.toName
  let ext := mode == "ext"
  if ext then enableInitializersExecution
  let env ← importModules (mods.map ({module := ·})) {} (loadExts := ext) (level := .private)
  IO.println s!"mode={mode} modules={env.header.moduleNames.size}"
  -- 被审常量：归属模块在参数里的那些
  let mut audited : Std.HashMap Name ConstantInfo := {}
  for (n, ci) in env.constants.toList do
    let some idx := env.getModuleIdxFor? n | continue
    if mods.contains env.header.moduleNames[idx.toNat]! then audited := audited.insert n ci
  IO.println s!"audited constants={audited.size}"
  for (n, ci) in audited.toList do
    if ci matches .thmInfo _ then
      IO.println s!"AXIOMS {n} : {← axiomsOf env n}"
  if mode == "replay" then
    -- 基底环境：被审模块的导入里不属于被审集合的那些
    let mut deps : Array Import := #[]
    for m in mods do
      let some idx := env.getModuleIdx? m | continue
      for imp in env.header.moduleData[idx.toNat]!.imports do
        unless mods.contains imp.module do deps := deps.push { module := imp.module }
    let base ← importModules deps {} (level := .private)
    try
      discard <| base.replay audited
      IO.println "REPLAY accepted"
    catch e =>
      IO.println s!"REPLAY rejected: {e}"
      return 1
  return 0
