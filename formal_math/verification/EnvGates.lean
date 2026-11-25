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

private def projectModule (mod : Name) : Bool :=
  [`Chan, `ChanChallenge, `ChanDyn, `ChanTest, `ChanExplore].any (within mod)

private def owner (env : Environment) (name : Name) : Option Name := do
  let idx ← env.getModuleIdxFor? name
  env.header.moduleNames[idx.toNat]?

private def node (entry : Entry) : MetaM Bool := do
  unless [`Chan.Thm, `Chan.Proofs, `Chan.Exec, `ChanChallenge].any (within entry.mod) do
    return false
  unless entry.info matches .thmInfo _ | .defnInfo _ | .opaqueInfo _ do return false
  let env ← getEnv
  if (env.getProjectionStructureName? entry.name).isSome then return false
  -- 报告按源码声明逐条列读数。门 3 封住了本地元编程，无声明范围的常量只能是 Lean 生成的辅助项
  -- （方程引理、_proof_i、match 辅助等），不当节点；阻断门不依赖这一条。
  if (← findDeclarationRangesCore? entry.name).isNone then return false
  isProp entry.info.type

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

def statement (env : Environment) (entry : Entry) : Except String Json := do
  let info := entry.info
  let params := info.levelParams
  let value ← (do
    match info with
    | .defnInfo d =>
      let hint := match d.hints with
        | .opaque => "opaque"
        | .abbrev => "abbrev"
        | .regular .. => "regular"
      let safety := if info.isUnsafe then "unsafe" else if info.isPartial then "partial" else "safe"
      let reducibility := match getReducibilityStatusCore env entry.name with
        | .reducible => "reducible"
        | .semireducible => "semireducible"
        | .implicitReducible => "implicitReducible"
        | .instanceReducible => "instanceReducible"
        | .irreducible => "irreducible"
      return row "definition" [toJson hint, toJson safety, toJson reducibility, ← exprCode params d.value]
    | .opaqueInfo d => return row "opaque" [toJson d.isUnsafe, ← exprCode params d.value]
    | .thmInfo _ => pure (row "theorem" [])
    | .axiomInfo d => pure (row "axiom" [toJson d.isUnsafe])
    | .inductInfo d => pure (row "inductive" [toJson d.numParams, toJson d.numIndices,
        toJson (d.ctors.map canonicalName), toJson (d.all.map canonicalName)])
    | .ctorInfo d => pure (row "constructor" [canonicalName d.induct, toJson d.cidx,
        toJson d.numParams, toJson d.numFields])
    | .recInfo _ => pure (row "recursor" [])
    | .quotInfo _ => pure (row "quotient" []))
  return row "FM-lock-v2" [canonicalName entry.name, toJson params.length,
    ← exprCode params info.type, value]

structure NodeConfig where
  registration : Bool := false
  about : List String := []
  mode : String := ""
  helpers : List String := []
  declarative_unique : Bool := false
  main_theorem : Bool := false
  necessary : List Nat := []
  convenience : List (Nat × String) := []
  doc_only : List (Nat × String) := []
  needs_necessity : Bool := false
  deriving FromJson

structure Config where
  nodes : List (String × NodeConfig) := []
  refinements : List (String × String) := []
  deriving FromJson

private def finding (gate : String) (e : Entry) (code detail : String) : MetaM Bool := do
  if gate == "15" then
    let path := e.mod.toString.replace "." "/"
    IO.println s!"GATE{gate} RED formal_math/{path}.lean:{e.name} {code} {detail}"
  else
    let evidence := if ["GENERALIZES", "DROPPABLE_PREMISE"].contains code then
      "certified" else "hint"
    IO.println <| (toJson #[e.mod.toString, e.name.toString, gate, "finding",
      evidence, code, detail]).compress
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

private def projection (struct : Name) (nparams : Nat) (field : Name) (idx : Nat)
    (x t : Expr) (whole := false) : Bool :=
  let args := t.getAppArgs
  if t.getAppFn.isConstOf (struct ++ field) then
    (args[nparams]? == some x) && (!whole || args.size == nparams + 1)
  else match t.getAppFn with
    | .proj name i base => name == struct && i == idx && base == x && (!whole || args.isEmpty)
    | _ => false

private def equations : Nat → Expr → Array (Expr × Expr)
  | 0, _ => #[]
  | k + 1, e =>
    if let some (_, a, b) := e.eq? then #[(a, b)]
    else if e.isAppOfArity `Iff 2 then #[(e.appFn!.appArg!, e.appArg!)]
    else if e.isAppOfArity `And 2 then
      equations k e.appFn!.appArg! ++ equations k e.appArg!
    else #[]

private def refines (struct : Name) (nparams : Nat) (fields bad : Array (Nat × Name)) (type : Expr) :
    MetaM Bool :=
  forallTelescope type fun xs result => do
    if xs.size != nparams + 1 then return false
    let x := xs[nparams]!
    let ty ← inferType x
    if !ty.isAppOfArity struct nparams || ty.getAppArgs != xs.extract 0 nparams then return false
    -- 逐个按结构类型的参数域对账，不限制显隐或实例绑定。
    let .const _ levels := ty.getAppFn | return false
    let mut structTy := (← getConstInfo struct).instantiateTypeLevelParams levels
    for p in xs.extract 0 nparams do
      let .forallE _ expected rest _ ← whnf structTy | return false
      unless ← withoutModifyingState <| withTransparency .default <|
          isDefEq (← inferType p) expected do return false
      structTy := rest.instantiate1 p
    let pairs := equations 256 result
    let raw (t : Expr) := fields.any fun (i, f) =>
      !bad.contains (i, f) && projection struct nparams f i x t true
    let clean (r : Expr) :=
      (r.find? raw).isSome &&
        !(containsFVar (r.replace fun t => if raw t then some (mkNatLit 0) else none) x)
    let criterion (i : Nat) (f : Name) (t : Expr) :=
      projection struct nparams f i x t true ||
        -- Bool 作命题时，Lean 的标准强制转换是「整个字段 = true」。
        ((t.eq?).any fun (ty, a, b) =>
          ty.isConstOf `Bool && b.isConstOf `Bool.true &&
            projection struct nparams f i x a true)
    return bad.all fun (i, f) => pairs.any fun (a, b) =>
      (criterion i f a && clean b) || (criterion i f b && clean a)

private def resident (name : Name) (nparams : Nat) (entries : Array Entry) : MetaM Bool :=
  entries.anyM fun w => do
    unless within w.mod `ChanTest do
      return false
    -- 见证可直接给出结构项，或内核已验的 Nonempty 实例。
    let ty ← withTransparency .reducible <| whnf w.info.type
    let ty := if ty.isAppOfArity `Nonempty 1 then ty.appArg! else ty
    return ty.isAppOfArity name nparams && w.info.levelParams.isEmpty && w.info.hasValue true

private def gate7a (e : Entry) (cfg : Config) (entries : Array Entry) : MetaM Bool := do
  let env ← getEnv
  if ← node e then
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
    let (fields, hasProp) ← forallTelescope (← getConstInfo ctor).type fun xs _ => do
      let mut result := #[]
      let mut hasProp := false
      for (x, field) in xs[ind.numParams:].toArray.zip allFields do
        let fieldTy ← inferType x
        let proofField ← isProp fieldTy
        let (isBool, isPredicate) ← forallTelescopeReducing fieldTy (whnfType := true) fun _ ty =>
          pure (ty.isConstOf `Bool, ty == mkSort .zero)
        hasProp := hasProp || proofField || isPredicate
        if isBool || isPredicate then result := result.push field
      return (result, hasProp)
    let mut red := false
    if hasProp && !(← resident e.name ind.numParams entries) then
      red ← finding "7a" e "RESIDENCE" "ChanTest 缺少具体参数下的闭项居留见证"
    if !fields.isEmpty then
      if let some name := cfg.refinements.lookup e.name.toString then
        if let some (.thmInfo thm) := resolve env name then
          if ← refines e.name ind.numParams allFields fields thm.type then
            return red
      return ← finding "7a" e "FREE_PREDICATE" s!"自由判据字段 {fields.map Prod.snd} 缺少原始数据到判据的精化定理"
    return red
  return false

