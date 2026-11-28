/-
单元自测 U1 的驱动：按私有层级读入 `Forge.lean` 造出的模块，调用 `FM.autoParamCarriers`，
输出 `["carriers", [判为载体的名字…]]` 与 `["present", [模块里全部常量名…]]`。
-/
import Lean
import Auditor.EnvGates
open Lean

def main (args : List String) : IO UInt32 := do
  initSearchPath (← findSysroot)
  let mods := args.toArray.map String.toName
  let env := (← importModules (mods.map fun m => { module := m }) {} (level := .private)).setExporting false
  let entries : Array FM.Entry := (env.constants.toList.filterMap fun (name, info) => do
    let idx ← env.getModuleIdxFor? name
    let mod ← env.header.moduleNames[idx.toNat]?
    if mods.contains mod then some { mod, name, info } else none).toArray
  let ctx : Core.Context := { fileName := "FM 单元自测", fileMap := default }
  let (carriers, _) ← (FM.autoParamCarriers entries).run'.toIO ctx { env }
  let names (xs : List Name) : Json := toJson (xs.map toString |>.toArray.qsort (· < ·))
  IO.println (Json.arr #[toJson "carriers", names carriers.toList]).compress
  IO.println (Json.arr #[toJson "present", names (entries.map (·.name)).toList]).compress
  return 0
