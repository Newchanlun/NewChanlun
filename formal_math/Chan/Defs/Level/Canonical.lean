module

public import Chan.Defs.Level.Tower

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Alt
variable {P : Type _} [Std.LinearOrderPackage P] {r : BlockRule} {base : AltSeq P}

/-- 同一底层可有多条合法切点链；逐层检查每对相邻切点划出的连续块属于块语言。
[057:40] 当行情走到6点时，34、45、56这三段，就可以看成是一个1分钟中枢了，当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。 -/
def ValidDecomp (t : LevelTower r base) : Bool :=
  match realize (Stage.bottom base) t.cuts with
  | none => false
  | some (levels, _) => levels.zipIdx.all fun entry =>
    let (stage, cuts) := entry.1
    (cuts.zip cuts.tail).zipIdx.all fun p =>
      (r.rank entry.2 stage.seq.items (cuts.take p.2).reverse p.1.1 p.1.2).isSome

/-- 规范要求每层按规则择优、局部定尾且穷尽；最高层也不能再从起点成块。
[038:18] 显然，一个好的分解，其分解规则下，必须保证分解的唯一性，否则这种分解就绝对不可能是好的分解。
[099:26] 如果后面包括d+e+f延伸出9段，然后又直接上去了，划分中，必须首先保证5分钟中枢的成立。换言之，划分的原则很明确，就是必须保证中枢的确立，在这前提下，可以根据结合律，使得连接中枢的走势保持最完美的形态。 -/
def IsCanonical (t : LevelTower r base) : Bool :=
  match realize (Stage.bottom base) t.cuts with
  | none => false
  | some (levels, top) =>
    levels.zipIdx.all (fun entry =>
      DeterministicBlocks r entry.2 entry.1.1.seq.items entry.1.2) &&
      (r.ends levels.length top.seq.items [] 0).isEmpty

/-- 合法且满足声明式规范的塔；没有把唯一性写成某个算法的输出。
[038:18] 显然，一个好的分解，其分解规则下，必须保证分解的唯一性，否则这种分解就绝对不可能是好的分解。
[101:52] 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。 -/
abbrev CanonicalDecomp (r : BlockRule) (base : AltSeq P) :=
  { t : LevelTower r base // ValidDecomp t = true ∧ IsCanonical t = true }

end Chan.Defs.Level
