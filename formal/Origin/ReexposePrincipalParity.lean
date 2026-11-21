import Lean
import Origin.TotalWealth

/-! #1651 对拍入口：从 stdin 读取共用向量，逐步执行 Origin 正式核并输出 JSON。 -/

open Lean
open NewChanlun.Origin.TotalWealth

private structure InputState where
  free : Int
  holding : Int
  withdrawn : Int
  notional_in : Int
  stage_rank : Nat
  open_legacy_legs : Nat
  cum_net_cash : Int
  units : Int
deriving FromJson

private def InputState.toTW (s : InputState) : Except String TWState := do
  let stage ← match s.stage_rank with
    | 0 => pure TStage.costReduction
    | 1 => pure TStage.capitalRecovered
    | 2 => pure TStage.earningShares
    | _ => throw "非法阶段序"
  pure ⟨s.free, s.holding, s.withdrawn, s.notional_in, stage, s.open_legacy_legs,
    s.cum_net_cash, s.units⟩

private structure InputEvent where
  kind : String
  amount : Int
deriving FromJson

private def InputEvent.toTW (e : InputEvent) : Except String TWEvent :=
  match e.kind with
  | "recover_capital" => pure (.recoverCapital e.amount)
  | "reexpose_principal" => pure (.reexposePrincipal e.amount)
  | "enter_earning" => pure .enterEarning
  | "clear_campaign" => pure .clearCampaign
  | _ => throw s!"未知事件 {e.kind}"

private structure InputVector where
  name : String
  initial : InputState
  events : List InputEvent
deriving FromJson

private instance (s : TWState) (e : TWEvent) : Decidable (LegalTransition s e) := by
  cases e <;> simp only [LegalTransition, LegalEnterEarning] <;> infer_instance

private structure OutputState where
  legal : Bool
  free : Int
  holding : Int
  withdrawn : Int
  notional_in : Int
  stage_rank : Nat
  open_legacy_legs : Nat
  cum_net_cash : Int
  tw : Int
  l_wc : Int
deriving ToJson

private structure OutputStep where
  shared : OutputState
  units : Int
deriving ToJson

private structure OutputVector where
  name : String
  steps : Array OutputStep
deriving ToJson

private def runVector (v : InputVector) : Except String OutputVector := do
  let mut s ← v.initial.toTW
  let mut steps := #[]
  for input in v.events do
    let e ← input.toTW
    let legal := decide (LegalTransition s e)
    s := twStep s e
    let shared := ⟨legal, s.free, s.holding, s.withdrawn, s.notionalIn, s.stage.rank,
      s.openLegacyLegs, s.cumNetCash, s.tw, lWc s⟩
    steps := steps.push ⟨shared, s.units⟩
  pure ⟨v.name, steps⟩

def main : IO Unit := do
  let input ← (← IO.getStdin).getLine
  let output : Except String (List OutputVector) := do
    let vectors : List InputVector ← fromJson? (← Json.parse input)
    vectors.mapM runVector
  match output with
  | .ok rows => IO.println (toJson rows).compress
  | .error message => throw (IO.userError message)
