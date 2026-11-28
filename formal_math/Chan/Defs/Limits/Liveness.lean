module

public import Chan.Defs.Level.Canonical
public import Chan.Defs.Path.History
public import Mathlib.Order.Filter.AtTopBot.Basic
public import Mathlib.Order.Filter.EventuallyConst

/-!
# M18 无限走势、可观测性与“走势必完美”的四条独立命题签名

本文件只给命题签名（取值为 `Prop` 的定义），不断言其成立；活性以显式参数传入，不设公理。
-/

@[expose] public section

namespace Chan.Defs.Limits

open Chan.Defs.Alt Chan.Defs.Level Chan.Defs.Path

universe u

/-- 自然数索引的无限价格路径。

[017:60]「因为某种类型的走势完成以后就会转化为其他类型的走势，对于下跌的走势来说，一旦完成，只能转化为上涨与盘整，因此，一旦能把握下跌走势转化的关节点买入，就在市场中占据了一个最有利的位置，而这个买点，就是前面反复强调的“第一类买点”；」 -/
abbrev InfPath (A : Type*) := ℕ → A

/-- 截断至前 `n` 步的有限历史。

[二级旁证 105:442]「另外，由于大多数人的科学与哲学知识都很贫乏，容易被人唬住，本ID给大家一个最简单的判别标准，就是可观察量。现代科学最基本的概念不是其他，而是可观察量，任何在科学的范围内谈论的东西，必须是可观察的。因此，那一切涉及非可观察量的玩意都是可疑的，例如什么宇宙的无穷，事件的无穷，神秘的自然规律，上帝的启示，辨证唯物主义或这主义那非主义的规律所引发的所谓宇宙规律等等。」 -/
def prefixOf {A : Type*} (x : InfPath A) (n : ℕ) : History A :=
  List.ofFn (fun i : Fin n => x i.val)

/-- 由有限前缀决定的可观测谓词：每条路径都有一个前缀长度，凡与之共享该前缀的路径取值相同。

[二级旁证 105:442]「另外，由于大多数人的科学与哲学知识都很贫乏，容易被人唬住，本ID给大家一个最简单的判别标准，就是可观察量。现代科学最基本的概念不是其他，而是可观察量，任何在科学的范围内谈论的东西，必须是可观察的。因此，那一切涉及非可观察量的玩意都是可疑的，例如什么宇宙的无穷，事件的无穷，神秘的自然规律，上帝的启示，辨证唯物主义或这主义那非主义的规律所引发的所谓宇宙规律等等。」 -/
def PrefixObservable {A : Type*} (Q : InfPath A → Prop) : Prop :=
  ∀ x : InfPath A, ∃ n, ∀ y : InfPath A, prefixOf y n = prefixOf x n → (Q y ↔ Q x)

/-- 在线分析量沿逐步加长的前缀在 `Filter.atTop` 下最终常值。

[102:20]「同样，本ID的理论给出的递归函数，完美地给出市场走势一个类似记数法一样的唯一分解，也就是说，本ID揭示了看似毫无规律的市场走势竟然有着和自然数有着类似的整体结构，完全超越一般的想象，这才是真正最牛的地方。」 -/
def EventuallyStable {A B : Type*} (f : History A → B) (x : InfPath A) : Prop :=
  Filter.EventuallyConst (fun n => f (prefixOf x n)) Filter.atTop

/-- 命题一（分解存在）：任一有限基底在给定规则与粗化策略下存在局部规范的合法分解。

[101:52]「所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。」 -/
def DecompExistsSpec {P : Type u} [LinearOrder P] (r : BlockRule.{u}) (dir : CoarseDirPolicy P) :
    Prop :=
  ∀ base : AltSeq P, Nonempty (LocalCanonicalDecomp r dir base)

/-- 命题二（规范唯一）：任意两个局部规范分解逐层切点相同。

[101:56]「本ID理论最牛的地方，就是把仿佛毫无头绪的股票走势，给出了唯一分解定理，也就是走势必完美，这等于引进理想数，使得代数数论升堂入室一样牛。」
[102:14]「如果是单纯地唯一分解，并不能显示本ID理论真正厉害之处，因为走势必完美对应的是一种最特殊、最强有力的唯一分解，这看似毫无规律的市场走势竟然有这样完美的整体结构，这才是最牛的地方。」 -/
def CanonicalUniqueSpec {P : Type u} [LinearOrder P] (r : BlockRule.{u})
    (dir : CoarseDirPolicy P) : Prop :=
  ∀ (base : AltSeq P) (a b : LocalCanonicalDecomp r dir base), a.val.sameCuts b.val

/-- 命题三（有界活性下终结）：满足显式活性谓词的路径上，任一未完成状态在 `bound` 步内完成或升级。

[069:28]「其实，本ID的理论的关键不是什么中枢、走势类型，而是走势必完美，这才是本ID理论的核心。但要真正理解这个关键，可不是看字面意思就能明白的。」 -/
def BoundedTerminationSpec {A : Type*} (live : InfPath A → Prop) (pending done : History A → Prop)
    (bound : ℕ) : Prop :=
  ∀ x : InfPath A, live x → ∀ n, pending (prefixOf x n) →
    ∃ m, n ≤ m ∧ m ≤ n + bound ∧ done (prefixOf x m)

/-- 命题四（弱安全性）：买点之后若在时刻 `m` 前形成同级中枢，则其间存在价格不低于买入价的时刻；不宣称操作上的绝对安全。

[107:22]「显然，没有任何绝对性可以保障上下上中，最后一个上一定有比第一个上有更高的高点，特别那种所谓奔走型的反弹，后上的高点可能只刚好触及前上的低点，因此，如果你一定要等上下上都完成才抛出，那很可能面对这样的尴尬，就是你在第一个上的最低点买的，在上下上的电梯过后，你只有一个可能连手续费都不够、稍纵即逝的卖点。因此，这种操作，注定是只有相对的理论上的绝对安全性，而没有具体操作上的绝对安全性。」
[017:60]「因为上涨和盘整必然要在图形上完成，而上涨和盘整在图形上的要求，是必须包含三个以上的次级别运动，因此后面必须还至少有一个向上的次级别运动，这样的买点是绝对安全的，其安全性由走势的“不患”而保证，这，就是在前面反复强调的第二类买点。」 -/
def WeakSafetySpec {P : Type*} [LinearOrder P] (buyAt : InfPath P → ℕ → Prop)
    (centerAfter : InfPath P → ℕ → ℕ → Prop) : Prop :=
  ∀ (x : InfPath P) (t : ℕ), buyAt x t → ∀ m, centerAfter x t m →
    ∃ s, t < s ∧ s ≤ m ∧ x t ≤ x s

end Chan.Defs.Limits
