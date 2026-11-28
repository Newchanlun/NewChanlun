module

public import Chan.Proxy.Ema

/-!
# M16a 精确核代理层：MACD 三件与柱组读法

`dif = ema_fast - ema_slow`，`dea = ema_sig(dif)`，`hist = 2 * (dif - dea)`。
无系数版本 `histRaw = dif - dea` 与系数 2 版本满足 `hist = 2 * histRaw`（按定义）；
标准配置下核常数口径 `56 = (9 - 1) * (26 - 12) / 2` 按无系数版本计。
-/

@[expose] public section

namespace Chan.Proxy

/-- MACD 参数：短周期、长周期、信号周期与两处播种方式；标准配置 `(12, 26, 9)` 不写死在通用定义里。

[025:16]「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
structure MacdParams where
  /-- 短周期。 -/
  fast : ℕ
  /-- 长周期。 -/
  slow : ℕ
  /-- 信号周期。 -/
  sig : ℕ
  /-- 短周期正性。 -/
  fast_pos : 0 < fast
  /-- 短周期严格小于长周期。 -/
  fast_lt_slow : fast < slow
  /-- 信号周期正性。 -/
  sig_pos : 0 < sig
  /-- 两条价格均线的播种方式。 -/
  seed : EmaSeed
  /-- 信号线的播种方式。 -/
  sigSeed : EmaSeed

/-- 标准参数 `(12, 26, 9)`，播种方式仍须显式给出。

[025:16]「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
def MacdParams.standard (seed sigSeed : EmaSeed) : MacdParams where
  fast := 12
  slow := 26
  sig := 9
  fast_pos := by decide
  fast_lt_slow := by decide
  sig_pos := by decide
  seed := seed
  sigSeed := sigSeed

/-- 短周期均线参数。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def MacdParams.fastEma (p : MacdParams) : EmaParams := ⟨p.fast, p.fast_pos, p.seed⟩

/-- 长周期均线参数。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def MacdParams.slowEma (p : MacdParams) : EmaParams :=
  ⟨p.slow, Nat.lt_trans p.fast_pos p.fast_lt_slow, p.seed⟩

/-- 信号线参数。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def MacdParams.sigEma (p : MacdParams) : EmaParams := ⟨p.sig, p.sig_pos, p.sigSeed⟩

/-- MACD 单点三分量：`dif`、`dea` 与柱值 `hist`（系数 2 版本）。

[103:22]「就一个最简单MACD指标，0轴分为多空主导，也就是说，一旦MACD指标陷入0轴之下，那么就在对应时间单位的图表下进入空头主导，而这是必须远离的。」 -/
structure MacdPoint where
  /-- 快慢均线差。 -/
  dif : ℚ
  /-- `dif` 的信号均线。 -/
  dea : ℚ
  /-- 柱值 `2 * (dif - dea)`。 -/
  hist : ℚ

/-- 无系数柱值 `dif - dea`，与 `hist` 相差因子 2。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def MacdPoint.histRaw (m : MacdPoint) : ℚ := m.dif - m.dea

/-- `dif` 序列。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def difSeq (p : MacdParams) (x : ℕ → ℚ) (t : ℕ) : ℚ :=
  emaSeq p.fastEma x t - emaSeq p.slowEma x t

/-- `dea` 序列（`dif` 的信号均线，其核为两次卷积，零轴界须单独表述）。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def deaSeq (p : MacdParams) (x : ℕ → ℚ) : ℕ → ℚ :=
  emaSeq p.sigEma (difSeq p x)

/-- MACD 序列。

[103:22]「就一个最简单MACD指标，0轴分为多空主导，也就是说，一旦MACD指标陷入0轴之下，那么就在对应时间单位的图表下进入空头主导，而这是必须远离的。」 -/
def macdSeq (p : MacdParams) (x : ℕ → ℚ) (t : ℕ) : MacdPoint where
  dif := difSeq p x t
  dea := deaSeq p x t
  hist := 2 * (difSeq p x t - deaSeq p x t)

/-- 闭窗口 `[s, e]` 上的带号和。

[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def signedSum (h : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e + 1 - s)) fun i => h (s + i)

/-- 闭窗口 `[s, e]` 上的红柱和（正部和）。

[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def posSum (h : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e + 1 - s)) fun i => max (h (s + i)) 0

/-- 闭窗口 `[s, e]` 上的绿柱和（负部绝对值和）。

[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def negSum (h : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e + 1 - s)) fun i => max (-h (s + i)) 0

/-- 闭窗口 `[s, e]` 上的绝对值和。

[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def absSum (h : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e + 1 - s)) fun i => abs (h (s + i))

/-- 闭窗口 `[s, e]` 上的离散正变差。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def posVar (h : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e - s)) fun i => max (h (s + i + 1) - h (s + i)) 0

/-- 闭窗口 `[s, e]` 上的离散负变差。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def negVar (h : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e - s)) fun i => max (h (s + i) - h (s + i + 1)) 0

/-- 闭窗口 `[s, e]` 上的离散全变差。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def totalVar (h : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e - s)) fun i => abs (h (s + i + 1) - h (s + i))

/-- 闭窗口 `[s, e]` 上的端点差。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def endpointDiff (h : ℕ → ℚ) (s e : ℕ) : ℚ := h e - h s

/-- 精确零轴回拉界命题（只针对标准参数下的 `DIF`，是待检陈述而非已断言事实）：
最近 `n` 根在价格带内、更早价格与显式初值到价格带的距离不超过 `delta` 时，
`|DIF t| ≤ A * R + (q_26^n - q_12^n) * delta`。

[103:22]「就一个最简单MACD指标，0轴分为多空主导，也就是说，一旦MACD指标陷入0轴之下，那么就在对应时间单位的图表下进入空头主导，而这是必须远离的。」 -/
def ZeroAxisBoundData.DifClaim (d : ZeroAxisBoundData) (seed sigSeed : EmaSeed)
    (x : ℕ → ℚ) : Prop :=
  d.RecentInBand x → d.EarlierWithinDelta x → d.SeedWithinDelta seed →
    abs (difSeq (MacdParams.standard seed sigSeed) x d.t) ≤ d.bound

end Chan.Proxy
