module

public import Chan.Defs.Signal.Phase
public import Mathlib.Algebra.Order.Ring.Rat

@[expose] public section

namespace Chan.Defs.Dynamics

open Chan.Defs.Alt Chan.Defs.Order Chan.Defs.Signal

/-- 所选分解中两个同向比较段的原始闭跨度（可共用转接点）。锚是可选的中枢核，不是价格样本。
[061:26] 要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。 -/
structure ForceWindow where
  earlier : Span
  later : Span
  anchor : Option (Bar ℚ)
  ordered : earlier.last ≤ later.first
  deriving DecidableEq

/-- 按段号从同一分解取比较对；指定锚时也从同级账本取核。越界、异向或错序无窗口。
[033:26] 对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。 -/
def ForceWindow.ofDecomp? (d : Decomposition ℚ) (i j : Nat) (center? : Option Nat) :
    Option ForceWindow := do
  let a ← d.steps[i]?
  let b ← d.steps[j]?
  if i ≥ j || a.dir != b.dir then none else
    let anchor ← match center? with
      | none => some none
      | some k => (d.ledger.centers[k]?).map (fun z => some z.core)
    if h : a.source.last ≤ b.source.first then some ⟨a.source, b.source, anchor, h⟩ else none

/-- 在时刻 t 只给出严格过去的 t 个样本及当下成交价。旧时刻求值不会见到后续价格；
绝对价位本身也可以是势。
[二级旁证 105:442] 另外，由于大多数人的科学与哲学知识都很贫乏，容易被人唬住，本ID给大家一个最简单的判别标准，就是可观察量。现代科学最基本的概念不是其他，而是可观察量，任何在科学的范围内谈论的东西，必须是可观察的。因此，那一切涉及非可观察量的玩意都是可疑的，例如什么宇宙的无穷，事件的无穷，神秘的自然规律，上帝的启示，辨证唯物主义或这主义那非主义的规律所引发的所谓宇宙规律等等。 -/
structure CausalPotential where
  sample : List ℚ → ℚ → ℚ

/-- 全历史与现价同比例放大时，势值也按该正比例放大。
[050:18] 必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。 -/
def PosHomogeneous (v : CausalPotential) : Prop :=
  ∀ a : ℚ, 0 < a → ∀ past x, v.sample (past.map (a * ·)) (a * x) = a * v.sample past x

/-- 整条价格历史镜像后势值反号；这是可单独检验的性质。
[033:26] 所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。 -/
def MirrorAntiSym (v : CausalPotential) : Prop :=
  ∀ past x, v.sample (past.map Neg.neg) (-x) = -v.sample past x

end Chan.Defs.Dynamics
