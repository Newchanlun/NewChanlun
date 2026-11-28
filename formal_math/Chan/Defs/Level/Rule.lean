module

public import Chan.Defs.Center.Center
public import Chan.Defs.Alt.CutChain

@[expose] public section

namespace Chan.Defs

/-- 深度依赖基底标签。同深度而基底不同，不是同一类型的级别。
[017:40] 这里有一个递归的问题，就是这次级别不能无限下去，就像有些半吊子哲学胡诌什么，而“分”不是无限的，按照量子力学，物质之分是有极限的，同样，级别之次也不可能无限，在实际之中，对最后不能分解的级别，其缠中说禅走势中枢就不能用“至少三个连续次级别走势类型所重叠”定义，而定义为至少三个该级别单位K线重叠部分。
[101:58] 分型等于递归函数的a0，这完全可以随意设计，如何设计都不会影响到唯一分解定理的证明。 -/
structure Level {Tag : Type _} (base : Tag) where
  depth : Nat
  deriving DecidableEq

end Chan.Defs

namespace Chan.Defs.Level

open Chan.Defs.Order Chan.Defs.Path Chan.Defs.Alt Chan.Defs.Center
universe u
variable {P Q : Type u} [LinearOrder P] [LinearOrder Q]

/-- #2296（needs-fable U-1）：高阶块方向由调用方选取，暂不要求粗化结果交替。 -/
abbrev CoarseDirPolicy (P : Type _) [LinearOrder P] := Seg P → List (Seg P) → Dir

/-- 用首段方向的显式对照策略。 -/
def CoarseDirPolicy.firstSegment : CoarseDirPolicy P := fun a _ => a.dir

/-- 块语言读取层深、段列、逆序的既往块首及本块起止。无值表示不合法，数值越大越优先。已确认标志另列。
[038:18] 显然，一个好的分解，其分解规则下，必须保证分解的唯一性，否则这种分解就绝对不可能是好的分解。
[057:40] 当行情走到6点时，34、45、56这三段，就可以看成是一个1分钟中枢了，当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。 -/
structure BlockRule where
  rank : {P : Type u} → [LinearOrder P] →
    Nat → List (Seg P) → List Nat → Nat → Nat → Option Nat
  confirmed : {P : Type u} → [LinearOrder P] →
    Nat → List (Seg P) → List Nat → Nat → Nat → Bool

/-- 把合法范围内的非空块粗化为真实值域和来源凸包；不把越界块截短。

[102:38] 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式
-/
def BlockRule.coarsen (xs : List (Seg P)) (i j : Nat)
    (dir : CoarseDirPolicy P) : Option (Seg P) :=
  if i < j ∧ j ≤ xs.length then
    match xs.extract i j with
    | [] => none
    | a :: tail =>
      some ⟨dir a tail, hullInterval a.range (tail.map Seg.range),
        tail.foldl (fun source s => source.join s.source) a.source⟩
  else none

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

/-- 五条接口律的逐点判定。粗化后的段列可以不交替；只有已确认块承担延拓稳定义务。
[043:44] 缠中说禅走势类型分解原则：一个某级别的走势类型中，不可能出现比该级别更大的中枢，一旦出现，就证明这不是一个某级别的走势类型，而是更大级别走势类型的一部分或几个该级别走势类型的连接。
-/
def checkStageInterfaceLaws (r : BlockRule) (k : Nat) (xs ys : List (Seg P)) (f : OrderEmb P Q)
    (past : List Nat) (i j : Nat) : Bool :=
  let score := r.rank k xs past i j
  let confirmed := r.confirmed k xs past i j
  let contracts := !score.isSome || decide (i < j ∧ j ≤ xs.length)
  let seeded := !score.isSome || (decide (i + 3 ≤ j) &&
    (List.range (j - i - 2)).any (fun n => CanSeedCenter xs (i+n)))
  let mapped := xs.map (Seg.mapEmb f)
  let mirrored := xs.map dualSeg
  let orderInvariant := decide (r.rank k mapped past i j = score) &&
    decide (r.confirmed k mapped past i j = confirmed)
  let mirrorInvariant := decide (r.rank k mirrored past i j = score) &&
    decide (r.confirmed k mirrored past i j = confirmed)
  let stable := !confirmed || !(xs.isPrefixOf ys) ||
    (score.isSome && r.preferred k xs past i j &&
      decide (r.rank k ys past i j = score) && r.preferred k ys past i j &&
      r.confirmed k ys past i j)
  contracts && seeded && orderInvariant && mirrorInvariant && stable

