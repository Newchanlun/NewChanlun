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
