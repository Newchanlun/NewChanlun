#[cfg(test)]
mod fixture;
#[cfg(test)]
mod consumer {
    use newchan_rust::at14_report::*;
    use super::fixture::valid_pass_input;
    #[test]
    fn public_sample_roundtrip_and_explicitly_unrun() {
        let input = valid_pass_input();
        let formal_profile = input.profile_json.get("structure").is_some();
        let formal_manifest = input.manifest_json.pointer("/economic/b").is_some();
        let sealed = seal_report(input.clone()).unwrap();
        let restored = verify_sealed_json(&sealed.to_pretty_json()).unwrap();
        assert_eq!(sealed, restored);
        println!("sample oracle fixture: profile.structure={formal_profile}, manifest.economic.b={formal_manifest}, verdict={}", restored.verdict().label());
        let mut waiting = input;
        waiting.h2 = None;
        assert!(!seal_report(waiting).unwrap().verdict().is_pass());
    }
    #[test]
    fn consumer_needs_independent_review_and_ci_identity() {
        let mut local_run = valid_pass_input();
        local_run.ci_run_id = None;
        local_run.review_binding = None;
        let maybe = seal_report(local_run);
        assert!(!maybe.is_ok_and(|r|r.verdict().is_pass()),"unbound report still PASS");
    }
    #[test]
    fn reported_input_source_matches_echoed_source() {
        let mut sample = valid_pass_input();
        sample.input_source = InputSource::DatabentoEqusMiniTickV1;
        if let Ok(r) = seal_report(sample) {
            if r.verdict().is_pass() {
                let b = r.body();
                assert_eq!(b.input_source.as_str(),b.session.profile_echo["input_source"].as_str().unwrap());
            }
        }
    }
    #[test]
    fn incomplete_report_is_not_deserializable() {
        let incomplete = r#"{"verdict":{"kind":"PASS"}}"#;
        assert!(verify_sealed_json(incomplete).is_err());
    }
}
