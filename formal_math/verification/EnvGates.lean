module

public import Lean

open Lean Meta

namespace FM

public section

structure Entry where
  mod : Name
  name : Name
  info : ConstantInfo

def within (mod lane : Name) : Bool := lane.isPrefixOf mod

def locked (entry : Entry) : Bool :=
  [`Chan.Defs, `Chan.Hypotheses, `Chan.Audit.Literal, `ChanChallenge].any (within entry.mod)

private def node (entry : Entry) : Bool :=
  [`Chan.Thm, `Chan.Proofs, `Chan.Exec, `ChanChallenge].any (within entry.mod) &&
    (entry.info matches .thmInfo _)

private def row (tag : String) (items : List Json) : Json :=
  .arr (#[toJson tag] ++ items.toArray)

private def canonicalName : Name → Json
  | .anonymous => .null
  | .str p s => row "str" [canonicalName p, toJson s]
  | .num p n => row "num" [canonicalName p, toJson n]

private def levelCode (params : List Name) : Level → Except String Json
  | .zero => pure (row "zero" [])
  | .succ a => return row "succ" [← levelCode params a]
  | .max a b => return row "max" [← levelCode params a, ← levelCode params b]
  | .imax a b => return row "imax" [← levelCode params a, ← levelCode params b]
  | .param n =>
    if params.contains n then pure (row "param" [toJson (params.idxOf n)])
    else .error s!"未声明的宇宙参数 {n}"
  | .mvar _ => .error "常量含宇宙元变量"

private def binderCode : BinderInfo → Json
  | .default => toJson (0 : Nat)
  | .implicit => toJson (1 : Nat)
  | .strictImplicit => toJson (2 : Nat)
  | .instImplicit => toJson (3 : Nat)

-- 用内核表达式的 de Bruijn 编号，不用 pretty-printer、源位置或绑定名。
private def exprCode (params : List Name) : Expr → Except String Json
  | .bvar i => pure (row "bvar" [toJson i])
  | .fvar _ | .mvar _ => .error "常量不是闭表达式"
  | .sort u => return row "sort" [← levelCode params u]
  | .const n us => return row "const" [canonicalName n, toJson (← us.mapM (levelCode params))]
  | .app f a => return row "app" [← exprCode params f, ← exprCode params a]
  | .lam _ t b i => return row "lam" [binderCode i, ← exprCode params t, ← exprCode params b]
  | .forallE _ t b i => return row "forall" [binderCode i, ← exprCode params t, ← exprCode params b]
  | .letE _ t v b _ => return row "let" [← exprCode params t, ← exprCode params v, ← exprCode params b]
  | .lit (.natVal n) => pure (row "nat" [toJson n])
  | .lit (.strVal s) => pure (row "string" [toJson s])
  | .mdata _ b => exprCode params b
  | .proj n i b => return row "proj" [canonicalName n, toJson i, ← exprCode params b]

def statement (entry : Entry) : Except String Json := do
  let info := entry.info
  let params := info.levelParams
  let value ← match info with
    | .defnInfo d => exprCode params d.value
    | .opaqueInfo d => return row "opaque" [← exprCode params d.value]
    | _ => pure .null
  return row "FM-lock-v1" [canonicalName entry.name, toJson params.length,
    ← exprCode params info.type, value]

structure NodeConfig where
  registration : Bool := false
  about : List String := []
  mode : String := ""
  helpers : List String := []
  declarative_unique : Bool := false
  necessary : List String := []
  needs_necessity : Bool := false
  deriving FromJson

structure Config where
  nodes : List (String × NodeConfig) := []
  refinements : List (String × String) := []
  deriving FromJson

private def finding (gate : String) (e : Entry) (code detail : String) : MetaM Bool := do
  let path := e.mod.toString.replace "." "/"
  IO.println s!"GATE{gate} RED formal_math/{path}.lean:{e.name} {code} {detail}"
  return true

private def resolve (env : Environment) (s : String) : Option ConstantInfo :=
  if let some c := env.find? s.toName then some c
  else env.constants.toList.findSome? fun (n, c) => if n.toString == s then some c else none

private def same (a b : Expr) : MetaM Bool :=
  withoutModifyingState <| withReducible <| isDefEq a b

private def containsFVar (e x : Expr) : Bool :=
  (e.find? (· == x)).isSome

private def params (xs : Array Expr) : MetaM (Array Expr × Array Expr) := do
  let mut data := #[]
  let mut premises := #[]
  for x in xs do
    if ← isProof x then premises := premises.push x
    else data := data.push x
  return (data, premises)

private def projection (struct : Name) (field : Name) (idx : Nat) (t : Expr) : Bool :=
  t.getAppFn.isConstOf (struct ++ field) ||
    (match t.getAppFn with
      | .proj name i _ => name == struct && i == idx
      | _ => false)

private def equations : Nat → Expr → Array (Expr × Expr)
  | 0, _ => #[]
  | k + 1, e =>
    if let some (_, a, b) := e.eq? then #[(a, b)]
    else if e.isAppOfArity `Iff 2 then #[(e.appFn!.appArg!, e.appArg!)]
    else if e.isAppOfArity `And 2 then
      equations k e.appFn!.appArg! ++ equations k e.appArg!
    else #[]

private def refines (struct : Name) (fields bad : Array (Nat × Name)) (type : Expr) :
    MetaM Bool :=
  forallTelescope type fun xs result => do
    if (← params xs).2.size != 0 then return false
    let pairs := equations 256 result
    let clean (r : Expr) :=
      !(r.find? fun t => bad.any fun (i, f) => projection struct f i t).isSome &&
        (r.find? fun t => fields.any fun (i, f) =>
          !bad.contains (i, f) && projection struct f i t).isSome
    return bad.all fun (i, f) => pairs.any fun (a, b) =>
      (projection struct f i a && clean b) || (projection struct f i b && clean a)

private def gate7a (e : Entry) (cfg : Config) : MetaM Bool := do
  let env ← getEnv
  if node e then
    let some n := cfg.nodes.lookup e.name.toString
      | return ← finding "7a" e "NODE_MISSING" "定理未登记"
    if !n.registration then
      return ← finding "7a" e "NODE_MISSING" "定理未登记 about 或 mode"
    if !["对任意实现成立", "依赖具体定义"].contains n.mode ||
        (n.mode == "依赖具体定义" && n.about.isEmpty) then
      return ← finding "7a" e "NODE_MODE" "mode 无效或缺少具体定义"
    if n.about.any (fun s => (resolve env s).isNone) then
      return ← finding "7a" e "ABOUT_UNKNOWN" "about 含环境中不存在的常量"
  if within e.mod `Chan.Defs && (getStructureInfo? env e.name).isSome then
    let structureInfo := getStructureInfo env e.name
    let some (.inductInfo ind) := env.find? e.name | throwError "未读取到结构构造器"
    let [ctor] := ind.ctors | throwError "结构不止一个构造器"
    let allFields := structureInfo.fieldNames.mapIdx (fun i n => (i, n))
    let fields ← forallTelescope (← getConstInfo ctor).type fun xs _ => do
      let mut result := #[]
      for (x, field) in xs[ind.numParams:].toArray.zip allFields do
        if ← forallTelescopeReducing (← inferType x) (whnfType := true) fun _ ty =>
            pure (ty.isConstOf `Bool || ty == mkSort .zero) then
          result := result.push field
      return result
    if !fields.isEmpty then
      if let some name := cfg.refinements.lookup e.name.toString then
        if let some (.thmInfo thm) := resolve env name then
          if ← refines e.name allFields fields thm.type then
            return false
      return ← finding "7a" e "FREE_PREDICATE" s!"自由判据字段 {fields.map Prod.snd} 缺少原始数据到判据的精化定理"
  return false

