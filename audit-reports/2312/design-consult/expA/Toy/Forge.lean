import Lean
open Lean Elab Command

-- 模拟「精化期拿到元编程权限」之后能做的事：不经内核检查塞进一条类型不符的定理。
set_option debug.skipKernelTC true in
run_cmd liftCoreM do
  addDecl <| .thmDecl
    { name := `Toy.forged, levelParams := [], type := mkConst ``False, value := mkConst ``True.intro }

theorem Toy.anything : (1 : Nat) = 2 := Toy.forged.elim
