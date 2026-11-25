module
@[expose] public section
def f_arr_get (xs : Array Nat) (i : Nat) : Nat := xs[i]!
def f_list_get (xs : List Nat) (i : Nat) : Nat := xs[i]!
def f_list_head (xs : List Nat) : Nat := xs.head!
def f_list_headD (xs : List Nat) : Nat := xs.headD 0
def f_arr_back (xs : Array Nat) : Nat := xs.back!
def f_arr_getD (xs : Array Nat) (i : Nat) : Nat := xs.getD i 0
def f_opt_get (o : Option Nat) : Nat := o.get!
def f_opt_getD (o : Option Nat) : Nat := o.getD 0
def f_tail (xs : List Nat) : List Nat := xs.tail!