-- 实例只从定理自己的数据参数选；每一步先核对依赖实例的类型。
private def premiseInstance (data : Array Expr) (conclusion : Expr) : Nat → Expr → MetaM Bool
  | 0, _ => throwError "假设实例化超过递归上限"
  | fuel + 1, ty => do
    if ← same ty conclusion then return true
    let ty ← withReducible <| whnf ty
    if let .forallE _ domain rest _ := ty then
      for d in data do
        if ← same domain (← inferType d) then
          if ← premiseInstance data conclusion fuel (rest.instantiate1 d) then return true
    return false

private def gate8a (e : Entry) (cfg : NodeConfig) : MetaM Bool :=
  forallTelescope e.info.type fun xs result => do
    let (data, premises) ← params xs
    let mut red := false
    for h in premises do
      if ← premiseInstance data result 256 (← inferType h) then
        red ← finding "8a" e "PREMISE_INSTANCE" s!"前提 {← h.fvarId!.getUserName} 的实例即结论"
    if cfg.declarative_unique && result.getAppFn.isConstOf (Name.mkSimple "ExistsUnique") then
      let args := result.getAppArgs
      if args.size == 2 then
        let graph ← withLocalDeclD `y args[0]! fun y => do
          let body ← withReducible <| whnf (mkApp args[1]! y)
          if let some (_, a, b) := body.eq? then
            return (a == y && !containsFVar b y) || (b == y && !containsFVar a y)
          return false
        if graph then red ← finding "8a" e "FUNCTION_GRAPH" "声明式唯一性只复述函数图"
    return red

-- 内核重放接收一个临时环境的返回值；调用方从不安装它。
private def replay (e : Entry) (type value : Expr) : MetaM Bool := do
  let env ← getEnv
  let result := env.addDeclCore 200000 1024 (.thmDecl {
    name := `_fm_gate_kernel_replay
    levelParams := e.info.levelParams
    type, value
  }) none
  match result with
  | .ok _ => return true
  | .error (.declTypeMismatch ..) | .error (.appTypeMismatch ..)
  | .error (.declHasFVars ..) | .error (.typeExpected ..)
  | .error (.letTypeMismatch ..) | .error (.exprTypeMismatch ..)
  | .error (.funExpected ..) | .error (.invalidProj ..) => return false
  | .error err => throwError "内核重放不能判定：{err.toMessageData {}}"

