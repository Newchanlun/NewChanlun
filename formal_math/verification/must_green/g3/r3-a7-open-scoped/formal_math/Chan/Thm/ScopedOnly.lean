module
public section
namespace Foo
def a : Nat := 1
end Foo
open scoped Foo
@[simp] theorem trivEq (x : Nat) : x + 0 = x := rfl