/-- 交替段列的逐点检查入口，与一般段列共用判定。 -/
def checkInterfaceLaws (r : BlockRule) (k : Nat) (s t : AltSeq P) (f : OrderEmb P Q)
    (past : List Nat) (i j : Nat) : Bool :=
  checkStageInterfaceLaws r k s.items t.items f past i j

/-- 底层和上层共用的全称接口契约：合法块边界与成核、序嵌入、对偶，以及已确认前缀稳定。
量化范围包括任意段列，不以方向交替为前提。

[099:22] 另外，根据结合律，连接中枢的走势，并不一定是完全的趋势类型，也就是说，一个线段类上涨后，可能第二类类中枢就消融在中阴状态的那个中枢里了。也就是说，a+b+c+d+e+f= a+b+c+（d+e+f），a+b+c+d+e是一个线段类上涨，c+d+e的重合部分构成最后的一个类中枢，f是类背驰后的回调，这时候，就可以马上构成一个1分钟的中枢，然后后面直接继续上涨，构成1分钟的上涨是完全合理的。因为，最终的划分，就必须把a+b+c+d+e给拆开了。
[102:38] 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式
-/
def InterfaceLaws (r : BlockRule.{u}) : Prop :=
  ∀ {A B : Type u} [LinearOrder A] [LinearOrder B] (k : Nat)
    (xs ys : List (Seg A)) (f : OrderEmb A B) (past : List Nat) (i j : Nat),
    checkStageInterfaceLaws r k xs ys f past i j = true

/-- 成核后三段以外仍逐段与固定核重叠；长度包含成核三段。 -/
def extRun (xs : List (Seg P)) (start : Nat) : Nat :=
  match xs.drop start with
  | a :: b :: c :: tail =>
    let bounds := seedBounds a b c
    if h : bounds.1 ≤ bounds.2 then
      let core : Bar P := ⟨bounds.1, bounds.2, h⟩
      3 + (tail.takeWhile (fun s => decide (overlaps core s.range))).length
    else 0
  | _ => 0

/-- 给定首段与长度的延伸窗口存在，等价于该长度不超过连续延伸总长。 -/
abbrev ExtRun (xs : List (Seg P)) (start len : Nat) : Prop :=
  3 ≤ len ∧ len ≤ extRun xs start

/-- 只约束块内单核最长连续延伸，不把前导进入段计入延伸。
九段几何不成立时（`nineAt = false`），普通块可以继续延伸；九段上界不是进位规则的保证。
回归见证 `b2Extended` 给出 `CarryBounded carry 9 0 b2Extended [] 0 = false`。

[057:42] 显然，这10个线段，已经组成了一个更高级别的5分钟中枢，结合方式如下：（12+23+34）+（45+56+67）+（78+89+910），该中枢的区间是[4015，4122]。这一点其实由6这个第三类卖点的存在以及后面的背驰，就可以知道，这中枢级别的扩展，是必然的。
-/
def CarryBounded (r : BlockRule) (bound k : Nat) (xs : List (Seg P)) (past : List Nat)
    (i : Nat) : Bool :=
  (r.ends k xs past i).all fun p =>
    let block := xs.extract i p.1
    decide (i + 3 ≤ p.1) &&
      (List.range block.length).all (fun start => decide (extRun block start ≤ bound))

/-- 进位有界律：对所有价格载体、层深、段列与历史，逐点延伸界均成立。 -/
def CarryBoundedProp (r : BlockRule.{u}) (bound : Nat) : Prop :=
  ∀ {P : Type u} [LinearOrder P] (k : Nat) (xs : List (Seg P)) (past : List Nat) (i : Nat),
    CarryBounded r bound k xs past i = true

/-- 可选的总块长上界，与单核延伸上界分开。 -/
def BlockLengthBounded (r : BlockRule) (bound k : Nat) (xs : List (Seg P)) (past : List Nat)
    (i : Nat) : Bool :=
  (r.ends k xs past i).all (fun p => decide (p.1 - i ≤ bound))

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

/-- 规则级唯一占优：有合法块尾时，恰有一个取最大优先级的块尾。

[038:18] 显然，一个好的分解，其分解规则下，必须保证分解的唯一性，否则这种分解就绝对不可能是好的分解。
-/
def DeterministicRule (r : BlockRule.{u}) : Prop :=
  ∀ {P : Type u} [LinearOrder P] (k : Nat) (xs : List (Seg P)) (past : List Nat) (i : Nat),
    let ends := r.ends k xs past i
    ends ≠ [] → (ends.filter (fun p => r.preferred k xs past i p.1)).length = 1

end Chan.Defs.Level
