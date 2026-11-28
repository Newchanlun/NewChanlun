module

public import Chan.Proxy.Ema
public import Mathlib.Algebra.BigOperators.Group.Finset.Basic

@[expose] public section

namespace Chan.Proxy

/-- 三个正周期；在快慢线的命名中，快线的周期严格短于慢线。
[025:16] 「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
structure MacdParams where
  fast : ℕ+
  slow : ℕ+
  signal : ℕ+
  fast_lt_slow : fast < slow
  fastSeed : EmaSeed
  slowSeed : EmaSeed
  sigSeed : EmaSeed
  deriving DecidableEq

/-- 标准首值播种构造器：三条均线各取各自输入的首值。
[025:16] 「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
def MacdParams.firstValue (fast slow signal : ℕ+) (ordered : fast < slow) : MacdParams :=
  ⟨fast, slow, signal, ordered, .firstValue, .firstValue, .firstValue⟩

/-- 双线之差、差线的信号均线、带倍数 2 的柱高。无倍数口径的柱高是 `hist / 2`。
[024:24] 「而C 段的走势类型完成时对应的MACD 柱子面积（向上的看红柱子，向下看绿柱子）比A 段对应的面积要小，这时候就构成标准的背弛。」 -/
structure MacdPoint where
  dif : ℚ
  dea : ℚ
  hist : ℚ
  deriving DecidableEq

/-- 独立播种快、慢、信号三线；DEA 的输入是当时的 DIF。
标准 `(12, 26, 9)` 下，倍柱核常数为 56，无系数版为 28。
[025:16] 「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
def macdSeq (p : MacdParams) (price : ℕ → ℚ) (t : ℕ) : MacdPoint :=
  let pf := EmaParams.ofPeriod p.fast p.fastSeed
  let ps := EmaParams.ofPeriod p.slow p.slowSeed
  let pd := EmaParams.ofPeriod p.signal p.sigSeed
  let update (params : EmaParams) (old new : ℚ) :=
    (1 - params.alpha) * old + params.alpha * new
  let f0 := pf.init (price 0)
  let s0 := ps.init (price 0)
  let step (k : ℕ) (state : ℚ × ℚ × ℚ) : ℚ × ℚ × ℚ :=
    let fast := update pf state.1 (price (k + 1))
    let slow := update ps state.2.1 (price (k + 1))
    (fast, slow, update pd state.2.2 (fast - slow))
  let (fast, slow, dea) := Nat.rec (f0, s0, pd.init (f0 - s0)) step t
  let dif := fast - slow
  ⟨dif, dea, 2 * (dif - dea)⟩

/-- 闭窗口 `[s,e]` 内各根柱的带号和；反向窗口为空。MACD 输入可取 `fun t => (m t).hist`。
[024:24] 「而C 段的走势类型完成时对应的MACD 柱子面积（向上的看红柱子，向下看绿柱子）比A 段对应的面积要小，这时候就构成标准的背弛。」 -/
def signedSum (bars : ℕ → ℚ) (s e : ℕ) : ℚ :=
  (Finset.range (e + 1 - s)).sum fun i => bars (s + i)

/-- 仅累加闭窗口中红柱的高度。
[024:24] 「而C 段的走势类型完成时对应的MACD 柱子面积（向上的看红柱子，向下看绿柱子）比A 段对应的面积要小，这时候就构成标准的背弛。」 -/
def posSum (bars : ℕ → ℚ) (s e : ℕ) : ℚ :=
  signedSum (fun t => max (bars t) 0) s e

/-- 仅累加闭窗口中绿柱的深度，读数非负。
[024:24] 「而C 段的走势类型完成时对应的MACD 柱子面积（向上的看红柱子，向下看绿柱子）比A 段对应的面积要小，这时候就构成标准的背弛。」 -/
def negSum (bars : ℕ → ℚ) (s e : ℕ) : ℚ :=
  signedSum (fun t => max (-bars t) 0) s e

/-- 各根柱不分颜色，取绝对值后相加。
[024:24] 「而C 段的走势类型完成时对应的MACD 柱子面积（向上的看红柱子，向下看绿柱子）比A 段对应的面积要小，这时候就构成标准的背弛。」 -/
def absSum (bars : ℕ → ℚ) (s e : ℕ) : ℚ :=
  signedSum (fun t => |bars t|) s e

/-- 只计两个端点都在窗口内的相邻增量，累加其正部。
[025:16] 「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def posVar (x : ℕ → ℚ) (s e : ℕ) : ℚ :=
  (Finset.range (e - s)).sum fun i => max (x (s + i + 1) - x (s + i)) 0

/-- 与正变差使用同一批相邻增量，累加负部的绝对值。
[025:16] 「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def negVar (x : ℕ → ℚ) (s e : ℕ) : ℚ :=
  posVar (fun t => -x t) s e

/-- 离散全变差等于窗口内上行变差与下行变差之和。
[025:16] 「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def totalVar (x : ℕ → ℚ) (s e : ℕ) : ℚ :=
  posVar x s e + negVar x s e

/-- 末值减初值。反向窗口不含增量，读数为零。
[025:16] 「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def endpointDiff (x : ℕ → ℚ) (s e : ℕ) : ℚ :=
  if s ≤ e then x e - x s else 0

end Chan.Proxy
