module

public import Mathlib.Data.List.Basic

@[expose] public section

namespace Chan.Defs.Path

variable {A B : Type*}

/-- 截至当前的有限输入，按到达次序排列。
[099:22] 另外，根据结合律，连接中枢的走势，并不一定是完全的趋势类型，也就是说，一个线段类上涨后，可能第二类类中枢就消融在中阴状态的那个中枢里了。也就是说，a+b+c+d+e+f= a+b+c+（d+e+f），a+b+c+d+e是一个线段类上涨，c+d+e的重合部分构成最后的一个类中枢，f是类背驰后的回调，这时候，就可以马上构成一个1分钟的中枢，然后后面直接继续上涨，构成1分钟的上涨是完全合理的。因为，最终的划分，就必须把a+b+c+d+e给拆开了。 -/
abbrev History (A : Type*) := List A

/-- 延拓只向历史末尾追加输入。
[099:22] 另外，根据结合律，连接中枢的走势，并不一定是完全的趋势类型，也就是说，一个线段类上涨后，可能第二类类中枢就消融在中阴状态的那个中枢里了。也就是说，a+b+c+d+e+f= a+b+c+（d+e+f），a+b+c+d+e是一个线段类上涨，c+d+e的重合部分构成最后的一个类中枢，f是类背驰后的回调，这时候，就可以马上构成一个1分钟的中枢，然后后面直接继续上涨，构成1分钟的上涨是完全合理的。因为，最终的划分，就必须把a+b+c+d+e给拆开了。 -/
abbrev IsPrefix (h t : History A) : Prop := h.IsPrefix t

/-- 用无重复有限表精确呈现可能值：每项都有见证，每个可能值都在表内。
[099:16] 有人可能认为，中阴存在是理论不完善的结果，其实，这是典型的一根筋思维，对于这种思维，世界就是机械的，任何时候都只有一个机械精确的结果，而实际上，世界更多是量子化的，是测不准的，中阴的存在恰好客观地反映了走势的这种特性。 -/
class FiniteImage {B : Type*} (possible : B → Prop) where
  values : List B
  unique : values.Nodup
  exactImage : ∀ b, b ∈ values ↔ possible b

/-- 指定历史与合法延拓条件；候选包括且只包括至少能在一条合法延拓上实现的结果。
[099:16] 有人可能认为，中阴存在是理论不完善的结果，其实，这是典型的一根筋思维，对于这种思维，世界就是机械的，任何时候都只有一个机械精确的结果，而实际上，世界更多是量子化的，是测不准的，中阴的存在恰好客观地反映了走势的这种特性。 -/
abbrev PendingCandidates (f : History A → B) (h : History A) (legal : History A → Prop) :=
  FiniteImage (fun b => ∃ tail, legal (h ++ tail) ∧ f (h ++ tail) = b)

/-- 针对一个输出位置观察；删除可编码为无值。精确像把对全部有限延拓的量化化为有限判定。
[099:22] 另外，根据结合律，连接中枢的走势，并不一定是完全的趋势类型，也就是说，一个线段类上涨后，可能第二类类中枢就消融在中阴状态的那个中枢里了。也就是说，a+b+c+d+e+f= a+b+c+（d+e+f），a+b+c+d+e是一个线段类上涨，c+d+e的重合部分构成最后的一个类中枢，f是类背驰后的回调，这时候，就可以马上构成一个1分钟的中枢，然后后面直接继续上涨，构成1分钟的上涨是完全合理的。因为，最终的划分，就必须把a+b+c+d+e给拆开了。 -/
def Confirmed (f : History A → B) (h : History A) : Prop :=
  ∀ tail, f (h ++ tail) = f h

/-- 有限候选的逐项判定等价于检验所有有限延拓。
[099:16] 有人可能认为，中阴存在是理论不完善的结果，其实，这是典型的一根筋思维，对于这种思维，世界就是机械的，任何时候都只有一个机械精确的结果，而实际上，世界更多是量子化的，是测不准的，中阴的存在恰好客观地反映了走势的这种特性。 -/
instance [DecidableEq B] (f : History A → B) (h : History A)
    [future : PendingCandidates f h (fun _ => True)] : Decidable (Confirmed f h) :=
  decidable_of_iff (∀ b ∈ future.values, b = f h) ⟨by
    intro check tail
    exact check _ ((future.exactImage _).mpr ⟨tail, trivial, rfl⟩), by
    intro stable b hb
    obtain ⟨tail, _, rfl⟩ := (future.exactImage b).mp hb
    exact stable tail⟩

/-- 位置从零起算。展望 k 步后，任何更长历史与截到 i+k 的前缀都须给出同一结果。
[102:38] 而级别的存在，一个必然的结论就是，任何高级别的改变都必须先从低级别开始。例如，绝对不可能出现5分钟从下跌转折为上涨，而1分钟还在下跌段中。 -/
def DelayedCausal (f : History A → Nat → B) (k : Nat) : Prop :=
  ∀ h i, i + k < h.length → f (h.take (i+k+1)) i = f h i

