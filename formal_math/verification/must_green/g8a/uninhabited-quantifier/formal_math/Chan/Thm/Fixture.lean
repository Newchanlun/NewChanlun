module

public section

theorem claim (P : Prop) (_h : Empty → P) (h : ¬ ¬ P) : P := Classical.byContradiction h
