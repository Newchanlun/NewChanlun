#![cfg(feature = "s_session")]

use std::num::NonZeroU32;

use newchan_rust::theta_v0::cost_stop::{
    CostComponent, CostGap, CostStopPolicy, CostStopProfile, CostStopStatus, NotEvaluableReason,
};
use newchan_rust::theta_v0::policy_records::{PolicyError, PolicyVersion};

#[test]
fn public_load_and_evaluate_use_only_profile_revision_and_level() {
    for (profile, key) in [
        (CostStopProfile::P0, "#1354/cost-stop-policy/P0@1"),
        (
            CostStopProfile::P1HlTestnet,
            "#1354/cost-stop-policy/P1-hl-testnet@1",
        ),
    ] {
        let revision = NonZeroU32::new(1).unwrap();
        let policy = CostStopPolicy::load(profile, revision).unwrap();
        assert_eq!(policy.record().version, PolicyVersion::Signed(1));
        assert_eq!(policy.identity().key(), key);
        let outcome = policy.evaluate(0).unwrap();
        assert_eq!(
            outcome.status(),
            CostStopStatus::NotEvaluable(NotEvaluableReason::UnavailableCost(
                CostComponent::Slippage
            )),
        );
        assert_eq!(
            outcome.cost_gap(),
            Some((CostComponent::Slippage, CostGap::SignedMissing))
        );
        assert_eq!(outcome.record(), policy.record());
        assert_eq!(outcome.consumed(), std::slice::from_ref(policy.identity()));
        assert!(outcome.amplitude_gap().is_none());
        assert!(outcome.windows().is_empty());
        assert!(matches!(
            CostStopPolicy::load(profile, NonZeroU32::new(2).unwrap()),
            Err(PolicyError::RecordMissing { .. })
        ));
    }
}