-- 只展开本包命题别名和可约的计算包装，保留库连接词的逻辑边界。
private def statementHead : Nat → Expr → MetaM Expr
  | 0, _ => throwError "命题别名展开超过上限"
  | k + 1, e => do
    let e ← whnfCore e
    let .const n us := e.getAppFn | return e
    if n == `Not || n == `Exists || n == `And || n == `Iff || n == `Eq ||
        n == Name.mkSimple "ExistsUnique" then return e
    let env ← getEnv
    if (owner env n).any projectModule then
      if let some c@(.defnInfo _) := env.find? n then
        return ← statementHead k ((c.instantiateValueLevelParams! us).beta e.getAppArgs)
    let reduced ← withReducible <| whnf e
    if reduced == e then return e
    statementHead k reduced

private def unfoldStatement (e : Expr) (fuel : Nat := 128) : MetaM Expr := do
  let e := e.consumeMData
  let .const n us := e.getAppFn | return e
  let env ← getEnv
  let some mod := owner env n | return e
  unless projectModule mod && !locked { mod, name := n, info := ← getConstInfo n } do
    return e
  let some c@(.defnInfo _) := env.find? n | return e
  match fuel with
  | 0 => throwError "命题骨架展开超过上限"
  | k + 1 => unfoldStatement ((c.instantiateValueLevelParams! us).beta e.getAppArgs) k

private def skeleton (e : Expr) (parallel : Bool := false) (fuel : Nat := 1024) :
    MetaM (Option String) := do
  let e ← unfoldStatement e
  if parallel && e.isConstOf `True then return some "True 不能作前提或合取项"
  match fuel with
  | 0 => throwError "命题骨架超过上限"
  | k + 1 =>
    if let .forallE n d r bi := e then
      if ← isProp d then
        if let some issue ← skeleton d true k then return some issue
      return ← withLocalDecl n bi d fun x => skeleton (r.instantiate1 x) false k
    if e.isAppOfArity `And 2 || e.isAppOfArity `Or 2 || e.isAppOfArity `Iff 2 then
      let p := e.isAppOfArity `And 2
      if let some issue ← skeleton e.getAppArgs[0]! p k then return some issue
      return ← skeleton e.getAppArgs[1]! p k
    if e.isAppOfArity `Not 1 then return ← skeleton e.appArg! false k
    if e.isAppOfArity `Exists 2 || e.isAppOfArity (Name.mkSimple "ExistsUnique") 2 then
      return ← withLocalDeclD `x e.getAppArgs[0]! fun x =>
        skeleton (e.appArg!.beta #[x]) false k
    if e.getAppFn.isFVar then return none
    if let .const n _ := e.getAppFn then
      if (← getConstInfo n).type.getForallBody == mkSort .zero then return none
    return some s!"头部 {e.getAppFn} 不是陈述范式允许的命题"

private def gateS (e : Entry) : MetaM Bool := do
  unless [`Chan.Defs, `Chan.Hypotheses, `Chan.Proxy, `Chan.Thm, `Chan.Proofs,
      `Chan.Exec, `ChanChallenge, `Chan.Final, `Chan.Audit].any (within e.mod) do return false
  unless e.info matches .thmInfo _ | .defnInfo _ | .opaqueInfo _ do return false
  unless ← isProp e.info.type do return false
  if let some issue ← skeleton e.info.type then
    finding "S" e "STATEMENT_FORM" (issue.replace "\n" " ")
  else pure false

