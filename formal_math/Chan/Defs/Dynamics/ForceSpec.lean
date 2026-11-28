module

public import Chan.Defs.Dynamics.Potential

/-!
# M16c 综合力度接口与读数层不变性

四个显式参数（窗口、势函数、读法、端点约定）全部无默认值。
价格平移不变性与正仿射等变性挂在读数层（对完整读数 `evalForce` 陈述），不强加于势函数。
-/

@[expose] public section

namespace Chan.Defs.Dynamics

open Chan.Defs.Alt

/-- 读法：端点差或正变差。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
inductive ReadingKind where
  /-- 末值减首值。 -/
  | endpointDiff
  /-- 相邻增量正部之和。 -/
  | posVar

/-- 端点约定：`interiorOnly` 只取窗口内时刻 `[first, last]`；`leftClosed` 把前驱终点
`first - 1` 并入左端（保相邻窗口可加性）；`fromRest` 在窗口前置零参考值。

[061:26]「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
inductive EndpointConv where
  /-- 带前驱终点的左闭约定。 -/
  | leftClosed
  /-- 纯窗口内约定。 -/
  | interiorOnly
  /-- 从静止起算约定。 -/
  | fromRest

/-- 力度三分量（势函数、读法、端点约定），全部无默认值。

[072:28]「本ID的理论，本质上分两部分，一是形态学，二是动力学，当然三就是两者的结合。」 -/
structure ForceRecipe (R : Type*) where
  /-- 势函数。 -/
  potential : CausalPotential R
  /-- 读法。 -/
  reading : ReadingKind
  /-- 端点约定。 -/
  endpoint : EndpointConv

/-- 综合力度接口：窗口、势函数、读法、端点约定四参数，全部无默认值。

[033:34]「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
structure ForceSpec (R : Type*) extends ForceRecipe R where
  /-- 比较窗口。 -/
  window : ForceWindow

/-- 三分量配上窗口得到综合力度接口。

[061:26]「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
def ForceRecipe.withWindow {R : Type*} (rc : ForceRecipe R) (w : ForceWindow) : ForceSpec R :=
  { toForceRecipe := rc, window := w }

/-- 比较开关：严格小于，或不大于（相等也算减弱）。

[二级旁证 051:246]「不一定要缩小，不大于就可以，而且深圳那边明显变小，对照一下就更能确定了。1分钟以下级别的背驰，反抽到1分钟以下级别的中枢里，这当然被理论所保证。」 -/
inductive ForceCompareMode where
  /-- 严格小于。 -/
  | strictLt
  /-- 不大于。 -/
  | notGreater

variable {R : Type*} [Field R] [LinearOrder R] [IsStrictOrderedRing R]

/-- 有限列的端点差（空列为零）。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def listEndpointDiff (l : List R) : R := l.getLastD 0 - l.headD 0

/-- 有限列的正变差。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def listPosVar (l : List R) : R := ((l.zip l.tail).map fun p => max (p.2 - p.1) 0).sum

/-- 按读法从取样列提取标量。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def ReadingKind.read (k : ReadingKind) (l : List R) : R :=
  match k with
  | .endpointDiff => listEndpointDiff l
  | .posVar => listPosVar l

/-- 按端点约定在跨度上取样势函数值。

[061:26]「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
def EndpointConv.sample (conv : EndpointConv) (v : ℕ → R) (sp : Span) : List R :=
  let inner := (List.range (sp.last + 1 - sp.first)).map fun i => v (sp.first + i)
  match conv with
  | .interiorOnly => inner
  | .leftClosed => v (sp.first - 1) :: inner
  | .fromRest => 0 :: inner

/-- 多空定向：向上原样，向下取负，使两侧都量“顺向”力度。

[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def orient (d : Dir) (x : ℕ → R) : ℕ → R :=
  match d with
  | .up => x
  | .down => fun t => -x t

/-- 在给定历史、方向与窗口一侧上评估力度。

[033:34]「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
def evalForce (spec : ForceSpec R) (d : Dir) (x : ℕ → R) (side : WindowSide) : R :=
  spec.reading.read (spec.endpoint.sample (spec.potential.phi (orient d x)) (spec.window.span side))

/-- 读数层的价格平移不变性：对任意窗口，历史整体平移不改变完整读数。

[072:40]「所谓形态学、动力学，其实很好分辨，任何涉及背驰的，都是动力学的范围，背驰是动力学的基本点之一。另外，中枢、走势的能量结构之类的东西，也属于动力学。而形态学，就是中枢、走势类型、笔、线段之类的东西。」 -/
def ReadingShiftInvariant (rc : ForceRecipe R) : Prop :=
  ∀ (w : ForceWindow) (d : Dir) (x : ℕ → R) (c : R) (side : WindowSide),
    evalForce (rc.withWindow w) d (fun t => x t + c) side = evalForce (rc.withWindow w) d x side

/-- 读数层的正仿射等变性：`x ↦ a * x + b`（`0 < a`）使读数乘 `a`。

[104:18]「现代物理的一个核心概念，就是物理与几何的高度统一。」 -/
def PositiveAffineEquiv (rc : ForceRecipe R) : Prop :=
  ∀ (w : ForceWindow) (d : Dir) (x : ℕ → R) (a b : R) (side : WindowSide), 0 < a →
    evalForce (rc.withWindow w) d (fun t => a * x t + b) side =
      a * evalForce (rc.withWindow w) d x side

/-- 按开关比较两标量。

[二级旁证 051:246]「不一定要缩小，不大于就可以，而且深圳那边明显变小，对照一下就更能确定了。1分钟以下级别的背驰，反抽到1分钟以下级别的中枢里，这当然被理论所保证。」 -/
def ForceCompareMode.cmp (m : ForceCompareMode) (a b : R) : Prop :=
  match m with
  | .strictLt => a < b
  | .notGreater => a ≤ b

/-- 力度减弱：窗口后段读数按开关弱于前段读数。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def forceWeaker (spec : ForceSpec R) (m : ForceCompareMode) (d : Dir) (x : ℕ → R) : Prop :=
  m.cmp (evalForce spec d x .after) (evalForce spec d x .before)

end Chan.Defs.Dynamics
