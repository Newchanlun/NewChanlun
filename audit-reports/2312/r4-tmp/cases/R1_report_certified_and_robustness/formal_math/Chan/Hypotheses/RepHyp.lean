module
public import Chan.Defs.RepDefs
@[expose] public section
inductive NomInd (n : Nat) : Prop where
  | mk : D n = 1 → NomInd n
  | alt : D n = 1 → NomInd n
