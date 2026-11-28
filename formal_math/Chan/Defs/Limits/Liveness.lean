module

public import Chan.Defs.Level.Canonical
public import Chan.Defs.Path.History
public import Chan.Defs.Signal.Phase
public import Mathlib.Order.Filter.AtTopBot.Basic
public import Mathlib.Order.Filter.EventuallyConst

@[expose] public section

namespace Chan.Defs.Limits

open Chan.Defs.Alt Chan.Defs.Level Chan.Defs.Path Chan.Defs.Signal

universe u
variable {P : Type u} {V : Type*}

/-- 无限路径按成交时间顺序取值，从时刻零起算。
[030:16] 而本ID的理论，当然也是以这交易时间的不可逆为前提，如果今天的交易可以变成昨天的或者干脆不算了，那本ID的理论马上土崩瓦解。 -/
abbrev InfPath (P : Type*) := Nat → P

/-- 前 `n` 个观测对应半开时间段 `[0,n)`。空前缀不含零时刻的价格。
[030:16] 而本ID的理论，当然也是以这交易时间的不可逆为前提，如果今天的交易可以变成昨天的或者干脆不算了，那本ID的理论马上土崩瓦解。 -/
def prefixOf (x : InfPath P) (n : Nat) : History P :=
  List.ofFn (fun i : Fin n => x i.val)

/-- 柱集可观测：性质一旦为真，总有一个有限前缀能作证，任何共享此前缀的延拓也为真。
[二级旁证 105:442] 另外，由于大多数人的科学与哲学知识都很贫乏，容易被人唬住，本ID给大家一个最简单的判别标准，就是可观察量。现代科学最基本的概念不是其他，而是可观察量，任何在科学的范围内谈论的东西，必须是可观察的。因此，那一切涉及非可观察量的玩意都是可疑的，例如什么宇宙的无穷，事件的无穷，神秘的自然规律，上帝的启示，辨证唯物主义或这主义那非主义的规律所引发的所谓宇宙规律等等。 -/
def PrefixObservable (property : InfPath P → Prop) : Prop :=
  ∀ x, property x → ∃ n, ∀ y, prefixOf y n = prefixOf x n → property y

/-- 依次把更长前缀交给同一读数器；最终常值并不要求在首次取到该值时就能确认。
[102:38] 而级别的存在，一个必然的结论就是，任何高级别的改变都必须先从低级别开始。例如，绝对不可能出现5分钟从下跌转折为上涨，而1分钟还在下跌段中。 -/
def EventuallyStable (readout : History P → V) (x : InfPath P) : Prop :=
  Filter.EventuallyConst (fun n => readout (prefixOf x n)) Filter.atTop

variable [LinearOrder P]

/-- B-24（存在）：抽取器把有限价格历史变为底层段列；合法规则下须能给出合法塔。
[101:52] 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。 -/
def DecompExistsSpec (rule : BlockRule.{u}) (dir : CoarseDirPolicy P)
    (extractBase : History P → AltSeq P) : Prop :=
  InterfaceLaws rule → ∀ h, ∃ t : LevelTower rule dir (extractBase h), ValidDecomp t = true

/-- B-24（规范唯一）：在同一历史、规则与方向策略下，有一座满足指定规范的合法塔，
且所有这样的塔具有相同切点。
[101:56] 本ID理论最牛的地方，就是把仿佛毫无头绪的股票走势，给出了唯一分解定理，也就是走势必完美，这等于引进理想数，使得代数数论升堂入室一样牛。 -/
def CanonicalUniqueSpec (rule : BlockRule.{u}) (dir : CoarseDirPolicy P)
    (extractBase : History P → AltSeq P)
    (canonical : (h : History P) → LevelTower rule dir (extractBase h) → Prop) : Prop :=
  InterfaceLaws rule → ∀ h, ∃ a : CanonicalDecomp rule dir (extractBase h) (canonical h),
    ∀ b : CanonicalDecomp rule dir (extractBase h) (canonical h), a.val.sameCuts b.val

/-- 从已到达的历史取指定层的分解。账本自身记录的规则和层深必须与查询一致。
[101:52] 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。 -/
abbrev StageReader (P : Type u) [LinearOrder P] (rule : BlockRule.{u}) :=
  (depth : Nat) → History P → {d : Decomposition P // d.rule = rule ∧ d.depth = depth}

/-- B-24（有界终结）：在指定活性条件下，当前未完成的同一对象须在给定期限内完成或升级。
`id` 是跨前缀、跨级别不变的对象标识；升级要在严格更高级别的账本上认出该对象。
[017:60] 因为某种类型的走势完成以后就会转化为其他类型的走势，对于下跌的走势来说，一旦完成，只能转化为上涨与盘整，因此，一旦能把握下跌走势转化的关节点买入，就在市场中占据了一个最有利的位置，而这个买点，就是前面反复强调的“第一类买点”； -/
def BoundedTerminationSpec {Id : Type*} (rule : BlockRule.{u}) (readStage : StageReader P rule)
    (live : InfPath P → Prop) (bound : Nat)
    (pending complete promoted : Id → Decomposition P → Prop) : Prop :=
  ∀ x, live x → ∀ n depth id, pending id (readStage depth (prefixOf x n)).val →
    ∃ m, n < m ∧ m ≤ n + bound ∧
      (complete id (readStage depth (prefixOf x m)).val ∨
       ∃ higher, depth < higher ∧ promoted id (readStage higher (prefixOf x m)).val)

/-- B-24（弱安全）：买点以当时的分解判读。其后若形成同级中枢，买入后至少一次可达买价；
等价亦计，不计费用，不把买入时刻本身当卖出机会。
[107:22] 显然，没有任何绝对性可以保障上下上中，最后一个上一定有比第一个上有更高的高点，特别那种所谓奔走型的反弹，后上的高点可能只刚好触及前上的低点，因此，如果你一定要等上下上都完成才抛出，那很可能面对这样的尴尬，就是你在第一个上的最低点买的，在上下上的电梯过后，你只有一个可能连手续费都不够、稍纵即逝的卖点。因此，这种操作，注定是只有相对的理论上的绝对安全性，而没有具体操作上的绝对安全性。 -/
def WeakSafetySpec (rule : BlockRule.{u}) (readStage : StageReader P rule)
    (buyNow : Decomposition P → Prop) : Prop :=
  ∀ (x : InfPath P) (depth buy t : Nat), buy < t →
    buyNow (readStage depth (prefixOf x (buy+1))).val →
    (∃ z ∈ (readStage depth (prefixOf x (t+1))).val.ledger.centers,
      buy < z.c.source.last ∧ z.c.source.last ≤ t) →
    ∃ exitTime, buy < exitTime ∧ x buy ≤ x exitTime

end Chan.Defs.Limits
