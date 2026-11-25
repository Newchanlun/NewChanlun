module
public import Mathlib.Order.Filter.AtTopBot.Defs
public import Mathlib.Order.RelIso.Basic
public section
open scoped Classical
theorem ev_thm (p : Nat → Prop) (h : ∀ n, p n) : ∀ᶠ n in Filter.atTop, p n :=
  Filter.Eventually.of_forall h
theorem rel_hom_thm (r : Nat → Nat → Prop) (f : RelHom r r) (a b : Nat) (h : r a b) : r (f a) (f b) :=
  f.map_rel' h
theorem rel_emb_thm (r : Nat → Nat → Prop) (f : RelEmbedding r r) (a b : Nat) (h : r a b) : r (f a) (f b) :=
  f.map_rel_iff.mpr h
