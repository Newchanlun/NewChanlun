import Origin.CenterConstruction

/-! #1486：给既有段区间读法提供第 78 课标准化的线段输入。

[旧缠论] `docs/chanlun/text/blog/078-第78课.md:58`【正文】：
「都可以把该线段标准化为最高低点都在端点」。
`:60`【正文】：「所有向上线段都是以最低点开始最高点结束，向下线段都是以最高点开始最低点结束」。
[新缠论:选择] #1419 L3（见 #1486）据此取已确定的成员笔端价极值，不把几何分段端点价
用作区间。下面的构造保留首末笔的索引，只标准化端价。
-/

namespace NewChanlun.Origin

private def memberPrices (first : Stroke) (rest : List Stroke) : List Tick :=
  first.startPrice :: first.endPrice :: rest.flatMap (fun s => [s.startPrice, s.endPrice])

def memberLow (first : Stroke) (rest : List Stroke) : Tick :=
  (memberPrices first rest).min (by simp [memberPrices])

def memberHigh (first : Stroke) (rest : List Stroke) : Tick :=
  (memberPrices first rest).max (by simp [memberPrices])

private theorem memberLow_le_memberHigh (first : Stroke) (rest : List Stroke) :
    memberLow first rest ≤ memberHigh first rest := by
  have h : first.startPrice ∈ memberPrices first rest := by simp [memberPrices]
  exact Int.le_trans (List.min_le_of_mem h) (List.le_max_of_mem h)

/-- 构造前提：成员已由分段判据确定且非空；Segment 的端点价是第 78 课
    标准化后的方向极值。向上段为低→高，向下段为高→低。 -/
def segOfMembers (dir : Direction) (first : Stroke) (rest : List Stroke) : Segment :=
  let lo := memberLow first rest
  let hi := memberHigh first rest
  let (startPrice, endPrice) := match dir with
    | .up => (lo, hi)
    | .down => (hi, lo)
  { direction := dir
    startIndex := first.startIndex
    endIndex := (rest.getLastD first).endIndex
    startPrice, endPrice }

theorem segHigh_segOfMembers (dir : Direction) (first : Stroke) (rest : List Stroke) :
    segHigh (segOfMembers dir first rest) = memberHigh first rest := by
  have h := memberLow_le_memberHigh first rest
  cases dir <;> simp only [segOfMembers, segHigh] <;> split <;> simp only [Tick] at * <;> omega

theorem segLow_segOfMembers (dir : Direction) (first : Stroke) (rest : List Stroke) :
    segLow (segOfMembers dir first rest) = memberLow first rest := by
  have h := memberLow_le_memberHigh first rest
  cases dir <;> simp only [segOfMembers, segLow] <;> split <;> simp only [Tick] at * <;> omega

end NewChanlun.Origin
