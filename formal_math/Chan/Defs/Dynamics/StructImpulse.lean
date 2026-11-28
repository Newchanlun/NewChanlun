module

public import Chan.Defs.Dynamics.ForceSpec

@[expose] public section

namespace Chan.Defs.Dynamics

open Chan.Defs.Alt Chan.Defs.Signal

/-- 单位时间取相邻原始样本的间距。用实际出入价之差除以历时，不把区间极值当成端点。
[033:34] 「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
def segSlope (s : Seg ℚ) (p : DirectedEndpoints s) (_elapsed : s.source.first < s.source.last) : ℚ :=
  (p.exit - p.entry) / ((s.source.last - s.source.first : Nat) : ℚ)

/-- 可测速的一个结构段：有实际端点，且两个时间戳不同。
[104:18] 「现代物理的一个核心概念，就是物理与几何的高度统一。」 -/
structure ImpulseLeg where
  seg : Seg ℚ
  prices : DirectedEndpoints seg
  elapsed : seg.source.first < seg.source.last

/-- 以原始闭跨度判相邻：共用转折样本或占用相接的两组样本；相邻底段方向交替。
[104:26] 「而本ID的理论，本质上是站在这种现代物理的角度构建自己的能量动力学结构的。这里，一切都是几何结构说了算，一切的能量动力形态，都变几何化，因此，必须有这种思维上的根本改变，才会有真正的理解。否则，还是牛顿时代那种弱智思维，那就将陷入一种机械化思维的陷阱中。」 -/
abbrev ImpulseLeg.followedBy (a b : ImpulseLeg) : Prop :=
  a.seg.dir ≠ b.seg.dir ∧
    (a.seg.source.last = b.seg.source.first ∨ a.seg.source.last + 1 = b.seg.source.first)

/-- 非空连续段窗。起点之前的速度不属于这个窗口。
[061:26] 「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
structure ImpulseWindow where
  first : ImpulseLeg
  rest : List ImpulseLeg
  connected : (first :: rest).IsChain ImpulseLeg.followedBy

/-- 先按实测端点计算带号速度，再投到本次比较的方向。
[033:34] 「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
def ImpulseLeg.speedAlong (leg : ImpulseLeg) (side : Dir) : ℚ :=
  orientValue side (segSlope leg.seg leg.prices leg.elapsed)

/-- L_in 只读窗内的速度变化；只有一段时，两个内部读法均读零。
[104:26] 「而本ID的理论，本质上是站在这种现代物理的角度构建自己的能量动力学结构的。这里，一切都是几何结构说了算，一切的能量动力形态，都变几何化，因此，必须有这种思维上的根本改变，才会有真正的理解。否则，还是牛顿时代那种弱智思维，那就将陷入一种机械化思维的陷阱中。」 -/
def impulseIn (kind : ReadingKind) (side : Dir) (w : ImpulseWindow) : ℚ :=
  readSamples kind (w.first.speedAlong side) (w.rest.map (·.speedAlong side))

/-- L_pre 把紧邻前驱到窗首的速度变化分配给本窗；前驱必须真实相邻。
[104:26] 「而本ID的理论，本质上是站在这种现代物理的角度构建自己的能量动力学结构的。这里，一切都是几何结构说了算，一切的能量动力形态，都变几何化，因此，必须有这种思维上的根本改变，才会有真正的理解。否则，还是牛顿时代那种弱智思维，那就将陷入一种机械化思维的陷阱中。」 -/
def impulsePre (kind : ReadingKind) (side : Dir) (prev : ImpulseLeg) (w : ImpulseWindow)
    (_adjacent : prev.followedBy w.first) : ℚ :=
  readSamples kind (prev.speedAlong side) ((w.first :: w.rest).map (·.speedAlong side))

/-- L_zero 在首段前插入已投到比较方向的基准速度 `v0`；取零得到静止参考态。
[033:34] 「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
def impulseZero (kind : ReadingKind) (side : Dir) (v0 : ℚ) (w : ImpulseWindow) : ℚ :=
  readSamples kind v0 ((w.first :: w.rest).map (·.speedAlong side))

/-- 同一静止参考下并列保留末态速度与正变差。窗口中途有回吐时，两者可以不同。
[033:34] 「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
structure RestImpulseReadings where
  terminalSpeed : ℚ
  positiveVariation : ℚ
  deriving DecidableEq

/-- #2322 U-8：同时取出从静止起算的两项读数。速度冲量族是 FM-42 证明期的主攻口径，
不是默认值；末态速度与正变差并行检验。
[033:26] 「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def impulseFromRest (side : Dir) (w : ImpulseWindow) : RestImpulseReadings :=
  ⟨impulseZero .endpointDiff side 0 w, impulseZero .posVar side 0 w⟩

end Chan.Defs.Dynamics
