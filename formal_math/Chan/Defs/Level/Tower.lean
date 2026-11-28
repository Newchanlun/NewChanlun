module

public import Chan.Defs.Level.Rule

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Alt
variable {P : Type _} [LinearOrder P]

/-- 当前层段列和对应的底层原始边界；层内下标不冒充原始切点。
[102:38] 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式 -/
structure Stage (P : Type _) [LinearOrder P] where
  items : List (Seg P)
  raw : List Nat

/-- 底层每一项占一个原始位置，末边界为长度。
[053:20] 但无论这些显微镜如何转换，一个原则是不变的，就是当你用一个级别的显微镜时，就等于先把次级别的当成线段了，也就是说次级别不在该级别的观察中。 -/
def Stage.bottom (s : AltSeq P) : Stage P := ⟨s.items, List.range (s.items.length+1)⟩

/-- 把上层原始切点还原为本层位置；只接受已有边界，每两个边界粗化成一个实际段。
[057:40] 当行情走到6点时，34、45、56这三段，就可以看成是一个1分钟中枢了，当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。 -/
def Stage.ascend (s : Stage P) (dir : CoarseDirPolicy) (raw : List Nat) : Option (List Nat × Stage P) := do
  if raw.length < 2 || !(raw.all (fun j => s.raw.contains j)) then none else
    let localCuts := raw.map (fun j => s.raw.idxOf j)
    let blocks ← (localCuts.zip localCuts.tail).mapM fun p =>
      BlockRule.coarsen s.items p.1 p.2 dir
    some (localCuts, ⟨blocks, raw⟩)

/-- 逐层还原，保留供块语言检查的本层切点；空表表示没有更高的完成层。
[101:52] 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。 -/
def realize (dir : CoarseDirPolicy) (s : Stage P) : List (List Nat) → Option (List (Stage P × List Nat) × Stage P)
  | [] => some ([], s)
  | row :: rows => do
      let (cuts, upper) ← s.ascend dir row
      let (levels, top) ← realize dir upper rows
      some ((s,cuts) :: levels, top)

/-- 固定基底、规则和粗化方向策略的几何塔。证书保证各层可还原；块语言合法性另查。
[101:52] 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。
[053:20] 但无论这些显微镜如何转换，一个原则是不变的，就是当你用一个级别的显微镜时，就等于先把次级别的当成线段了，也就是说次级别不在该级别的观察中。 -/
structure LevelTower (rule : BlockRule) (dir : CoarseDirPolicy) (base : AltSeq P) where
  partition : NestedCuts base.items.length
  anchored : ∀ row ∈ partition.rows, row.anchoredZero
  realized : (realize dir (Stage.bottom base) (partition.rows.map CutChain.marks)).isSome = true

variable {r : BlockRule} {dir : CoarseDirPolicy} {base : AltSeq P}

/-- 由低到高提取原始下标；各层均使用同一底层坐标。
[102:38] 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式 -/
def LevelTower.cuts (t : LevelTower r dir base) :=
  t.partition.rows.map CutChain.marks

/-- 在固定基底、规则和方向策略下逐行比较切点，不比较粗化证书。
[057:40] 当行情走到6点时，34、45、56这三段，就可以看成是一个1分钟中枢了，当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。
[101:52] 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。 -/
abbrev LevelTower.sameCuts (a b : LevelTower r dir base) : Prop :=
  a.cuts = b.cuts

/-- 复用塔的粗化策略和原始切点，还原每层段表与局部切点。 -/
def LevelTower.stages? (t : LevelTower r dir base) :=
  realize dir (Stage.bottom base) t.cuts

/-- 原始右开边界左侧底层段的方向；边界 0 及越界没有收笔。 -/
def closingDirBefore? (base : AltSeq P) (stop : Nat) : Option Dir :=
  match stop with
  | 0 => none
  | n + 1 => base.items[n]?.map Seg.dir

/-- 取指定层、指定段的收笔方向。深度 0 直接读底层段，其余深度读该层原始切点行。
待证：`seam_alternates`（前块收笔与后块起笔相反）；
`strict_alternates_iff_odd_blocks`（严格交替等价于每个非末块含奇数个底层段）。 -/
def LevelTower.closingDir? (t : LevelTower r dir base) (depth i : Nat) : Option Dir := do
  match depth with
  | 0 => base.items[i]?.map Seg.dir
  | n + 1 =>
    let row ← t.cuts[n]?
    let stop ← row[i+1]?
    closingDirBefore? base stop

end Chan.Defs.Level
