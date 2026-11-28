module

public import Chan.Defs.Level.Tower

@[expose] public section

namespace Chan.Defs.Level

open Chan.Defs.Order Chan.Defs.Alt Chan.Defs.Center
variable {P : Type _} [LinearOrder P]

/-- 完成走势的三个形态，不含预测状态。
[017:44] 缠中说禅盘整：在任何级别的任何走势中，某完成的走势类型只包含一个缠中说禅走势中枢，就称为该级别的缠中说禅盘整。
[017:46] 缠中说禅趋势：在任何级别的任何走势中，某完成的走势类型至少包含两个以上依次同向的缠中说禅走势中枢，就称为该级别的缠中说禅趋势。 -/
inductive TrendKind where
  | consolidation | uptrend | downtrend
  deriving DecidableEq

/-- 形态取多空对偶：盘整不变，上涨与下跌互换。
[017:46] 缠中说禅趋势：在任何级别的任何走势中，某完成的走势类型至少包含两个以上依次同向的缠中说禅走势中枢，就称为该级别的缠中说禅趋势。 -/
def TrendKind.dual : TrendKind → TrendKind
  | .consolidation => .consolidation
  | .uptrend => .downtrend
  | .downtrend => .uptrend

/-- 某一合法划分选择的完成块及其同级中枢。各核按时间不交，数据来自原段；不能漏掉与所有已选中枢都不交的成核三段。
[017:56] “缠中说禅走势分解定理一”：任何级别的任何走势，都可以分解成同级别“盘整”、“下跌”与“上涨”三种走势类型的连接。
[057:40] 当行情走到6点时，34、45、56这三段，就可以看成是一个1分钟中枢了，当然，这种分法和原来[4087，4122]中枢的分解不同，但站在多义性的角度，这是绝对符合结合律的，当然是一个分解的方法。 -/
structure Finished (xs : List (Seg P)) where
  first : Nat
  stop : Nat
  bounded : first < stop ∧ stop ≤ xs.length
  centers : List (Center P)
  inside : ∀ z ∈ centers, first ≤ z.start ∧ z.stop ≤ stop ∧ xs.extract z.start z.stop = z.cover
  ordered : centers.Pairwise (fun a b => a.stop ≤ b.start)
  accounted : ∀ i ∈ List.range stop, first ≤ i → i+3 ≤ stop → CanSeedCenter xs i = true →
    centers.any (fun z => decide (i < z.stop ∧ z.start < i+3)) = true
  deriving DecidableEq

/-- 一个中枢为盘整；两个以上逐对比较整个波动区间。零个、相触或方向混杂都不能冒称趋势。
[017:44] 缠中说禅盘整：在任何级别的任何走势中，某完成的走势类型只包含一个缠中说禅走势中枢，就称为该级别的缠中说禅盘整。
[017:46] 缠中说禅趋势：在任何级别的任何走势中，某完成的走势类型至少包含两个以上依次同向的缠中说禅走势中枢，就称为该级别的缠中说禅趋势。
[020:58] 缠中说禅走势中枢中心定理二：前后同级别的两个缠中说禅走势中枢，后GG<前DD，等价于下跌及其延续；后DD>前GG等价于上涨及其延续。后ZG<前ZD且后GG>=前DD，或后ZD>前ZG且后DD=<前GG，则等价于形成高级别的走势中枢。
[二级旁证 106:186] 二、不大规范地的，就是直接从该中枢第三类买点扩展成更大级别的反弹。这等于标准的下跌走势a+A+b+B+c中的c不出现，读过课程的都知道，只要有A和B，a、c不出现不改变下跌的性质，趋势与盘整在于中枢数量，这是最基本的常识。
-/
def classifyTrend {xs : List (Seg P)} (b : Finished xs) : Option TrendKind :=
  match b.centers with
  | [] => none
  | [_] => some .consolidation
  | _ :: _ :: _ =>
    let pairs := b.centers.zip b.centers.tail
    if pairs.all (fun p => decide (gapUp p.1.zone.hull p.2.zone.hull)) then some .uptrend
    else if pairs.all (fun p => decide (gapDown p.1.zone.hull p.2.zone.hull)) then some .downtrend
    else none

/-- 第一枢后的三类事件须有实际顺向推进；直到观察边界，回试以来的各段都不得再触核。
[107:32] 有人喜欢精确定义，那么这里其实也给出了什么是上升趋势形成的最精确定义，就是在第一中枢后出现第三类买点并形成非背驰类向上。
[054:24] 当走势发展到d2时，一个1分钟级别的中枢就形成，区间是[d1,g1]。后面出现的线段，就要以该区间来决定是中枢震荡还是第三类买卖点。由于d1=g2，那么d2g2这段就属于[d1,g1]中枢的震荡。而到d3g3这段，显然已经不能触及[d1,g1]，所以g3就是第三类卖点。当然，如果前面d1>g2，那g2就是第三类卖点了。 -/
def TrendFormingProspect (xs : List (Seg P)) (centers : List (Center P)) (d : Dir) (atCut : Nat) : Bool :=
  match centers with
  | [z] =>
    match z.departureIndex? d (xs.take atCut) with
    | none => false
    | some k =>
      let follow := xs.extract (k+2) atCut
      decide (atCut ≤ xs.length) &&
        (follow.all fun x => match d with
          | .up => decide (z.leavesUp x)
          | .down => decide (z.leavesDown x)) &&
        match xs[k]? with
        | none => false
        | some leave => follow.any fun x => decide (x.dir = d) &&
            match d with
            | .up => decide (leave.range.hi < x.range.hi)
            | .down => decide (x.range.lo < leave.range.lo)
  | _ => false

end Chan.Defs.Level
