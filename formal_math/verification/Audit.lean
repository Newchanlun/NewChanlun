module

public import Lean
import all Lean.Util.CollectAxioms
import Lean.Meta.Constructions.CtorIdx
import verification.EnvGates
import verification.SourceGates

open Lean Meta

private def allowedAxioms : Array Name :=
  #[`propext, `Classical.choice, `Quot.sound]

private def probeName : Name :=
  (Name.mkSimple "_private" ++ `ChanTest.Probe).num 0 |>.str "gateProofProbe"

/-- 派生处理器的类与辅助函数前缀，照录 `Lean.Elab.Deriving` 各处理器调用 `mkContext` 的实参。 -/
private def derivingPrefixes : Array (Name × String) :=
  #[(``Repr, "repr"), (``BEq, "beq"), (``Hashable, "hash"), (``Ord, "ord"),
    (``DecidableEq, "decEq")]

private def sameModule (env : Environment) (a b : Name) : Bool :=
  (env.getModuleIdxFor? a).isSome && env.getModuleIdxFor? a == env.getModuleIdxFor? b

/--
`T.ctorIdx` 的运行期实现：类型与 `T.ctorIdx` 相同，值是逐参数抽象后的
`getObjTagNat _ x`（`Lean.Meta.Constructions.CtorIdx.mkCtorIdxImpl` 的形状）。
-/
private def ctorIdxImpl (env : Environment) (decl impl : Name) : Bool := Id.run do
  let some ind := isCtorIdxCore? env decl | false
  let some (.defnInfo d) := env.find? decl | false
  let some (.defnInfo i) := env.find? impl | false
  if ind.isUnsafe || !sameModule env ind.name decl || !sameModule env decl impl then return false
  if d.safety != .safe || i.safety != .unsafe || i.type != d.type ||
      i.levelParams != d.levelParams then return false
  let mut body := i.value
  let mut arity := 0
  while body.isLambda do
    body := body.bindingBody!
    arity := arity + 1
  return arity == d.type.getForallArity && body.isAppOfArity ``getObjTagNat 2 &&
    body.appArg! == .bvar 0

/--
生成来源判据：常量带 `unsafe`、`partial`、`implemented_by` 时，只有能机械复核为下列三类
Lean 自动生成的辅助项才豁免，返回类别名。
1. 归纳类型的 `ctorIdx` 运行期实现（`isCtorIdxCore?` 认定，且形状与生成器一致）。
2. 结构递归或良基递归定义的编译影子：`Compiler.isUnsafeRecName?` 指向的源定义是同模块、
   内核检查过的安全 `def`，且 `isRecursiveDefinition` 登记为结构／良基递归，类型逐字相同。
3. 派生处理器的辅助函数：源定义是同模块的 `opaque`，其前缀是同模块的实例常量，实例类型为
   `C (T …)`，用 Lean 自己的 `Deriving.mkContext C 前缀 T` 重算得出 `usePartial` 为真，
   辅助函数名与实例名恰与重算结果一致，且实例体引用重算出的辅助函数。
手写 `partial def` 的源定义是 `opaque` 且不满足第 3 类，不豁免。
-/
private def generatedBy (name : Name) (info : ConstantInfo) (implTargets : NameMap Name) :
    MetaM (Option String) := do
  let env ← getEnv
  if let some decl := implTargets.find? name then
    if ctorIdxImpl env decl name then return some "ctorIdx 运行期实现"
  if let some impl := Compiler.getImplementedBy? env name then
    if ctorIdxImpl env name impl then return some "ctorIdx"
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
    if s.isUnsafe || s.type != d.type then return none
    let inst := source.getPrefix
    unless sameModule env inst source do return none
    let some instInfo := env.find? inst | return none
    forallTelescopeReducing instInfo.type fun _ target => do
      let .const cls _ := target.getAppFn | return none
      let some (_, pre) := derivingPrefixes.find? (·.1 == cls) | return none
      let some arg := target.getAppArgs.back? | return none
      let .const ty _ := arg.getAppFn | return none
      unless sameModule env ty source && (← isInductive ty) do return none
      -- 生成器为实例取「当前命名空间里未用的」名字；在空的探针命名空间里重算，
      -- 避开已存在的实例本身。原处若因撞名加过后缀，重算对不上，按不豁免处理。
      let ctx ← withTheReader Core.Context ({ · with currNamespace := `_fm_regen, openDecls := [] })
        (Elab.Deriving.mkContext cls pre ty).run'
      let aux := ctx.auxFunNames.map (inst.getPrefix ++ ·)
      -- 实例体须引用重算出的辅助函数，证明二者出自同一次派生。
      let used := (instInfo.value? (allowOpaque := true)).map (·.getUsedConstants) |>.getD #[]
      if ctx.usePartial && inst == inst.getPrefix ++ ctx.instName && aux.contains source &&
          aux.any used.contains then
        return some "派生处理器辅助函数"
      return none
  | _ => return none

private def gate3 (entries : Array FM.Entry) : MetaM UInt32 := do
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
    let flagged := info.isUnsafe || info.isPartial ||
      (Compiler.getImplementedBy? env name).isSome || isExtern env name
    if flagged && (← generatedBy name info implTargets).isNone then
      if info.isUnsafe then
        issues := issues.push ("ENV_UNSAFE", "声明不受内核安全性保证")
      if info.isPartial then
        let source := (Compiler.isUnsafeRecName? name).getD name
        issues := issues.push ("ENV_PARTIAL", s!"部分定义（源定义 {source} 不是结构／良基递归或白名单派生）")
      if (Compiler.getImplementedBy? env name).isSome then
        issues := issues.push ("ENV_IMPLEMENTED_BY", "声明具有 implemented_by 属性")
      if isExtern env name then
        issues := issues.push ("ENV_EXTERN", "声明具有 extern 属性")
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
      let (code, _) ← (gate3 entries).run'.toIO ctx { env }
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
    let (code, _) ← (FM.run gate entries publicView).run'.toIO ctx { env }
    return code
  catch err =>
    IO.eprintln err.toString
    return 2
