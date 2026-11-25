-- R4-B1 & R4-B2 独立复验样本：普通递归类型 deriving Ord 与 Chan/Defs 内 deriving Repr/Hashable；在 R5 门 2/3/15 均退 0
module
@[expose] public section
inductive BinTree where
  | leaf (v : Nat)
  | node (l r : BinTree)
deriving Ord, Repr, Hashable, DecidableEq, BEq
