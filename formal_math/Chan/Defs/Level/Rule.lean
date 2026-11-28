module

public import Chan.Defs.Center.Center
public import Chan.Defs.Alt.CutChain

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Order Chan.Defs.Path Chan.Defs.Alt Chan.Defs.Center
universe u
variable {P Q : Type u} [Std.LinearOrderPackage P] [Std.LinearOrderPackage Q]

/-- 深度依赖基底标签。同深度而基底不同，不是同一类型的级别。
[017:40] 这里有一个递归的问题，就是这次级别不能无限下去，就像有些半吊子哲学胡诌什么，而“分”不是无限的，按照量子力学，物质之分是有极限的，同样，级别之次也不可能无限，在实际之中，对最后不能分解的级别，其缠中说禅走势中枢就不能用“至少三个连续次级别走势类型所重叠”定义，而定义为至少三个该级别单位K线重叠部分。
[101:58] 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。 -/
structure Level {Tag : Type _} (base : Tag) where
  depth : Nat
  deriving DecidableEq

/-- 块语言读取层深、段列、逆序的既往块首及本块起止。无值表示不合法，数值越大越优先。已确认标志另列。
[038:18] 显然，一个好的分解，其分解规则下，必须保证分解的唯一性，否则这种分解就绝对不可能是好的分解。
[057:40] 当行情走到6点时，34、45、56这三段，就可以看成是一个1分钟中枢了，当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。 -/
structure BlockRule where
  rank : {P : Type u} → [Std.LinearOrderPackage P] →
    Nat → List (Seg P) → List Nat → Nat → Nat → Option Nat
  confirmed : {P : Type u} → [Std.LinearOrderPackage P] →
    Nat → List (Seg P) → List Nat → Nat → Nat → Bool

/-- 上一级段保留全部下级值域与来源的凸包；方向取块首方向，不从极值倒推。
[053:20] 但无论这些显微镜如何转换，一个原则是不变的，就是当你用一个级别的显微镜时，就等于先把次级别的当成线段了，也就是说次级别不在该级别的观察中。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。 -/
def BlockRule.coarsen (xs : List (Seg P)) (i j : Nat) : Option (Seg P) :=
  if j > xs.length then none else
    match xs.extract i j with
    | [] => none
    | a :: tail =>
      let src := tail.foldl (fun x s =>
        (⟨min x.first s.source.first, max x.last s.source.last,
          Nat.le_trans (Nat.min_le_left _ _) (Nat.le_trans x.ordered (Nat.le_max_left _ _))⟩ : Span)) a.source
      some ⟨a.dir, hullInterval a.range (tail.map Seg.range), src⟩

/-- 给定局部上下文，穷举边界内合法的块尾与规则优先级。
[099:26] 如果后面包括d+e+f延伸出9段，然后又直接上去了，划分中，必须首先保证5分钟中枢的成立。换言之，划分的原则很明确，就是必须保证中枢的确立，在这前提下，可以根据结合律，使得连接中枢的走势保持最完美的形态。 -/
def BlockRule.ends (r : BlockRule) (k : Nat) (xs : List (Seg P)) (past : List Nat) (i : Nat) :=
  (List.range (xs.length + 1)).filterMap fun j =>
    if i < j then (r.rank k xs past i j).map (fun score => (j, score)) else none

/-- 端点按规则给定的优先级占优；不额外规定长块或短块必胜。
[099:26] 如果后面包括d+e+f延伸出9段，然后又直接上去了，划分中，必须首先保证5分钟中枢的成立。换言之，划分的原则很明确，就是必须保证中枢的确立，在这前提下，可以根据结合律，使得连接中枢的走势保持最完美的形态。 -/
def BlockRule.preferred (r : BlockRule) (k : Nat) (xs : List (Seg P)) (past : List Nat)
    (i j : Nat) : Bool :=
  match r.rank k xs past i j with
  | none => false
  | some score => decide (i < j ∧ j ≤ xs.length) &&
      (r.ends k xs past i).all (fun p => decide (p.2 ≤ score))

/-- 五条接口律的逐输入判定。规则满足接口律指对任意层、变换、候选块和合法延拓均成立。
[043:44] 缠中说禅走势类型分解原则：一个某级别的走势类型中，不可能出现比该级别更大的中枢，一旦出现，就证明这不是一个某级别的走势类型，而是更大级别走势类型的一部分或几个该级别走势类型的连接。
[018:24] 则，中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））而实际上用目测就可以，不用这么复杂。 -/
def InterfaceLaws (r : BlockRule) (k : Nat) (s t : AltSeq P) (f : OrderEmb P Q)
    (past : List Nat) (i j : Nat) : Bool :=
  let score := r.rank k s.items past i j
  let contracts := !score.isSome || decide (i < j ∧ j ≤ s.items.length)
  let seeded := !score.isSome || (decide (i + 3 ≤ j) &&
    (List.range (j - i - 2)).any (fun n => CanSeedCenter s (i+n)))
  let orderInvariant := decide (r.rank k (s.mapEmb f).items past i j = score) &&
    decide (r.confirmed k (s.mapEmb f).items past i j = r.confirmed k s.items past i j)
  let mirrorInvariant := decide (r.rank k (dualAltSeq s).items past i j = score) &&
    decide (r.confirmed k (dualAltSeq s).items past i j = r.confirmed k s.items past i j)
  let stable := !r.confirmed k s.items past i j || !(s.items.isPrefixOf t.items) ||
    (score.isSome && r.preferred k s.items past i j &&
      decide (r.rank k t.items past i j = score) && r.preferred k t.items past i j &&
      r.confirmed k t.items past i j)
  contracts && seeded && orderInvariant && mirrorInvariant && stable

/-- 同一规则以固定界约束每个完成块，且每次至少三合一；不设上限的规则不预设此律。
[057:42] 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。这一点其实由6这个第三类卖点的存在以及后面的背驰，就可以知道，这中枢级别的扩展，是必然的。
[043:44] 缠中说禅走势类型分解原则：一个某级别的走势类型中，不可能出现比该级别更大的中枢，一旦出现，就证明这不是一个某级别的走势类型，而是更大级别走势类型的一部分或几个该级别走势类型的连接。 -/
def CarryBounded (r : BlockRule) (bound k : Nat) (xs : List (Seg P)) (past : List Nat)
    (i : Nat) : Bool :=
  (r.ends k xs past i).all (fun p => decide (i + 3 ≤ p.1 ∧ p.1 ≤ i + bound))

/-- 每个已选块首恰有一个占优块尾且等于所选尾；最后一个切点起不再成块。优先级相同的歧义不会被隐藏。
[038:18] 显然，一个好的分解，其分解规则下，必须保证分解的唯一性，否则这种分解就绝对不可能是好的分解。
[101:52] 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。 -/
def DeterministicBlocks (r : BlockRule) (k : Nat) (xs : List (Seg P)) (marks : List Nat) : Bool :=
  decide (marks.head? = some 0) && marks.zipIdx.all fun p =>
    let past := (marks.take p.2).reverse
    let ends := r.ends k xs past p.1
    match marks[p.2+1]? with
    | some j => decide ((ends.filter fun q => r.preferred k xs past p.1 q.1).map Prod.fst = [j])
    | none => ends.isEmpty

end Chan.Defs.Level