private def bodyOf (e : Entry) : MetaM Expr := do
  let env ← getEnv
  let some body := env.checked.get.find? e.name >>= (·.value? true)
    | throwError "无法读取证明体 {e.name}"
  return body

private def gate8b (e : Entry) (cfg : NodeConfig) : MetaM Bool := do
  if cfg.necessary.isEmpty then return false
  let body ← bodyOf e
  forallTelescope e.info.type fun xs result => do
    let (_, premises) ← params xs
    let mut red := false
    for label in cfg.necessary do
      let some h ← premises.findM? (fun h => return (← h.fvarId!.getUserName).toString == label)
        | throwError "{e.name}: 必要前提 {label} 不在望远镜里"
      let rest := xs.filter (· != h)
      if containsFVar result h || (← rest.anyM fun x => return containsFVar (← inferType x) h) then
        IO.eprintln s!"GATE8b NOTE {e.name}: 后续类型依赖 {label}，无法直接删去"
      else
        let ty ← mkForallFVars rest result
        let proof ← mkLambdaFVars rest (body.beta xs)
        if ← replay e ty proof then
          red ← finding "8b" e "DROPPABLE_PREMISE" s!"删去必要前提 {label} 后原证明仍通过"
    return red

-- 追踪未获准展开的项目常量；若它们仍能访问 D，就没有完成一致替换。
private def hiddenDependency (env : Environment) (targets : List Name) (earliest : Nat) :
    Nat → List Name → NameSet → MetaM Bool
  | 0, _, _ => throwError "抽象依赖闭包超过上限"
  | _, [], _ => pure false
  | fuel + 1, n :: todo, seen => do
    if targets.contains n then return true
    if seen.contains n || (env.getModuleIdxFor? n).any (·.toNat < earliest) then
      return ← hiddenDependency env targets earliest fuel todo seen
    let some c := env.checked.get.find? n | throwError "无法读取依赖 {n}"
    let direct := c.type.getUsedConstants.toList ++
      ((c.value? true).map (·.getUsedConstants.toList)).getD []
    hiddenDependency env targets earliest fuel (direct ++ todo) (seen.insert n)

private def constantApps (e : Expr) : IO (Array Expr) := do
  let found ← IO.mkRef ({} : Std.HashSet Expr)
  e.forEach (m := IO) fun t => do
    if t.isConst then found.modify (·.insert t)
  return (← found.get).toArray

