module

public import Chan.Defs.Center.Center

/-!
# M9 走势类型

形态学只按同级中枢个数分类（清单 B-22）：盘整恰 1 个；趋势至少 2 个且相邻中枢波动区间
依次严格分离；进入段 a 与离开段 c 可缺省。前瞻谓词单列，不进形态学主定义；
走势类型定义不暗含必然升级（清单 B-23）。
-/

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Order Chan.Defs.Alt Chan.Defs.Center

universe u

/-- 走势类型三态：盘整、上涨趋势、下跌趋势。

[017:56]
> “缠中说禅走势分解定理一”：任何级别的任何走势，都可以分解成同级别“盘整”、“下跌”与“上涨”三种走势类型的连接。
-/
inductive TrendKind where
  /-- 盘整。 -/
  | consolidation
  /-- 上涨趋势。 -/
  | upTrend
  /-- 下跌趋势。 -/
  | downTrend
  deriving DecidableEq

variable {P : Type u} [LinearOrder P]

/-- 仅按同级中枢序列分类：0 个无类型；1 个为盘整；至少 2 个且相邻波动区间依次严格向上
（后 `DD >` 前 `GG`）为上涨，依次严格向下（后 `GG <` 前 `DD`）为下跌；否则不是单一本级走势类型。
a、c 段不参与分类，可缺省。

[017:44]
> 缠中说禅盘整：在任何级别的任何走势中，某完成的走势类型只包含一个缠中说禅走势中枢，就称为该级别的缠中说禅盘整。

[017:46]
> 缠中说禅趋势：在任何级别的任何走势中，某完成的走势类型至少包含两个以上依次同向的缠中说禅走势中枢，就称为该级别的缠中说禅趋势。

[二级旁证 106:186]
> 只要有A和B，a、c不出现不改变下跌的性质，趋势与盘整在于中枢数量，这是最基本的常识。
-/
def classifyTrend : List (Center P) → Option TrendKind
  | [] => none
  | [_] => some TrendKind.consolidation
  | c₁ :: c₂ :: rest =>
    if (∀ q ∈ List.zip (c₁ :: c₂ :: rest) (c₂ :: rest), q.1.gg < q.2.dd) then
      some TrendKind.upTrend
    else if (∀ q ∈ List.zip (c₁ :: c₂ :: rest) (c₂ :: rest), q.2.gg < q.1.dd) then
      some TrendKind.downTrend
    else none

/-- 单列前瞻谓词（趋势形成中）：`c` 是段序列中的第一个中枢，其覆盖末段 `k` 与紧接段 `k+1`
构成第三类事件（方向 `d`），且此后各段均不再回到核内。剥离 `107:32` 的非背驰动力学条件。

[107:32]
> 有人喜欢精确定义，那么这里其实也给出了什么是上升趋势形成的最精确定义，就是在第一中枢后出现第三类买点并形成非背驰类向上。
-/
def TrendFormingProspect (d : Dir) (segs : List (Seg P)) (c : Center P) (k : Nat) : Prop :=
  c.WellFormed segs ∧ (∀ k' ∈ List.range c.first, seedAtB segs k' = false) ∧
  k + 1 = c.first + c.count ∧
  ((d = Dir.up ∧ c.thirdBuyAt segs k = true ∧ ∀ s ∈ List.drop (k + 2) segs, c.zg < s.range.lo) ∨
   (d = Dir.down ∧ c.thirdSellAt segs k = true ∧ ∀ s ∈ List.drop (k + 2) segs, s.range.hi < c.zd))

/-- `TrendFormingProspect` 可判定。

[107:32]
> 有人喜欢精确定义，那么这里其实也给出了什么是上升趋势形成的最精确定义，就是在第一中枢后出现第三类买点并形成非背驰类向上。
-/
instance instDecidableTrendFormingProspect (d : Dir) (segs : List (Seg P)) (c : Center P)
    (k : Nat) : Decidable (TrendFormingProspect d segs c k) := by
  unfold TrendFormingProspect; infer_instance

end Chan.Defs.Level
