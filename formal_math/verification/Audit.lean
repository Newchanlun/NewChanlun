module

public import Lean
import all Lean.Util.CollectAxioms
import Lean.Meta.Constructions.CtorIdx
import verification.EnvGates
import verification.SourceGates
import verification.Inventory

open Lean Meta

private def allowedAxioms : Array Name :=
  #[`propext, `Classical.choice, `Quot.sound]

private def probeName : Name :=
  (Name.mkSimple "_private" ++ `ChanTest.Probe).num 0 |>.str "gateProofProbe"

private def sameModule (env : Environment) (a b : Name) : Bool :=
  (env.getModuleIdxFor? a).isSome && env.getModuleIdxFor? a == env.getModuleIdxFor? b

/--
照 Lean 4.36.0 `Lean.Meta.Constructions.CtorIdx.mkCtorIdx` 与 `mkCtorIdxImpl` 重算归纳类型 `ind`
本应生成的 `ctorIdx` 类型、定义体与运行期实现体。生成器不为命题族、单构造子或运行期内建类型
生成运行期实现，这些情形返回 `none`。
-/
private def expectedCtorIdx (ind : InductiveVal) : MetaM (Option (Expr × Expr × Expr)) := do
  if (← isPropFormerType ind.type) || ind.numCtors == 1 ||
      Compiler.LCNF.isRuntimeBuiltinType ind.name then return none
  let casesOnInfo ← getConstInfo (mkCasesOnName ind.name)
  unless casesOnInfo.levelParams.length > ind.levelParams.length do return none
  let us := ind.levelParams.map mkLevelParam
  forallBoundedTelescope ind.type (ind.numParams + ind.numIndices) fun xs _ => do
  withImplicitBinderInfos xs do
    let params : Array Expr := xs[:ind.numParams]
    let indices : Array Expr := xs[ind.numParams:]
    let indType := mkAppN (mkConst ind.name us) xs
    let declType ← mkForallFVars xs (← mkArrow indType (mkConst ``Nat))
    let declValue ← withLocalDeclD `x indType fun x => do
      let motive ← mkLambdaFVars (indices.push x) (mkConst ``Nat)
      let mut value := mkAppN (mkConst (mkCasesOnName ind.name) (Level.one :: us)) params
      value := mkAppN (mkApp value motive) indices
      value := mkApp value x
      for c in ind.ctors do
        let cInfo ← getConstInfoCtor c
        let cType ← instantiateForall cInfo.type params
        value := mkApp value (← forallBoundedTelescope cType cInfo.numFields fun ys _ =>
          mkLambdaFVars ys (mkRawNatLit cInfo.cidx))
      mkLambdaFVars (xs.push x) value
    let implValue ← forallTelescope declType fun args _ => do
      let discr := args[args.size - 1]!
      let ty ← inferType discr
      mkLambdaFVars args (mkApp2 (mkConst ``getObjTagNat [← getLevel ty]) ty discr)
    return some (declType, declValue, implValue)

/--
豁免 1：`decl` 是归纳类型 `T` 的 `T.ctorIdx`，`impl` 是 `T.ctorIdx._impl`；两者的类型与定义体
与上面重算的结果逐字相同（`==`），安全性、宇宙参数与 `implemented_by` 指向也一致。
手写声明若要命中，必须与 Lean 生成的那一份逐字相同。
-/
private def ctorIdxImpl (decl impl : Name) : MetaM Bool := do
  let env ← getEnv
  let some ind := isCtorIdxCore? env decl | return false
  unless decl == mkCtorIdxName ind.name && impl == Name.mkStr decl "_impl" do return false
  unless !ind.isUnsafe && sameModule env ind.name decl && sameModule env decl impl do return false
  unless Compiler.getImplementedBy? env decl == some impl do return false
  let some (.defnInfo d) := env.find? decl | return false
  let some (.defnInfo i) := env.find? impl | return false
  unless d.safety == .safe && i.safety == .unsafe && d.levelParams == ind.levelParams &&
      i.levelParams == ind.levelParams do return false
  let some (ty, value, implValue) ← expectedCtorIdx ind | return false
  return d.type == ty && i.type == ty && d.value == value && i.value == implValue

/--
生成来源判据：常量带 `unsafe`、`partial`、`implemented_by` 时，只有能机械复核为下列三类
Lean 自动生成的辅助项才豁免（`extern`、`meta` 不在任何豁免之内）：
1. 归纳类型的 `ctorIdx` 与其运行期实现：按生成器重算后逐字相同（见 `ctorIdxImpl`）。
2. 结构递归或良基递归定义的编译影子：`Compiler.isUnsafeRecName?` 指向的源定义是同模块、
   内核检查过的安全 `def`，且 `isRecursiveDefinition` 登记为结构／良基递归，类型逐字相同。
3. 派生处理器的辅助函数：源定义是同模块的 `opaque`，且**在本轮源码层审计的派生证书里**——
   源码层逐命令观察到它由行内 `deriving` 或 `deriving instance` 生成（声明范围落在派生目标类的
   语法节点内）。环境层单独运行时没有证书，第 3 类不豁免。
-/
private def generatedBy (name : Name) (info : ConstantInfo) (implTargets : NameMap Name)
    (derived : NameSet) : MetaM (Option String) := do
  let env ← getEnv
  if let some decl := implTargets.find? name then
    if ← ctorIdxImpl decl name then return some "ctorIdx 运行期实现"
  if let some impl := Compiler.getImplementedBy? env name then
    if ← ctorIdxImpl name impl then return some "ctorIdx"
  let .defnInfo d := info | return none
  let some source := Compiler.isUnsafeRecName? name | return none
  unless d.safety == .partial && sameModule env name source do return none
  match env.find? source with
  | some (.defnInfo s) =>
    if s.safety == .safe && s.type == d.type && s.levelParams == d.levelParams &&
        (← isRecursiveDefinition source) then
      return some "递归定义的编译影子"
    return none
  | some (.opaqueInfo s) =>
    if !s.isUnsafe && s.type == d.type && derived.contains source then
      return some "派生处理器辅助函数（源码层派生证书）"
    return none
  | _ => return none

private def gate3 (entries : Array FM.Entry) (derived : NameSet) : MetaM UInt32 := do
  let env ← getEnv
  let names := entries.map fun e => (e.mod, e.name, e.info)
  let implTargets := entries.foldl (init := {}) fun m e =>
    match Compiler.getImplementedBy? env e.name with
    | some impl => m.insert impl e.name
    | none => m
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
    if isMarkedMeta env name then
      issues := issues.push ("ENV_META", "声明是 meta 元程序")
    -- 全部常量都查；只有能复核生成来源的辅助项豁免，不看有无声明范围、不按名字后缀匹配。
    if isExtern env name then
      issues := issues.push ("ENV_EXTERN", "声明具有 extern 属性")
    let flagged := info.isUnsafe || info.isPartial || (Compiler.getImplementedBy? env name).isSome
    if flagged && (← generatedBy name info implTargets derived).isNone then
      if info.isUnsafe then
        issues := issues.push ("ENV_UNSAFE", "声明不受内核安全性保证")
      if info.isPartial then
        let source := (Compiler.isUnsafeRecName? name).getD name
        issues := issues.push ("ENV_PARTIAL", s!"部分定义（源定义 {source} 不是结构／良基递归，也不在派生证书里）")
      if (Compiler.getImplementedBy? env name).isSome then
        issues := issues.push ("ENV_IMPLEMENTED_BY", "声明具有 implemented_by 属性")
    for ax in axioms do
      unless allowedAxioms.contains ax do
        let code := if ax == `sorryAx then "ENV_SORRY" else "ENV_AXIOM_DEP"
        issues := issues.push (code, s!"闭包包含禁用公理 {ax}")
    for (code, detail) in issues do
      IO.println s!"GATE3 RED formal_math/{path}:{name} {code} {detail}"
      red := true
  return if red then 1 else 0

public unsafe def main (args : List String) : IO UInt32 := do
  let gate :: modules := args | return 2
  Lean.initSearchPath (← Lean.findSysroot)
  if gate == "inventory" then
    let [mod, path] := modules | return 2
    return ← FM.Inventory.run mod.toName path
  if gate == "inventory-scan" then
    let [path] := modules | return 2
    return ← FM.Inventory.scan path
  if gate == "selfcheck" then
    try return ← FM.selfcheck
    catch err =>
      IO.eprintln err.toString
      return 2
  if gate == "headers" || gate == "source" then
    try
      if gate == "headers" then return ← FM.headers modules
      let mod :: path :: tail := modules | return 2
      let selected ← match tail with
        | [] => pure "all"
        | [g] => if ["2", "3", "15"].contains g then pure g
                 else throw (IO.userError s!"未知源码门 {g}")
        | _ => throw (IO.userError "source 需要模块名、路径和可选门编号")
      return ← FM.source mod.toName path selected
    catch err =>
      IO.eprintln err.toString
      return 2
  -- run_gates 把本轮源码层审计观察到的派生产物写成证书交给门 3、15；单独调用时没有证书。
  let (derived, modules) ← match modules with
    | "--derived" :: file :: rest => do
      let .ok (names : Array String) := Json.parse (← IO.FS.readFile file) >>= fromJson?
        | throw (IO.userError "派生证书无法解码")
      pure (names.foldl (fun s n => s.insert n.toName) ({} : NameSet), rest)
    | _ => pure ({}, modules)
  let mods := modules.toArray.map String.toName
  -- 加载同一轮构建的私有分片，保留私有声明与证明体。
  let env := (← Lean.importModules (mods.map fun m => { module := m }) {}
    (level := .private)).setExporting false
  if ["3", "report"].contains gate &&
      !((env.checked.get.find? probeName >>= (·.value? true)).any
        (fun body => !body.getUsedConstants.isEmpty)) then
    IO.eprintln s!"GATE{gate}: 无法读取 {probeName} 的证明体"
    return 2
  let entries : Array FM.Entry := (env.constants.toList.filterMap fun (name, info) => do
    let idx ← env.getModuleIdxFor? name
    let mod ← env.header.moduleNames[idx.toNat]?
    if mods.contains mod then some { mod, name, info } else none).toArray
  let options := maxRecDepth.set (maxHeartbeats.set {} 6000000) 1024
  let ctx : Core.Context := { fileName := "FM 门禁", fileMap := default, options }
  if gate == "3" then
    try
      let (code, _) ← (gate3 entries derived).run'.toIO ctx { env }
      return code
    catch err =>
      IO.eprintln err.toString
      return 2
  try
    if gate == "report" then
      let config ← (← IO.getStdin).readToEnd
      let .ok cfg := Json.parse config >>= fromJson?
        | throw (IO.userError "节点台账无法解码")
      let (code, _) ← (FM.report entries cfg).run'.toIO ctx { env }
      return code
    let publicView ← if gate == "15" then
      some <$> Lean.importModules (mods.map fun m => { module := m }) {} (level := .exported)
      else pure none
    let (code, _) ← (FM.run gate entries publicView derived).run'.toIO ctx { env }
    return code
  catch err =>
    IO.eprintln err.toString
    return 2
