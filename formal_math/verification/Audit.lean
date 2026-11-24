module

public import Lean
import all Lean.Util.CollectAxioms

open Lean

private def allowedAxioms : Array Name :=
  #[`propext, `Classical.choice, `Quot.sound]

private def probeName : Name :=
  (Name.mkSimple "_private" ++ `ChanTest.Probe).num 0 |>.str "gateProofProbe"

public def main (args : List String) : IO UInt32 := do
  Lean.initSearchPath (← Lean.findSysroot)
  let mods := args.toArray.map String.toName
  -- 私有层加载同一轮 Lake 构建的 .olean 分片，保留非公开声明及其证明项。
  let env ← Lean.importModules (mods.map fun m => { module := m }) {}
    (level := .private)
  let env := env.setExporting false
  unless (env.find? probeName >>= (·.value? true)).any (fun body => !body.getUsedConstants.isEmpty) do
    IO.eprintln s!"GATE3: 无法读取 {probeName} 的证明体"
    return 2
  let names := env.constants.toList.filterMap fun (name, info) => do
    let idx ← env.getModuleIdxFor? name
    let mod ← env.header.moduleNames[idx.toNat]?
    if mods.contains mod then some (mod, name, info) else none
  let mut red := false
  let deps := CollectAxioms.runM env <| names.toArray.mapM fun (_, name, _) =>
    CollectAxioms.collectAndGet (fun _ _ => none) name
  for ((mod, name, info), axioms) in names.toArray.zip deps do
    let path := mod.toString.replace "." "/" ++ ".lean"
    -- 闭包遍历读的是内核环境；它必须持有枚举到的定义及证明体。
    if info.hasValue true && ((env.checked.get.find? name >>= (·.value? true)).isNone) then
      IO.eprintln s!"GATE3: 无法读取 {path}:{name} 的值"
      return 2
    let mut issues : Array (String × String) := #[]
    if info matches .axiomInfo _ then
      issues := issues.push ("ENV_AXIOM", "包内声明是公理")
    if info.isUnsafe then
      issues := issues.push ("ENV_UNSAFE", "声明不受内核安全性保证")
    if info.isPartial then
      issues := issues.push ("ENV_PARTIAL", "声明是部分定义")
    if (Lean.Compiler.getImplementedBy? env name).isSome then
      issues := issues.push ("ENV_IMPLEMENTED_BY", "声明具有 implemented_by 属性")
    if Lean.isExtern env name then
      issues := issues.push ("ENV_EXTERN", "声明具有 extern 属性")
    for ax in axioms do
      unless allowedAxioms.contains ax do
        let code := if ax == `sorryAx then "ENV_SORRY" else "ENV_AXIOM_DEP"
        issues := issues.push (code, s!"闭包包含禁用公理 {ax}")
    for (code, detail) in issues do
      IO.println s!"GATE3 RED formal_math/{path}:{name} {code} {detail}"
      red := true
  return if red then 1 else 0