private def telescope {α : Type} (type : Expr) (k : Array Expr → Expr → MetaM α) :
    MetaM α :=
  go 1024 #[] type
where
  go : Nat → Array Expr → Expr → MetaM α
    | 0, _, _ => throwError "望远镜超过上限"
    | fuel + 1, xs, ty => do
      let ty ← unfoldStatement ty
      if let .forallE n d r bi := ty then
        let d ← if ← isProp d then unfoldStatement d else pure d
        withLocalDecl n bi d fun x => go fuel (xs.push x) (r.instantiate1 x)
      else k xs ty

-- 用定义相等约束全称变量；未解出的前提须由同作用域的参数补齐。
private def premiseInstance (args : Array Expr) (conclusion : Expr) :
    Nat → Expr → MetaM Bool
  | 0, _ => throwError "假设实例化超过递归上限"
  | fuel + 1, ty => do
    let ty ← statementHead 128 ty
    if ← withoutModifyingState (isDefEq ty conclusion) then return true
    if ty.isAppOfArity `And 2 then
      return (← premiseInstance args conclusion fuel ty.getAppArgs[0]!) ||
        (← premiseInstance args conclusion fuel ty.getAppArgs[1]!)
    if ty.isForall then
      return ← withoutModifyingState <| withNewMCtxDepth do
        let (vars, _, body) ← forallMetaTelescope ty
        let rec fill (vs : List Expr) : MetaM Bool := do
          match vs with
          | [] => return !(← vars.anyM fun v => return (← instantiateMVars v).hasMVar)
          | v :: rest =>
            if !(← instantiateMVars v).isMVar then return ← fill rest
            return ← args.anyM fun a => withoutModifyingState do
              if ← isDefEq v a then fill rest else pure false
        let rec solve (body : Expr) (budget : Nat) : MetaM Bool := do
          let budget + 1 := budget | throwError "合取匹配超过上限"
          let body ← statementHead 128 body
          if body.isAppOfArity `And 2 then
            if ← withoutModifyingState (solve body.getAppArgs[0]! budget) then return true
            return ← solve body.getAppArgs[1]! budget
          unless ← isDefEq body conclusion do return false
          fill vars.toList
        solve body fuel
    return false

