import Lean
open Lean Elab Command

-- 探针：4.36.0 的内核是否还认 `Lean.reduceBool` 这个名字（旧版 native_decide 的内核钩子）。
namespace Lean
opaque reduceBool (b : Bool) : Bool := b
end Lean

def implTrue (_ : Unit) : Bool := true
@[implemented_by implTrue] def f (_ : Unit) : Bool := false

run_cmd liftCoreM do
  let ty := mkApp3 (mkConst ``Eq [1]) (mkConst ``Bool)
    (mkApp (mkConst `Lean.reduceBool) (mkApp (mkConst ``f) (mkConst ``Unit.unit))) (mkConst ``Bool.true)
  let val := mkApp2 (mkConst ``Eq.refl [1]) (mkConst ``Bool) (mkConst ``Bool.true)
  let decl := Declaration.thmDecl { name := `hookProbe, levelParams := [], type := ty, value := val }
  match (← getEnv).toKernelEnv.addDeclCore 0 0 decl (cancelTk? := none) with
  | .ok _ => logInfo "KERNEL ACCEPTED: reduceBool hook is active"
  | .error _ => logInfo "KERNEL REJECTED: no reduceBool hook"
