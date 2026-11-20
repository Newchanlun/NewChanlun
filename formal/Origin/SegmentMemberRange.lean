import Origin.CenterConstruction
import Origin.SegmentConstruction

/-! #1486：第 78 课标准化构造 `segOfMembers` 的区间读数等于成员笔极值。 -/

namespace NewChanlun.Origin

theorem segHigh_segOfMembers (dir : Direction) (first : Stroke) (rest : List Stroke) :
    segHigh (segOfMembers dir first rest) = memberHigh first rest := by
  have h := memberLow_le_memberHigh first rest
  cases dir <;> simp only [segOfMembers, segHigh] <;> split <;> simp only [Tick] at * <;> omega

theorem segLow_segOfMembers (dir : Direction) (first : Stroke) (rest : List Stroke) :
    segLow (segOfMembers dir first rest) = memberLow first rest := by
  have h := memberLow_le_memberHigh first rest
  cases dir <;> simp only [segOfMembers, segLow] <;> split <;> simp only [Tick] at * <;> omega

end NewChanlun.Origin