private def stripTrue : Nat → Expr → MetaM Expr
  | 0, _ => throwError "唯一性归一化超过上限"
  | k + 1, p => do
    let p ← statementHead 128 p
    if p.isAppOfArity `And 2 then
      let l ← stripTrue k p.getAppArgs[0]!
      let r ← stripTrue k p.getAppArgs[1]!
      if l.isConstOf `True then return r
      if r.isConstOf `True then return l
    return p

private def graphEq (x body : Expr) : MetaM Bool := do
  let some (_, a, b) := (← stripTrue 128 body).eq? | return false
  let a ← withTransparency .default <| whnf a
  let b ← withTransparency .default <| whnf b
  return (a == x && !containsFVar b x) || (b == x && !containsFVar a x)

private def functionGraph (result : Expr) : MetaM Bool := do
  let result ← stripTrue 128 result
  let result ← if result.isAppOfArity (Name.mkSimple "ExistsUnique") 2 then
      withTransparency .default <| whnf result
    else pure result
  let args := result.getAppArgs
  if result.isAppOfArity `Exists 2 then
    return ← withLocalDeclD `y args[0]! fun y => do
      let b ← stripTrue 128 (mkApp args[1]! y)
      unless b.isAppOfArity `And 2 do return false
      for (p, unique) in #[(b.getAppArgs[0]!, b.getAppArgs[1]!),
                             (b.getAppArgs[1]!, b.getAppArgs[0]!)] do
        unless ← graphEq y p do continue
        let q ← statementHead 128 unique
        let .forallE _ d rest _ := q | continue
        unless ← same d args[0]! do continue
        if ← withLocalDeclD `z d fun z => do
          let .forallE _ premise goal _ ← statementHead 128 (rest.instantiate1 z) | return false
          unless ← withoutModifyingState <| withTransparency .default <|
              isDefEq (← stripTrue 128 premise) (← stripTrue 128 (p.replaceFVar y z)) do return false
          let some (_, a, b) := (← stripTrue 128 goal).eq? | return false
          let a ← withTransparency .default <| whnf a
          let b ← withTransparency .default <| whnf b
          return (a == z && b == y) || (a == y && b == z)
        then return true
      return false
  return false

private def gate8a (e : Entry) (cfg : NodeConfig) : MetaM Bool :=
  telescope e.info.type fun xs result => do
    let (_, premises) ← params xs
    let mut red := false
    for h in premises do
      if ← premiseInstance (xs.filter (· != h)) result 256 (← inferType h) then
        red ← finding "8a" e "PREMISE_INSTANCE" s!"前提 {← h.fvarId!.getUserName} 的实例即结论"
    if cfg.declarative_unique && (← functionGraph result) then
      red ← finding "8a" e "FUNCTION_GRAPH" "声明式唯一性只复述函数图"
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

-- 替换的是原证明的定义等价展开，不为删前提重新搜证。
private def normalizeProof (body : Expr) : MetaM Expr := do
  let env ← getEnv
  let isLocked (n : Name) := (owner env n).any fun mod =>
    [`Chan.Defs, `Chan.Hypotheses, `Chan.Audit.Literal, `ChanChallenge].any (within mod)
  transform body (skipConstInApp := true) (pre := fun p => do
    if let .const n us := p.getAppFn then
      if ((owner env n).any projectModule && !isLocked n) ||
          [`Function.const, `And.left, `And.right].contains n then
        let some c := env.checked.get.find? n | throwError "缺少证明依赖 {n}"
        if c.hasValue true then
          return .visit ((c.instantiateValueLevelParams! us true).beta p.getAppArgs)
    let p' ← whnfCore p
    if p' != p then return .visit p'
    return .continue) (post := fun p => do
      let p' := (← whnfCore p).eta
      return if p' == p then .done p else .visit p')

