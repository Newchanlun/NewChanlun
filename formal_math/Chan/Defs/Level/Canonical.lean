module

public import Chan.Defs.Level.Tower

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Alt
variable {P : Type _} [LinearOrder P] {r : BlockRule} {dir : CoarseDirPolicy P} {base : AltSeq P}

/-- 同一底层可有多条合法切点链；逐层检查每对相邻切点划出的连续块属于块语言。
[057:40] 当行情走到6点时，34、45、56这三段，就可以看成是一个1分钟中枢了，当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。 -/
def ValidDecomp (t : LevelTower r dir base) : Bool :=
  match t.stages? with
  | none => false
  | some (levels, _) => levels.zipIdx.all fun entry =>
    let (stage, cuts) := entry.1
    (cuts.zip cuts.tail).zipIdx.all fun p =>
      (r.rank entry.2 stage.items (cuts.take p.2).reverse p.1.1 p.1.2).isSome

/-- 固定基底、规则和方向策略时，合法性只由各层切点决定。 -/
theorem validDecomp_eq_of_sameCuts (a b : LevelTower r dir base)
    (h : a.sameCuts b) : ValidDecomp a = ValidDecomp b := by
  unfold LevelTower.sameCuts at h
  unfold ValidDecomp LevelTower.stages?
  rw [h]

/-- 规范要求每层按规则择优、局部定尾且穷尽；最高层也不能再从起点成块。
[038:18] 显然，一个好的分解，其分解规则下，必须保证分解的唯一性，否则这种分解就绝对不可能是好的分解。
[099:26] 如果后面包括d+e+f延伸出9段，然后又直接上去了，划分中，必须首先保证5分钟中枢的成立。换言之，划分的原则很明确，就是必须保证中枢的确立，在这前提下，可以根据结合律，使得连接中枢的走势保持最完美的形态。 -/
def IsLocalCanonical (t : LevelTower r dir base) : Bool :=
  match t.stages? with
  | none => false
  | some (levels, top) =>
    levels.zipIdx.all (fun entry =>
      DeterministicBlocks r entry.2 entry.1.1.items entry.1.2) &&
      (List.range top.items.length).all
        (fun i => (r.ends levels.length top.items [] i).isEmpty)

/-- 固定基底、规则和方向策略时，局部规范性也只由各层切点决定。 -/
theorem isLocalCanonical_eq_of_sameCuts (a b : LevelTower r dir base)
    (h : a.sameCuts b) : IsLocalCanonical a = IsLocalCanonical b := by
  unfold LevelTower.sameCuts at h
  unfold IsLocalCanonical LevelTower.stages?
  rw [h]

/-- 默认规范是局部声明；全局结合律偏好由 #2296（needs-fable）另定。

[038:18] 显然，一个好的分解，其分解规则下，必须保证分解的唯一性，否则这种分解就绝对不可能是好的分解。
[099:22] 另外，根据结合律，连接中枢的走势，并不一定是完全的趋势类型，也就是说，一个线段类上涨后，可能第二类类中枢就消融在中阴状态的那个中枢里了。也就是说，a+b+c+d+e+f= a+b+c+（d+e+f），a+b+c+d+e是一个线段类上涨，c+d+e的重合部分构成最后的一个类中枢，f是类背驰后的回调，这时候，就可以马上构成一个1分钟的中枢，然后后面直接继续上涨，构成1分钟的上涨是完全合理的。因为，最终的划分，就必须把a+b+c+d+e给拆开了。
-/
abbrev IsCanonical (t : LevelTower r dir base) : Bool := IsLocalCanonical t

/-- 全局规范：塔合法，且在合法分解中没有严格更优者；偏好关系由调用方提供。

[099:26] 如果后面包括d+e+f延伸出9段，然后又直接上去了，划分中，必须首先保证5分钟中枢的成立。换言之，划分的原则很明确，就是必须保证中枢的确立，在这前提下，可以根据结合律，使得连接中枢的走势保持最完美的形态。
-/
def IsGlobalCanonical (pref : LevelTower r dir base → LevelTower r dir base → Prop)
    (t : LevelTower r dir base) : Prop :=
  ValidDecomp t = true ∧ ∀ other, ValidDecomp other = true → ¬ pref other t

/-- 合法且满足调用方所选声明式规范的塔。
[038:18] 显然，一个好的分解，其分解规则下，必须保证分解的唯一性，否则这种分解就绝对不可能是好的分解。
[101:52] 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。 -/
abbrev CanonicalDecomp (r : BlockRule) (dir : CoarseDirPolicy P) (base : AltSeq P)
    (canon : LevelTower r dir base → Prop) :=
  { t : LevelTower r dir base // ValidDecomp t = true ∧ canon t }

/-- 以逐层局部占优和尾部穷尽为规范的合法分解。 -/
abbrev LocalCanonicalDecomp (r : BlockRule) (dir : CoarseDirPolicy P) (base : AltSeq P) :=
  CanonicalDecomp r dir base (fun t => IsLocalCanonical t = true)

end Chan.Defs.Level
