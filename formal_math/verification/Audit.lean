module

public import Lean
import all Lean.Util.CollectAxioms
import verification.EnvGates

open Lean

private def allowedAxioms : Array Name :=
  #[`propext, `Classical.choice, `Quot.sound]

private def probeName : Name :=
  (Name.mkSimple "_private" ++ `ChanTest.Probe).num 0 |>.str "gateProofProbe"

-- Lean 为内核已验终止的递归定义另生成编译入口；它不是源码的部分定义。
private def compilerRec (env : Environment) (name : Name) (info : ConstantInfo) : Bool := Id.run do
  let some parent := Lean.Compiler.isUnsafeRecName? name | return false
  let some (.defnInfo base) := env.checked.get.find? parent | return false
  return base.safety == .safe && base.type == info.type &&
    env.getModuleIdxFor? parent == env.getModuleIdxFor? name

private def gate3 (env : Environment) (entries : Array FM.Entry) : IO UInt32 := do
  let names := entries.map fun e => (e.mod, e.name, e.info)
  let mut red := false
  let deps := CollectAxioms.runM env <| names.mapM fun (_, name, _) =>
    CollectAxioms.collectAndGet (fun _ _ => none) name
  for ((mod, name, info), axioms) in names.zip deps do
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
    if info.isPartial && !compilerRec env name info then
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

public def main (args : List String) : IO UInt32 := do
  let gate :: modules := args | return 2
  Lean.initSearchPath (← Lean.findSysroot)
  let mods := modules.toArray.map String.toName
  -- 加载同一轮构建的私有分片，保留私有声明与证明体。
  let env := (← Lean.importModules (mods.map fun m => { module := m }) {}
    (level := .private)).setExporting false
  if ["3", "7b", "8b"].contains gate &&
      !((env.checked.get.find? probeName >>= (·.value? true)).any
        (fun body => !body.getUsedConstants.isEmpty)) then
    IO.eprintln s!"GATE{gate}: 无法读取 {probeName} 的证明体"
    return 2
  let entries : Array FM.Entry := (env.constants.toList.filterMap fun (name, info) => do
    let idx ← env.getModuleIdxFor? name
    let mod ← env.header.moduleNames[idx.toNat]?
    if mods.contains mod then some { mod, name, info } else none).toArray
  if gate == "3" then return ← gate3 env entries
  let config ← (← IO.getStdin).readToEnd
  let .ok (cfg : FM.Config) := Json.parse config >>= fromJson?
    | IO.eprintln "节点台账无法解码"; return 2
  let options := maxRecDepth.set (maxHeartbeats.set {} 6000000) 1024
  let ctx : Core.Context := { fileName := "FM 门禁", fileMap := default, options }
  try
    let (code, _) ← (FM.run gate entries cfg).run'.toIO ctx { env }
    return code
  catch err =>
    IO.eprintln err.toString
    return 2
