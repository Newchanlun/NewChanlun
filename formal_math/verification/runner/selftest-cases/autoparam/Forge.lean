/-
单元自测 U1 的被测环境（测试设施，不是被审内容，不经过流水线）：用 `addDecl` 直接造常量，每个反例只在
`FM.autoParamCarriers` 的一条判据上与正例不同。由 `Check.lean` 按私有层级读回，调用判定函数。
-/
import Lean
open Lean Elab Command

abbrev MySyn := Lean.Syntax

/-- 造一个定义；`meta` 标记、提示、安全性、宇宙参数可调。 -/
def forge (n : Name) (type value : Expr) (hints := ReducibilityHints.opaque)
    (safety := DefinitionSafety.safe) (lps : List Name := []) (isMeta := true) : CoreM Unit := do
  addDecl (.defnDecl { name := n, levelParams := lps, type, value, hints, safety })
  if isMeta then modifyEnv (markMeta · n)

/-- 造一个类型为 `autoParam True c → True` 的引用者。 -/
def use (n c : Name) (us : List Level := []) (safety := DefinitionSafety.safe) : CoreM Unit := do
  let dom := mkApp2 (.const ``autoParam [Level.zero]) (mkConst ``True) (.const c us)
  let type := mkForall `h .default dom (mkConst ``True)
  let value := mkLambda `h .default dom (mkConst ``True.intro)
  addDecl (.defnDecl { name := n, levelParams := [], type, value, hints := .regular 1, safety })

run_cmd liftTermElabM do
  -- 正例 1：生成器本身（`declareTacticSyntax`）产出的载体。
  let tac ← `(tactic| omega)
  discard <| Term.declareTacticSyntax tac (some `U.ok._auto_1)
  use `U.ok.use `U.ok._auto_1
  let syn := mkConst ``Syntax
  let some (.defnInfo d) := (← getEnv).find? `U.ok._auto_1 | throwError "正例没有生成"
  let v := d.value
  -- 正例 2：逐字照抄生成值，名字是字段形态。
  forge `U.field._autoParam syn v
  use `U.field.use `U.field._autoParam
  -- 判据 1：名字形态不对。
  forge `U.badName syn v
  use `U.badName.use `U.badName
  forge `U.noDigits._auto_ syn v
  use `U.noDigits.use `U.noDigits._auto_
  -- 判据 2：安全性、提示、宇宙参数。
  forge `U.unsafe._auto_1 syn v (safety := .unsafe)
  use `U.unsafe.use `U.unsafe._auto_1 (safety := .unsafe)
  forge `U.hints._auto_1 syn v (hints := .regular 1)
  use `U.hints.use `U.hints._auto_1
  forge `U.abbrev._auto_1 syn v (hints := .abbrev)
  use `U.abbrev.use `U.abbrev._auto_1
  forge `U.univ._auto_1 syn v (lps := [`u])
  use `U.univ.use `U.univ._auto_1 [Level.zero]
  forge `U.impl._auto_1 syn v
  use `U.impl.use `U.impl._auto_1
  forge `U.helper syn (mkApp (mkConst ``mkAtom) (mkStrLit "x"))
  -- 判据 3：类型是定义上相等的别名，不是 `Lean.Syntax` 本身。
  forge `U.alias._auto_1 (mkConst ``MySyn) v
  use `U.alias.use `U.alias._auto_1
  -- 判据 4：没有任何常量以 `autoParam` 引用。
  forge `U.orphan._auto_1 syn v
  -- 判据 5：值里有函数调用；值里引用别的常量；形状对但与重算结果不等（两种）。
  let call ← instantiateMVars (← Term.elabTermEnsuringType (← `(Lean.mkAtom ("om" ++ "ega"))) syn)
  forge `U.call._auto_1 syn call
  use `U.call.use `U.call._auto_1
  let arr := mkApp2 (mkConst ``Array.push [Level.zero]) syn (mkApp (mkConst ``Array.empty [Level.zero]) syn)
  let null := mkApp (mkConst ``Name.mkStr1) (mkStrLit "null")
  forge `U.ref._auto_1 syn (mkApp3 (mkConst ``Syntax.node) (mkConst ``SourceInfo.none) null
    (mkApp arr (mkConst `U.helper)))
  use `U.ref.use `U.ref._auto_1
  let ident (raw : String) (n : Expr) := mkApp4 (mkConst ``Syntax.ident) (mkConst ``SourceInfo.none)
    (mkApp (mkConst ``String.toRawSubstring) (mkStrLit raw)) n
    (mkApp (mkConst ``List.nil [Level.zero]) (mkConst ``Syntax.Preresolved))
  forge `U.identOk._auto_1 syn (ident "x" (mkApp (mkConst ``Name.mkStr1) (mkStrLit "x")))
  use `U.identOk.use `U.identOk._auto_1
  forge `U.rawNeq._auto_1 syn (ident "y" (mkApp (mkConst ``Name.mkStr1) (mkStrLit "x")))
  use `U.rawNeq.use `U.rawNeq._auto_1
  forge `U.nameNeq._auto_1 syn (mkApp3 (mkConst ``Syntax.node) (mkConst ``SourceInfo.none)
    (mkApp2 (mkConst ``Name.str) (mkConst ``Name.anonymous) (mkStrLit "null"))
    (mkApp (mkConst ``Array.empty [Level.zero]) syn))
  use `U.nameNeq.use `U.nameNeq._auto_1
  -- 对照：不带 meta 标记的同形常量不在判定范围内（它本来就不报 ENV_META）。
  forge `U.plain._auto_1 syn v (isMeta := false)
  use `U.plain.use `U.plain._auto_1

attribute [implemented_by U.helper] U.impl._auto_1
