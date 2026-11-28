module

public import Chan.Defs.Dynamics.Potential

@[expose] public section

namespace Chan.Defs.Dynamics

open Chan.Defs.Alt

/-- 端点差保留回吐；正变差只累计沿比较方向的正向增量。
[033:34] 「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
inductive ReadingKind where
  | endpointDiff | posVar
  deriving DecidableEq

/-- 内部读法只取两端都在窗内的增量；另两种分别把真实前驱或零参考接在窗首之前。
[061:26] 「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
inductive EndpointConv where
  | interiorOnly | withPredecessor | fromRest
  deriving DecidableEq

/-- 先选择一对窗口、一种势、一种读法及一套端点约定，两段共享后三者。
[033:26] 「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
structure ForceSpec where
  window : ForceWindow
  potential : CausalPotential
  reading : ReadingKind
  endpoint : EndpointConv

/-- 固定势、读法与端点约定；比较窗口由分解另行提供。
[061:26] 「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
structure ForceRecipe where
  potential : CausalPotential
  reading : ReadingKind
  endpoint : EndpointConv

/-- 为配方指定合法窗口，不改变力度读法。
[061:26] 「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
def ForceRecipe.atWindow (recipe : ForceRecipe) (window : ForceWindow) : ForceSpec :=
  ⟨window, recipe.potential, recipe.reading, recipe.endpoint⟩

/-- 在同一窗口对中选择前段或后段，避免将层内段号误作价格下标。
[024:22] 「用MACD 判断背驰，首先要有两段同向的趋势。同向趋势之间一定有一个盘整或反向趋势连接，把这三段分别称为A、B、C 段。」 -/
inductive ForceLeg where
  | earlier | later
  deriving DecidableEq

/-- 把势或速度投到比较方向：多头取原值，空头取反号，然后才计算正变差。
[024:24] 「而C 段的走势类型完成时对应的MACD 柱子面积（向上的看红柱子，向下看绿柱子）比A 段对应的面积要小，这时候就构成标准的背弛。」 -/
def orientValue (side : Dir) (x : ℚ) : ℚ :=
  match side with | .up => x | .down => -x

/-- 非空采样列的读数。端点差取末值减首值；正变差逐对累加正部，单点两者均为零。
[033:34] 「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
def readSamples (kind : ReadingKind) (first : ℚ) (rest : List ℚ) : ℚ :=
  match kind with
  | .endpointDiff => rest.getLastD first - first
  | .posVar => (rest.foldl (fun (st : ℚ × ℚ) x => (x, st.2 + max (x - st.1) 0)) (first, 0)).2

/-- 在原始价格坐标上观察所选闭窗。每个势值只看至该点为止的历史；
窗尾未到或约定需要但没有前驱时返回无值，不以零替代。
[061:26] 「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
def evalForce (spec : ForceSpec) (h : List ℚ) (side : Dir) (leg : ForceLeg) : Option ℚ := do
  let w := match leg with | .earlier => spec.window.earlier | .later => spec.window.later
  if w.last ≥ h.length then none else
    let value := fun t x => orientValue side (spec.potential.sample (h.take t) x)
    let points := (h.extract w.first (w.last + 1)).mapIdx (fun i x => value (w.first + i) x)
    match points with
    | [] => none
    | first :: rest =>
      match spec.endpoint with
      | .interiorOnly => some (readSamples spec.reading first rest)
      | .fromRest => some (readSamples spec.reading 0 points)
      | .withPredecessor =>
        if w.first = 0 then none else
          let prev := w.first - 1
          let x ← h[prev]?
          some (readSamples spec.reading (value prev x) points)

/-- 对配方的每一合法比较窗，整体平移价格不改变力度读数；无需势本身平移不变。
[072:34] 「动力学，是属于物理范畴的，但站在更高的层次上看物理，物理的本质就是几何，当然，这是所有物理学家都不可能认同的，但如果用一些几何结构就可以把所有物理的常量给搞掂，那物理学家不认同也是白搭。同样道理，本ID理论里的动力学部分，本质上也是几何，只是这种几何比较特别，需要把价格充分有效市场里的非完全绝对趋同交易作为前提转化为某些几何结构，然后构造出理论的证明来。」 -/
def ReadingShiftInvariant (recipe : ForceRecipe) : Prop :=
  ∀ w h side leg (b : ℚ),
    evalForce (recipe.atWindow w) (h.map (· + b)) side leg =
      evalForce (recipe.atWindow w) h side leg

/-- 对配方的每一合法比较窗，正仿射换价按比例缩放读数且不改变其定义域。
[072:34] 「动力学，是属于物理范畴的，但站在更高的层次上看物理，物理的本质就是几何，当然，这是所有物理学家都不可能认同的，但如果用一些几何结构就可以把所有物理的常量给搞掂，那物理学家不认同也是白搭。同样道理，本ID理论里的动力学部分，本质上也是几何，只是这种几何比较特别，需要把价格充分有效市场里的非完全绝对趋同交易作为前提转化为某些几何结构，然后构造出理论的证明来。」 -/
def PositiveAffineEquiv (recipe : ForceRecipe) : Prop :=
  ∀ w (a b : ℚ), 0 < a → ∀ h side leg,
    evalForce (recipe.atWindow w) (h.map (fun x => a * x + b)) side leg =
      (evalForce (recipe.atWindow w) h side leg).map (a * ·)

/-- 同时镜像价格并互换比较方向，检验两侧读数是否相同。
[033:26] 「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def ReadingMirrorSymmetric (spec : ForceSpec) : Prop :=
  ∀ h side leg, evalForce spec (h.map Neg.neg) side.flip leg = evalForce spec h side leg

/-- 相等是否算减弱由调用方选择；两种比较各自独立。
[033:26] 「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」
[二级旁证 051:246] 「不一定要缩小，不大于就可以，而且深圳那边明显变小，对照一下就更能确定了。1分钟以下级别的背驰，反抽到1分钟以下级别的中枢里，这当然被理论所保证。」 -/
inductive ForceCompareMode where
  | strict | nonStrict
  deriving DecidableEq

/-- 用同一把尺量前后两段。未取得两个读数时不能报告力度减弱。
[033:26] 「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」
[二级旁证 051:246] 「不一定要缩小，不大于就可以，而且深圳那边明显变小，对照一下就更能确定了。1分钟以下级别的背驰，反抽到1分钟以下级别的中枢里，这当然被理论所保证。」 -/
def forceWeaker (mode : ForceCompareMode) (spec : ForceSpec) (h : List ℚ) (side : Dir) : Bool :=
  match evalForce spec h side .earlier, evalForce spec h side .later with
  | some a, some b => match mode with
    | .strict => decide (b < a)
    | .nonStrict => decide (b ≤ a)
  | _, _ => false

end Chan.Defs.Dynamics
