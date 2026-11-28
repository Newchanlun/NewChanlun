module
public section
namespace Foo
scoped instance : Inhabited Unit := ⟨()⟩
end Foo
open scoped Foo
@[simp] theorem trivEq (x : Nat) : x + 0 = x := rfl
def f (x : Nat) : Nat := x
attribute [simp] f