private def expand (env : Environment) (targets helpers : List Name) :
    Nat → Expr → MetaM Expr
  | 0, _ => throwError "辅助接口展开超过上限"
  | fuel + 1, e => do
    let earliest := (targets.filterMap (fun n => (env.getModuleIdxFor? n).map (·.toNat))).min?.getD 0
    let mut replacements : Array (Expr × Expr) := #[]
    for t in ← constantApps e do
      let .const n levels := t | continue
      if targets.contains n then continue
      let owner := env.getModuleIdxFor? n >>= (fun i => env.header.moduleNames[i.toNat]?)
      if helpers.contains n || (owner.any (within · `Chan.Hypotheses)) then
        let some c := env.checked.get.find? n | throwError "无法读取辅助接口 {n}"
        unless c.hasValue true do throwError "不能展开辅助接口 {n}"
        let v ← expand env targets helpers fuel (c.instantiateValueLevelParams! levels true)
        replacements := replacements.push (t, v)
      else if ← hiddenDependency env targets earliest 20000 [n] {} then
        throwError "未获准展开的依赖 {n} 隐藏了具体定义"
    return e.replace fun t => (replacements.find? (fun p => p.1 == t)).map Prod.snd

private def abstractReplay (e : Entry) :
    List Expr → Array (Expr × Expr) → Expr → Expr → MetaM Bool
  | [], pairs, ty, proof => do
    let replace (expr : Expr) :=
      expr.replace fun t => (pairs.find? (fun p => p.1 == t)).map Prod.snd
    let xs := pairs.map Prod.snd
    replay e (← mkForallFVars xs (replace ty)) (← mkLambdaFVars xs (replace proof))
  | t :: ts, pairs, ty, proof => do
    let domain := (← inferType t).replace fun x => (pairs.find? (fun p => p.1 == x)).map Prod.snd
    if ts.any (fun x => (domain.find? (· == x)).isSome) ||
        (domain.find? (· == t)).isSome then
      throwError "抽象对象的类型仍依赖未替换对象；请按依赖顺序登记 about"
    withLocalDeclD `F domain fun f => abstractReplay e ts (pairs.push (t, f)) ty proof

private def gate7b (e : Entry) (cfg : NodeConfig) : MetaM Bool := do
  if cfg.mode != "依赖具体定义" then return false
  let env ← getEnv
  let mut targets := []
  for label in cfg.about do
    let some c := resolve env label | throwError "未找到抽象对象 {label}"
    unless c matches .defnInfo _ | .opaqueInfo _ do throwError "{label} 不是具体定义"
    targets := targets ++ [c.name]
  if targets.isEmpty then throwError "抽象测试缺少 about"
  let helpers ← cfg.helpers.mapM fun label => do
    let some c := resolve env label | throwError "未找到获准抽象的辅助接口 {label}"
    pure c.name
  let ty ← expand env targets helpers 128 e.info.type
  let proof ← expand env targets helpers 128 (← bodyOf e)
  let all := (← constantApps ty) ++ (← constantApps proof)
  let mut ordered := []
  for n in targets do
    let relevant := (all.toList.filter (·.isConstOf n)).eraseDups
    if relevant.isEmpty && (← getConstInfo n).levelParams.isEmpty then
      ordered := ordered ++ [mkConst n]
    else ordered := ordered ++ relevant
  if ← abstractReplay e ordered #[] ty proof then
    finding "7b" e "GENERALIZES" "替换为任意同类型实现后，内核接受原证明"
  else
    IO.eprintln s!"GATE7b NOTE {e.name}: 该证明未推广"
    return false

-- 一条存在链绑定所有数据；依赖前提的参数保留在同一条链上。
private def existsOver (x body : Expr) : MetaM Expr := do
  let pred ← mkLambdaFVars #[x] body
  mkAppM `Exists #[pred]

private def witnessType (premises : Array Expr) (skip : Option Expr) :
    List Expr → Option Expr → MetaM (Option Expr)
  | [], tail => pure tail
  | x :: xs, tail => do
    let body ← witnessType premises skip xs tail
    if skip == some x then return body
    if premises.contains x then
      let ty ← inferType x
      match body with
      | none => return some ty
      | some b =>
        if containsFVar b x then return some (← existsOver x b)
        return some (mkApp2 (mkConst `And) ty b)
    else return some (← existsOver x (body.getD (mkConst `True)))

private def checkWitness (e : Entry) (entries : Array Entry) (suffix code : String)
    (expected : Expr) : MetaM Bool := do
  -- 内核私有名的数字组件在源码里写成带转义的标识符，例如 «0»。
  let base := e.name.components.foldl (fun acc part =>
    match part with
    | .num _ n => acc.str (toString n)
    | _ => acc ++ part) Name.anonymous
  let name := base.str suffix
  if expected.hasFVar then throwError "无法生成闭见证命题 {name}"
  let some w := entries.find? (fun w => within w.mod `ChanTest && w.name == name &&
      (w.info matches .thmInfo _))
    | return ← finding "9" e code s!"ChanTest 缺少见证定理 {name}"
  let params := e.info.levelParams.map Level.param
  if w.info.levelParams.length != params.length ||
      !(← withoutModifyingState <| withTransparency .all <|
        isDefEq (w.info.instantiateTypeLevelParams params) expected) then
    return ← finding "9" e code s!"{name} 的类型与生成的联合命题不定义相等"
  return false

private def gate9 (e : Entry) (cfg : NodeConfig) (entries : Array Entry) : MetaM Bool :=
  forallTelescope e.info.type fun xs result => do
    let (_, premises) ← params xs
    let expected := (← witnessType premises none xs.toList none).getD (mkConst `True)
    let mut red ← checkWitness e entries "witness" "WITNESS" expected
    if cfg.needs_necessity then
      for i in [:premises.size] do
        let h := premises[i]!
        let negated := mkApp (mkConst `Not) result
        let expected := (← witnessType premises (some h) xs.toList (some negated)).getD negated
        red := (← checkWitness e entries s!"without_{i + 1}" "NECESSITY" expected) || red
    return red

private def positive (b : Expr) : MetaM Bool := do
  if let some n ← getNatValue? b then
    if n > 0 then return true
  let goal := mkApp2 (mkConst `Nat.lt) (mkNatLit 0) b
  for d in ← getLCtx do
    if ← withoutModifyingState <| isDefEq d.type goal then return true
  return false

private def operation (e : Expr) : MetaM (Option String) := do
  let .const n _ := e.getAppFn | return none
  let args := e.getAppArgs
  if [`Nat.sub, `Nat.div, `HSub.hSub, `HDiv.hDiv, `Sub.sub, `Div.div].contains n then
    let direct := n == `Nat.sub || n == `Nat.div
    let offset := if direct then 0 else if n == `HSub.hSub || n == `HDiv.hDiv then 4 else 2
    unless direct do
      let arity := offset - 1
      for i in [:arity] do
        let some ty := args[i]? | return none
        unless ← same ty (mkConst `Nat) do return none
    if [`Nat.div, `HDiv.hDiv, `Div.div].contains n then
      if let some b := args[offset + 1]? then
        if ← positive b then return none
      return some "Nat.div"
    return some "Nat.sub"
  if n == `Inhabited.default || n == `Finset.sup || n == `Finset.inf then
    return some n.toString
  let .str _ key := n | return none
  if ["head!", "get!", "getD", "getElem!", "sSup", "sInf"].contains key then
    if ["head!", "get!", "getD", "getElem!"].contains key then
      let returnsOption ← forallTelescopeReducing (← inferType e) (whnfType := true)
        fun _ ty => pure (ty.getAppFn.isConstOf `Option)
      if returnsOption then return none
    return some (if key == "getElem!" then "get!" else key)
  return none

-- 遍历最大应用一次；进入绑定体时保留路径上的局部证据。
private def scan (fuel : Nat) (e : Expr) : MetaM (Array String) := do
  match fuel with
  | 0 => throwError "垃圾值扫描超过表达式深度上限"
  | k + 1 =>
    match e with
    | .lam n t b bi | .forallE n t b bi =>
      let domain ← scan k t
      withLocalDecl n bi t fun x => return domain ++ (← scan k (b.instantiate1 x))
    | .letE n t v b _ =>
      let outside := (← scan k t) ++ (← scan k v)
      withLetDecl n t v fun x => return outside ++ (← scan k (b.instantiate1 x))
    | .mdata _ t | .proj _ _ t => scan k t
    | _ =>
      let mut found := (← operation e).toArray
      if e.isApp then
        unless e.getAppFn.isConst do found := found ++ (← scan k e.getAppFn)
        for a in e.getAppArgs do found := found ++ (← scan k a)
      return found

private def gate10 (e : Entry) : MetaM Unit := do
  unless within e.mod `Chan.Defs || within e.mod `ChanChallenge do return
  let mut ops ← scan 1024 e.info.type
  -- 定理证明项只服务证明；声明期以定理类型和定义体为准。
  unless e.info matches .thmInfo _ do
    if e.info.hasValue true then ops := ops ++ (← scan 1024 (← bodyOf e))
  for op in ops do
    IO.println <| (toJson #[e.mod.toString, e.name.toString, op]).compress

def run (gate : String) (entries : Array Entry) (cfg : Config) : MetaM UInt32 := do
  let mut red := false
  for e in entries do
    let config := (cfg.nodes.lookup e.name.toString).getD {}
    let failed ← match gate with
      | "6a" =>
        if locked e then
          match statement e with
          | .error detail => throwError "{e.name}: {detail}"
          | .ok j => IO.println <| (row e.name.toString [toJson e.mod.toString, j]).compress
        pure false
      | "7a" => gate7a e cfg
      | "7b" => if node e then gate7b e config else pure false
      | "8a" => if node e then gate8a e config else pure false
      | "8b" => if node e then gate8b e config else pure false
      | "9" => if node e then gate9 e config entries else pure false
      | "10" => gate10 e *> pure false
      | _ => throwError "未知环境门禁 {gate}"
    red := red || failed
  return if red then 1 else 0

end
end FM