private def gate8b (e : Entry) (cfg : NodeConfig) : MetaM Bool :=
  telescope e.info.type fun xs result => do
    let (_, premises) ← params xs
    if cfg.doc_only.any (fun (i, _) => i == 0 || i > premises.size) then
      throwError "{e.name}: doc_only 的前提序号超出望远镜"
    if premises.isEmpty then return false
    let body ← bodyOf e
    let applied ← normalizeProof (body.beta xs)
    let mut red := false
    for i in [:premises.size] do
      if (cfg.doc_only.lookup (i + 1)).isSome then continue
      let h := premises[i]!
      let label := s!"#{i + 1} {← h.fvarId!.getUserName}"
      let rest := xs.filter (· != h)
      if containsFVar result h || (← rest.anyM fun x => return containsFVar (← inferType x) h) then
        IO.eprintln s!"GATE8b NOTE {e.name}: 后续类型依赖 {label}，无法直接删去"
      else
        let ty ← mkForallFVars rest result
        let proof ← mkLambdaFVars rest applied
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
    if (env.getModuleIdxFor? n).any (·.toNat < earliest) then
      return ← hiddenDependency env targets earliest fuel todo seen
    let some c := env.checked.get.find? n | throwError "无法读取依赖 {n}"
    let mut seen := seen.insert n
    let mut pending := todo
    for d in c.getUsedConstantsAsSet.toList do
      if !seen.contains d && !(env.getModuleIdxFor? d).any (·.toNat < earliest) then
        seen := seen.insert d
        pending := d :: pending
    hiddenDependency env targets earliest fuel pending seen

private def constantApps (e : Expr) : IO (Array Expr) := do
  let found ← IO.mkRef ({} : Std.HashSet Expr)
  e.forEach (m := IO) fun t => do
    if t.isConst then found.modify (·.insert t)
  return (← found.get).toArray

private def inductiveOwner (env : Environment) (name : Name) : Option Name :=
  match env.find? name with
  | some (.inductInfo _) => some name
  | some (.ctorInfo info) => some info.induct
  | some (.recInfo info) => some info.getMajorInduct
  | _ =>
    env.getProjectionStructureName? name <|>
      if isAuxRecursor env name || isNoConfusion env name then some name.getPrefix else none

