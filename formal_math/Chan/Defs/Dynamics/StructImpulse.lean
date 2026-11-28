module

public import Chan.Defs.Dynamics.ForceSpec
public import Chan.Defs.Alt.Zigzag

/-!
# M16b 结构冲量族

段斜率由折线端点位移除以来源跨度时长给出；三类端点读数 `L_in`、`L_pre`、`L_zero`
与从静止起算族并列，不设主线默认实例（默认值留待 FM-42 裁定）。
-/

@[expose] public section

namespace Chan.Defs.Dynamics

open Chan.Defs.Alt

/-- 从静止起算族的两种读法：正变差或末态速度。

[104:26]「而本ID的理论，本质上是站在这种现代物理的角度构建自己的能量动力学结构的。这里，一切都是几何结构说了算，一切的能量动力形态，都变几何化，因此，必须有这种思维上的根本改变，才会有真正的理解。否则，还是牛顿时代那种弱智思维，那就将陷入一种机械化思维的陷阱中。」 -/
inductive FromRestMode where
  /-- 自零速度起算的正变差。 -/
  | posVar
  /-- 末态速度。 -/
  | terminalVelocity

variable {R : Type*} [Field R] [LinearOrder R] [IsStrictOrderedRing R]

/-- 段的来源跨度时长（原始坐标步数）。

[072:40]「所谓形态学、动力学，其实很好分辨，任何涉及背驰的，都是动力学的范围，背驰是动力学的基本点之一。另外，中枢、走势的能量结构之类的东西，也属于动力学。而形态学，就是中枢、走势类型、笔、线段之类的东西。」 -/
def segDuration (s : Seg R) : ℕ := s.source.last - s.source.first

/-- 时间跨度正性条件：只有在此条件下段斜率才是有意义的均速。

[072:40]「所谓形态学、动力学，其实很好分辨，任何涉及背驰的，都是动力学的范围，背驰是动力学的基本点之一。另外，中枢、走势的能量结构之类的东西，也属于动力学。而形态学，就是中枢、走势类型、笔、线段之类的东西。」 -/
def SegPosDuration (s : Seg R) : Prop := s.source.first < s.source.last

/-- 单段离散斜率（带方向符号的均速）：折线终点减起点，除以来源跨度时长；时长为零时按域约定取零，须配合 `SegPosDuration` 使用。

[104:26]「而本ID的理论，本质上是站在这种现代物理的角度构建自己的能量动力学结构的。这里，一切都是几何结构说了算，一切的能量动力形态，都变几何化，因此，必须有这种思维上的根本改变，才会有真正的理解。否则，还是牛顿时代那种弱智思维，那就将陷入一种机械化思维的陷阱中。」 -/
def segSlope (s : Seg R) : R := (s.zigEnd - s.zigStart) / ((segDuration s : ℕ) : R)

/-- 纯段内读数 `L_in`：只依赖窗口内各段的速度列。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def impulseIn (k : ReadingKind) (ws : List (Seg R)) : R := k.read (ws.map segSlope)

/-- 带前驱读数 `L_pre`：速度列前置窗口起始前一段，以保持相邻窗口可加性。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def impulsePre (k : ReadingKind) (pre : Seg R) (ws : List (Seg R)) : R :=
  k.read ((pre :: ws).map segSlope)

/-- 从参考速度起算读数 `L_zero`：速度列前置显式参考速度 `v0`（零或中枢尺度基准速度）。

[033:34]「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
def impulseZero (k : ReadingKind) (v0 : R) (ws : List (Seg R)) : R :=
  k.read (v0 :: ws.map segSlope)

/-- 从静止起算族：正变差或末态速度，由调用方显式选择，不设默认实例。

[033:34]「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
def impulseFromRest (m : FromRestMode) (ws : List (Seg R)) : R :=
  match m with
  | .posVar => listPosVar ((0 : R) :: ws.map segSlope)
  | .terminalVelocity => (ws.map segSlope).getLastD 0

end Chan.Defs.Dynamics
