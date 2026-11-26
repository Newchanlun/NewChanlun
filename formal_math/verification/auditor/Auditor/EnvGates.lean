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
  | .letE _ t v b nondep =>
    return row "let" [toJson nondep, ← exprCode params t, ← exprCode params v, ← exprCode params b]
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
  -- v3：`let` 记 nondep 位（`have` 与 `let` 不再同码）。
  return row "FM-lock-v3" [canonicalName entry.name, toJson params.length,
    ← exprCode params info.type, value]

/-! 豁免第 4 类：自动参数的战术载体。

Lean 4.36.0 `Lean.Elab.Term.declareTacticSyntax`（`Lean/Elab/Binders.lean:92`）把 `:= by tac` 写成的
自动参数存成一个 `Lean.Syntax` 类型的辅助定义（值由 `quoteAutoTactic` 引号化而成）并 `markMeta`；
结构体字段名为 `<字段>._autoParam`，绑定器名为 `<声明>._auto_<数字>`。下面只认机械复核得出的那一份。
-/

private partial def quotedName : Expr → Option Name
  | .const ``Name.anonymous [] => some .anonymous
  | e => do
    let args := e.getAppArgs
    match e.getAppFn with
    | .const ``Name.str [] =>
      let #[p, .lit (.strVal s)] := args | none
      return (← quotedName p).str s
    | .const ``Name.num [] =>
      let #[p, n] := args | none
      return (← quotedName p).num (← n.nat?)
    | .const (.str ``Name s) [] =>
      guard (s.startsWith "mkStr")
      args.foldlM (init := .anonymous) fun n a => match a with
        | .lit (.strVal x) => some (n.str x)
        | _ => none
    | _ => none

private partial def quotedList (item : Expr → Option α) : Expr → Option (List α)
  | e => do
    let args := e.getAppArgs
    match e.getAppFn, args.size with
    | .const ``List.nil _, 1 => return []
    | .const ``List.cons _, 3 => return (← item args[1]!) :: (← quotedList item args[2]!)
    | _, _ => none

private def quotedPreresolved (e : Expr) : Option Syntax.Preresolved := do
  let args := e.getAppArgs
  match e.getAppFn, args with
  | .const ``Syntax.Preresolved.namespace [], #[n] => return .namespace (← quotedName n)
  | .const ``Syntax.Preresolved.decl [], #[n, fs] =>
    return .decl (← quotedName n) (← quotedList (fun | .lit (.strVal s) => some s | _ => none) fs)
  | _, _ => none

/-- `quoteAutoTactic` 的逆：只认它产出的那几种形状，其余返回 `none`；是否逐字相同由调用方重算比对。 -/
private partial def quotedSyntax (e : Expr) : Option Syntax := do
  let args := e.getAppArgs
  match e.getAppFn, args with
  | .const ``Syntax.node [], #[_, k, xs] => return .node .none (← quotedName k) (← quotedArray xs)
  | .const ``mkAtom [], #[.lit (.strVal s)] => return .atom .none s
  | .const ``Syntax.ident [], #[_, _, n, pre] =>
    let n ← quotedName n
    return .ident .none (toString n).toRawSubstring n (← quotedList quotedPreresolved pre)
  | _, _ => none
where
  quotedArray (e : Expr) : Option (Array Syntax) := do
    let args := e.getAppArgs
    match e.getAppFn, args with
    | .const ``Array.empty _, #[_] => return #[]
    | .const ``Array.push _, #[_, xs, x] => return (← quotedArray xs).push (← quotedSyntax x)
    | _, _ => none

private def carrierName : Name → Bool
  | .str _ s =>
    s == "_autoParam" || (s.startsWith "_auto_" && (s.toList.drop 6 |>.all Char.isDigit) && s.length > 6)
  | _ => false

/--
自动参数战术载体：带 `meta` 标记的常量只有同时满足下列各条才豁免 `ENV_META`，判据全部从环境现算。
1. 名字末段是 `_autoParam` 或 `_auto_<数字>`；
2. 安全的普通定义：`defnInfo`、`safe`，无 `implemented_by`、无 `extern`；无宇宙参数、`opaque` 提示
   （手写的 `def` 一律是 `regular` 提示，源码写不出满足这一条的冒用）；
3. 类型恰为 `Lean.Syntax`；
4. 同一模块里另有常量的类型含 `autoParam _ <该常量>`；
5. 值是 `quoteAutoTactic` 对某棵语法树的输出，逐字相同（解码后用 Lean 自己的 `quoteAutoTactic` 重算比对）。
第 3、5 条对源码写得出的冒用是冗余的（已被第 2 条的提示挡住），防的是产物被伪造时载体形态不符。
-/
def autoParamCarriers (entries : Array Entry) : MetaM NameSet := do
  let env ← getEnv
  let refs ← IO.mkRef ({} : NameSet)
  for e in entries do
    e.info.type.forEachWhere (·.isAppOfArity ``autoParam 2) fun x => do
      if let .const c [] := x.appArg! then
        if c != e.name && (env.getModuleIdxFor? c).isSome &&
            env.getModuleIdxFor? c == env.getModuleIdxFor? e.name then
          refs.modify (·.insert c)
  let refs ← refs.get
  entries.foldlM (init := {}) fun s e => do
    let .defnInfo d := e.info | return s
    unless isMarkedMeta env e.name && carrierName e.name do return s
    unless d.safety == .safe && !isExtern env e.name && (Compiler.getImplementedBy? env e.name).isNone do return s
    unless d.levelParams.isEmpty && d.hints matches .opaque do return s
    unless d.type == .const ``Syntax [] do return s
    unless refs.contains e.name do return s
    let some stx := quotedSyntax d.value | return s
    unless ← (try pure ((← Elab.Term.quoteAutoTactic stx) == d.value) catch _ => pure false) do return s
    return s.insert e.name

/-- 结构化发现行：`["finding", 门, 路径, 声明, 红码, 说明]`。 -/
def emitFinding (gate path decl code detail : String) : IO Unit :=
  IO.println (row "finding" [toJson gate, toJson path, toJson decl, toJson code, toJson detail]).compress

private def finding (gate : String) (e : Entry) (code detail : String) : MetaM Bool := do
  let path := e.mod.toString.replace "." "/"
  emitFinding gate s!"formal_math/{path}.lean" e.name.toString code detail
  return true

def run (gate : String) (entries : Array Entry)
    (publicView : Option Environment := none) (derived : NameSet := {}) : MetaM UInt32 := do
  let mut red := false
  for e in entries do
    let failed ← match gate with
      | "6a" =>
        if locked e then
          match statement (← getEnv) e with
          | .error detail => throwError "{e.name}: {detail}"
          | .ok j => IO.println <| (row "lock" [toJson e.name.toString, toJson e.mod.toString, j]).compress
        pure false
      | "15" =>
        let some env := publicView | throwError "缺少对外可见环境"
        -- 派生处理器给 Repr、Hashable 的辅助函数贴 @[no_expose]；源码层派生证书里的不算手写定义。
        if !isPrivateName e.name && (e.info matches .defnInfo _) && !derived.contains e.name &&
          (← findDeclarationRangesCore? e.name).isSome &&
          !(env.find? e.name matches some (.defnInfo _)) then
          finding "15" e "EXPOSE_SECTION" "公开定义未暴露定义体"
        else pure false
      | _ => throwError "未知环境门禁 {gate}"
    red := red || failed
  return if red then 1 else 0

end
end FM