private def expand (env : Environment) (targets helpers : List Name) (nominal : NameSet) :
    Nat → Expr → MetaM Expr
  | 0, _ => throwError "辅助接口展开超过上限"
  | fuel + 1, e => do
    let earliest := (targets.filterMap (fun n => (env.getModuleIdxFor? n).map (·.toNat))).min?.getD 0
    let mut replacements : Array (Expr × Expr) := #[]
    for t in ← constantApps e do
      let .const n levels := t | continue
      if targets.contains n then continue
      if (inductiveOwner env n).any nominal.contains then continue
      let inHyp := (owner env n).any (within · `Chan.Hypotheses)
      let hasBody := (env.checked.get.find? n).any (·.hasValue true)
      if helpers.contains n || (inHyp && hasBody) then
        let some c := env.checked.get.find? n | throwError "无法读取辅助接口 {n}"
        unless c.hasValue true do throwError "不能展开辅助接口 {n}"
        let v ← expand env targets helpers nominal fuel (c.instantiateValueLevelParams! levels true)
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
  let body ← bodyOf e
  -- 归纳接口不能像函数别名一样展开：构造器的字段类型是名义接口的一部分。
  -- 若字段绑定 D，先保留名义接口并重放。只有接口本身不锁住 D 才能签发正证书。
  let mut nominal : NameSet := {}
  for c in (← constantApps e.info.type) ++ (← constantApps body) do
    let n := c.constName!
    if (owner env n).any (within · `Chan.Hypotheses) then
      if let some s := inductiveOwner env n then
        if !nominal.contains s && (← hiddenDependency env targets 0 20000 [s] {}) then
          nominal := nominal.insert s
  let ty ← expand env targets helpers nominal 128 e.info.type
  let proof ← expand env targets helpers nominal 128 body
  let all := (← constantApps ty) ++ (← constantApps proof)
  let mut ordered := []
  for n in targets do
    let relevant := (all.toList.filter (·.isConstOf n)).eraseDups
    if relevant.isEmpty && (← getConstInfo n).levelParams.isEmpty then
      ordered := ordered ++ [mkConst n]
    else ordered := ordered ++ relevant
  if ← abstractReplay e ordered #[] ty proof then
    unless nominal.isEmpty do
      IO.eprintln s!"GATE7b NOTE {e.name}: 重放保留锁定 D 的名义假设，不签发泛化证书"
      return false
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
  telescope e.info.type fun xs result => do
    let (_, premises) ← params xs
    let expected := (← witnessType premises none xs.toList none).getD (mkConst `True)
    let mut red ← checkWitness e entries "witness" "WITNESS" expected
    if cfg.main_theorem then
      for i in cfg.necessary ++ cfg.convenience.map Prod.fst do
        if i == 0 || i > premises.size then
          red ← finding "9" e "PREMISE_REGISTRATION" s!"序号 #{i} 超出命题前提望远镜"
    for i in [:premises.size] do
      let necessary := cfg.necessary.contains (i + 1)
      let convenience := (cfg.convenience.lookup (i + 1)).isSome
      if cfg.main_theorem && necessary == convenience then
        red ← finding "9" e "PREMISE_REGISTRATION" s!"前提 #{i + 1} 必须二选一登记必要性或便利性"
      if convenience then
        let _ ← finding "9" e "CONVENIENCE" s!"便利前提 #{i + 1}，{(cfg.convenience.lookup (i + 1)).getD ""}"
      if necessary || cfg.needs_necessity then
        let h := premises[i]!
        let negated := mkApp (mkConst `Not) result
        let expected := (← witnessType premises (some h) xs.toList (some negated)).getD negated
        red := (← checkWitness e entries s!"without_{i + 1}" "NECESSITY" expected) || red
    return red

private def equal (a b : Expr) : MetaM Bool :=
  withoutModifyingState <| withTransparency .all <| isDefEq a b