/-- 若可达的截短、未截短观测值对有精确有限表，逐对比较就能决定延迟律。
[102:38] 也就是说，任何走势，都可以唯一地表示为a1A1+a5A5+a30A30的形式 -/
instance [DecidableEq B] (f : History A → Nat → B) (k : Nat)
    [observed : FiniteImage (fun p : B × B => ∃ (h : History A) (i : Nat),
      i + k < h.length ∧ p = (f (h.take (i+k+1)) i, f h i))] : Decidable (DelayedCausal f k) :=
  decidable_of_iff (∀ p ∈ observed.values, p.1 = p.2) ⟨by
    intro check h i hi
    exact check _ ((observed.exactImage _).mpr ⟨h,i,hi,rfl⟩), by
    intro stable p hp
    obtain ⟨h,i,hi,rfl⟩ := (observed.exactImage p).mp hp
    exact stable h i hi⟩

/-- 无限观察的有限再现谱：列出任意晚仍能出现的值，并给出尾部最终只取这些值的保证。
[099:16] 有人可能认为，中阴存在是理论不完善的结果，其实，这是典型的一根筋思维，对于这种思维，世界就是机械的，任何时候都只有一个机械精确的结果，而实际上，世界更多是量子化的，是测不准的，中阴的存在恰好客观地反映了走势的这种特性。 -/
class TailSpectrum {B : Type*} (observe : Nat → B) where
  recurrent : FiniteImage (fun b => ∀ n, ∃ m, n ≤ m ∧ observe m = b)
  confined : ∃ n, ∀ m, n ≤ m → observe m ∈ recurrent.values

/-- 沿给定无限延拓取逐步加长的前缀。精确再现谱内只有指定值，即最终稳定于该值。
[099:16] 有人可能认为，中阴存在是理论不完善的结果，其实，这是典型的一根筋思维，对于这种思维，世界就是机械的，任何时候都只有一个机械精确的结果，而实际上，世界更多是量子化的，是测不准的，中阴的存在恰好客观地反映了走势的这种特性。 -/
def LimitStable (f : History A → B) (stream : Nat → A) (value : B) : Prop :=
  ∃ n, ∀ m, n ≤ m → f (List.ofFn (fun i : Fin m => stream i.val)) = value

/-- 已知尾部再现谱时，最终稳定性化为有限比较；谓词本身也适用于没有给出谱的无限路径。
[099:16] 有人可能认为，中阴存在是理论不完善的结果，其实，这是典型的一根筋思维，对于这种思维，世界就是机械的，任何时候都只有一个机械精确的结果，而实际上，世界更多是量子化的，是测不准的，中阴的存在恰好客观地反映了走势的这种特性。 -/
instance [DecidableEq B] (f : History A → B) (stream : Nat → A) (value : B)
    [s : TailSpectrum (fun n => f (List.ofFn (fun i : Fin n => stream i.val)))] :
    Decidable (LimitStable f stream value) :=
  decidable_of_iff (∀ b ∈ s.recurrent.values, b = value) ⟨by
    intro check
    obtain ⟨n, confined⟩ := s.confined
    exact ⟨n, fun m hm => check _ (confined m hm)⟩, by
    intro stable b hb
    obtain ⟨n, fixed⟩ := stable
    obtain ⟨m, hm, eq⟩ := (s.recurrent.exactImage b).mp hb n
    exact eq.symm.trans (fixed m hm)⟩

/-- 用稳定的对象地址查旧输出，改写或撤销各计一次；新输出不算修订，零修订时没有最深层。
[099:22] 另外，根据结合律，连接中枢的走势，并不一定是完全的趋势类型，也就是说，一个线段类上涨后，可能第二类类中枢就消融在中阴状态的那个中枢里了。也就是说，a+b+c+d+e+f= a+b+c+（d+e+f），a+b+c+d+e是一个线段类上涨，c+d+e的重合部分构成最后的一个类中枢，f是类背驰后的回调，这时候，就可以马上构成一个1分钟的中枢，然后后面直接继续上涨，构成1分钟的上涨是完全合理的。因为，最终的划分，就必须把a+b+c+d+e给拆开了。 -/
def RevisionCount {Key : Type*} [DecidableEq B] (h : History A) (tail : List A)
    (addresses : List Key) (_distinct : addresses.Nodup) (level : Key → Nat)
    (readAt : History A → Key → Option B) : Nat × Option Nat :=
  let changed := addresses.filter fun k =>
    (readAt h k).isSome && decide (readAt h k ≠ readAt (h ++ tail) k)
  (changed.length, (changed.map level).max?)

end Chan.Defs.Path
