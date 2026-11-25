module
@[expose] public section
mutual
  def even : Nat → Bool | 0 => false | n+1 => odd n
  def odd : Nat → Bool | 0 => true | n+1 => even n
end