private def numeral (e : Expr) : MetaM (Option Nat) := do
  if let some i := e.rawNatLit? then return some i
  if e.isConstOf `Nat.zero then return some 0
  if e.isAppOfArity `OfNat.ofNat 3 then
    let some n := e.getAppArgs[1]!.rawNatLit? | return none
    if (← equal e.getAppArgs[0]! (mkConst `Nat)) && !(← equal e (mkNatLit n)) then
      return none
    return some n
  let e ← withTransparency .default <| whnf e
  if e.isAppOfArity `Int.ofNat 1 then return ← getNatValue? e.appArg!
  if e.isConstOf `Nat.zero then return some 0
  return e.rawNatLit?

private def guards (b : Expr) : Nat → Expr → MetaM Bool
  | 0, _ => pure false
  | k + 1, p => do
    let p ← statementHead 128 p
    let args := p.getAppArgs
    if p.isAppOfArity `And 2 then
      return (← guards b k args[0]!) || (← guards b k args[1]!)
    if p.isAppOfArity `Not 1 then
      if let some (_, x, y) := p.appArg!.eq? then
        return ((← numeral x) == some 0 && (← equal b y)) ||
          ((← numeral y) == some 0 && (← equal b x))
    if p.isAppOfArity `LT.lt 4 then
      return (← numeral args[2]!) == some 0 && (← equal b args[3]!)
    if ← equal (← inferType b) (mkConst `Nat) then
      return (← equal p (mkApp2 (mkConst `Nat.lt) (mkNatLit 0) b)) ||
        (← equal p (mkApp2 (mkConst `Nat.le) (mkNatLit 1) b))
    return false

private def safeDivisor (b : Expr) (kind : String) : MetaM Bool := do
  if kind != "HDiv.hDiv" && (← numeral b).any (· > 0) then return true
  let reduced ← withTransparency .all <| whnf b
  if kind == "Nat.div" then
    if reduced.isAppOfArity `Nat.succ 1 then return true
    for sum in #[b, reduced] do
      let args := sum.getAppArgs
      if args.size >= 2 then
        let a := args[args.size - 2]!
        let c := args[args.size - 1]!
        if (← numeral a).any (· > 0) || (← numeral c).any (· > 0) then
          if (← equal (← inferType a) (mkConst `Nat)) &&
              (← equal (← inferType c) (mkConst `Nat)) &&
              (← equal b (mkApp2 (mkConst `Nat.add) a c)) then return true
  let base :=
    if b.isAppOfArity `Subtype.val 3 then some b.appArg!
    else match reduced with
      | .proj n 0 x => if n == `Subtype then some x else none
      | _ => none
  if let some x := base then
    let xt ← whnf (← inferType x)
    if xt.isAppOfArity `Subtype 2 && (← guards b 128 (mkApp xt.appArg! b)) then
      return true
  for d in ← getLCtx do
    if ← guards b 128 d.type then return true
    let x := mkFVar d.fvarId
    let ty ← whnf d.type
    if let .const n _ := ty.getAppFn then
      let env ← getEnv
      if let some info := getStructureInfo? env n then
        for field in info.fieldNames do
          let some projFn := getProjFnForField? env n field | continue
          let proj ← mkAppM projFn #[x]
          if ← guards b 128 (← inferType proj) then return true
  return false

private def operation (e : Expr) : MetaM (Option String) := do
  let .const n _ := e.getAppFn | return none
  let args := e.getAppArgs
  let .str _ key := n | return none
  let isDivision := [`HDiv.hDiv, `Div.div].contains n ||
    ["div", "ediv", "tdiv", "fdiv", "bdiv"].contains key
  -- 类运算识别异质与同质族；直调接口保留具体运算名供签注定位。
  if [`HMod.hMod, `Mod.mod, `Inv.inv].contains n ||
      ["inv", "mod", "emod", "tmod", "fmod", "bmod"].contains key then
    return some n.toString
  if [`Nat.sub, `HSub.hSub, `Sub.sub].contains n || isDivision then
    let direct := ![`HSub.hSub, `HDiv.hDiv, `Sub.sub, `Div.div].contains n
    let offset := if direct then 0 else if n == `HSub.hSub || n == `HDiv.hDiv then 4 else 2
    if isDivision then
      let b := args[offset + 1]?
      let domain ← if let some d := b then inferType d
        else if !direct then pure (args[if offset == 4 then 1 else 0]?.getD (.sort .zero))
        else if let .forallE _ d _ _ := (← getConstInfo n).type then pure d
        else pure (.sort .zero)
      let kind ← if ← equal domain (mkConst `Nat) then pure "Nat.div"
        else if ← equal domain (mkConst `Int) then pure "Int.div"
        else if ← equal domain (mkConst `Rat) then pure "Rat.div"
        else pure "HDiv.hDiv"
      if let some divisor := b then
        if ← safeDivisor divisor kind then return none
      return some kind
    unless direct do
      let arity := offset - 1
      for i in [:arity] do
        let some ty := args[i]? | return none
        unless ← equal ty (mkConst `Nat) do return none
    return some "Nat.sub"
  if n == `Inhabited.default || n == `Finset.sup || n == `Finset.inf || n == `Nat.pred then
    return some n.toString
  if ["panicWithPosWithDecl", "panicWithPos", "panic", "panicCore"].contains key then
    return some "panic!"
  if key.endsWith "!" || ["getD", "getElemD", "headD", "getLastD",
      "backD", "frontD", "tailD", "sSup", "sInf", "iSup", "iInf"].contains key then
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
    IO.println <| (toJson #[e.mod.toString, e.name.toString, "10", "operation", op]).compress

def reportGates : List String := ["S", "7a", "7b", "8a", "8b", "9", "10"]

def report (entries : Array Entry) (cfg : Config) : MetaM UInt32 := do
  for e in entries do
    unless [`Chan, `ChanChallenge, `ChanDyn, `ChanTest].any (within e.mod) do continue
    let config := (cfg.nodes.lookup e.name.toString).getD {}
    let identity := #[e.mod.toString, e.name.toString]
    IO.println <| (toJson (identity.push "declaration")).compress
    for gate in reportGates do
      try
        -- 每条读数独立预算；失败条目不会消耗后续条目的预算或保留元变量。
        withoutModifyingState <| withCurrHeartbeats do
          match gate with
          | "S" => discard <| gateS e
          | "7a" => discard <| gate7a e cfg entries
          | "7b" => if ← node e then discard <| gate7b e config
          | "8a" => if ← node e then discard <| gate8a e config
          | "8b" => if e.info.hasValue true && (← node e) then discard <| gate8b e config
          | "9" => if ← node e then discard <| gate9 e config entries
          | "10" => gate10 e
          | _ => unreachable!
      catch err =>
        let detail ← err.toMessageData.toString
        IO.println <| (toJson (identity ++ #[gate, "unknown", "hint", "UNKNOWN", detail])).compress
  return 0

def run (gate : String) (entries : Array Entry)
    (publicView : Option Environment := none) : MetaM UInt32 := do
  let mut red := false
  for e in entries do
    let failed ← match gate with
      | "6a" =>
        if locked e then
          match statement (← getEnv) e with
          | .error detail => throwError "{e.name}: {detail}"
          | .ok j => IO.println <| (row e.name.toString [toJson e.mod.toString, j]).compress
        pure false
      | "15" =>
        let some env := publicView | throwError "缺少对外可见环境"
        if !isPrivateName e.name && (e.info matches .defnInfo _) &&
          (← findDeclarationRangesCore? e.name).isSome &&
          !(env.find? e.name matches some (.defnInfo _)) then
          finding "15" e "EXPOSE_SECTION" "公开定义未暴露定义体"
        else pure false
      | _ => throwError "未知环境门禁 {gate}"
    red := red || failed
  return if red then 1 else 0

end
end FM
