module

public import Chan.Defs.Level.Rule

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Alt
variable {P : Type _} [Std.LinearOrderPackage P]

/-- 当前层段列和对应的底层原始边界；层内下标不冒充原始切点。
[102:38] 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式 -/
structure Stage (P : Type _) [Std.LinearOrderPackage P] where
  seq : AltSeq P
  raw : List Nat

/-- 底层每一项占一个原始位置，末边界为长度。
[053:20] 但无论这些显微镜如何转换，一个原则是不变的，就是当你用一个级别的显微镜时，就等于先把次级别的当成线段了，也就是说次级别不在该级别的观察中。 -/
def Stage.bottom (s : AltSeq P) : Stage P := ⟨s, List.range (s.items.length+1)⟩

/-- 把上层原始切点还原为本层位置；只接受已有边界，每两个边界粗化成一个实际段。
[057:40] 当行情走到6点时，34、45、56这三段，就可以看成是一个1分钟中枢了，当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。 -/
def Stage.ascend (s : Stage P) (raw : List Nat) : Option (List Nat × Stage P) := do
  if raw.length < 2 || !(raw.all (fun j => s.raw.contains j)) then none else
    let localCuts := raw.map (fun j => s.raw.idxOf j)
    let blocks ← (localCuts.zip localCuts.tail).mapM fun p =>
      BlockRule.coarsen s.seq.items p.1 p.2
    if h : ∀ i : Fin blocks.length, ∀ j : Fin blocks.length,
        j.val = i.val + 1 → blocks[i.val].dir ≠ blocks[j.val].dir then
      some (localCuts, ⟨⟨blocks, h⟩, raw⟩)
    else none

/-- 逐层还原，保留供块语言检查的本层切点；空表表示没有更高的完成层。
[101:52] 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。 -/
def realize (s : Stage P) : List (List Nat) → Option (List (Stage P × List Nat) × Stage P)
  | [] => some ([], s)
  | row :: rows => do
      let (cuts, upper) ← s.ascend row
      let (levels, top) ← realize upper rows
      some ((s,cuts) :: levels, top)

/-- 给定基底和规则的几何塔；证书保证每次粗化可还原，块语言合法性另由 ValidDecomp 判断。
[101:52] 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。
[053:20] 但无论这些显微镜如何转换，一个原则是不变的，就是当你用一个级别的显微镜时，就等于先把次级别的当成线段了，也就是说次级别不在该级别的观察中。 -/
structure LevelTower (rule : BlockRule) (base : AltSeq P) where
  partition : NestedCuts base.items.length
  realized : (realize (Stage.bottom base) (partition.rows.map CutChain.marks)).isSome = true

/-- 由低到高提取原始下标；各层均使用同一底层坐标。
[102:38] 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式 -/
def LevelTower.cuts {r : BlockRule} {base : AltSeq P} (t : LevelTower r base) :=
  t.partition.rows.map CutChain.marks

/-- 同底同规则逐行比较，不比较粗化证书。
[057:40] 当行情走到6点时，34、45、56这三段，就可以看成是一个1分钟中枢了，当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。
[101:52] 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。 -/
abbrev LevelTower.sameCuts {r : BlockRule} {base : AltSeq P} (a b : LevelTower r base) : Prop :=
  a.cuts = b.cuts

end Chan.Defs.Level
