//! #1496：#2114 已裁的 R5 字面见证，走共用扫描的公开接口。

use newchan_rust::theta_v0::classifier::center::{
    center_from_segments, center_from_window, r5_joint, R5Joint, UnitRange,
};
use newchan_rust::theta_v0::classifier::center_scan::{
    scan_center_facts_full, scan_center_facts_with_r5, CenterScanFacts, R5AttestedLegs, R5Boundary,
    R5DirectionSource, R5Gap, R5Proof, R5Witness, UnitAssignment,
};
use newchan_rust::theta_v0::types::{Direction, Tick};
use serde::Deserialize;
use serde_json::{json, Value};

use Direction::{Down, Up};

const CONNECTED: [Tick; 10] = [10, 40, 20, 35, 30, 38, 21, 25, 5, 15];

fn unit(k: usize, (direction, lo, hi): (Direction, Tick, Tick)) -> UnitRange {
    UnitRange {
        start_index: k * 4,
        end_index: k * 4 + 4,
        direction,
        lo,
        hi,
    }
}

fn from_endpoints(p: &[Tick]) -> Vec<UnitRange> {
    p.windows(2)
        .enumerate()
        .map(|(k, w)| {
            let dir = if w[1] > w[0] { Up } else { Down };
            unit(k, (dir, w[0].min(w[1]), w[0].max(w[1])))
        })
        .collect()
}

fn from_ranges(ranges: &[(Direction, Tick, Tick)]) -> Vec<UnitRange> {
    ranges
        .iter()
        .copied()
        .enumerate()
        .map(|(k, u)| unit(k, u))
        .collect()
}

fn outward() -> Vec<UnitRange> {
    from_ranges(&[
        (Up, 10, 40),
        (Down, 20, 40),
        (Up, 20, 35),
        (Down, 30, 37),
        (Up, 36, 50),
    ])
}

fn unequal_joint() -> Vec<UnitRange> {
    from_ranges(&[
        (Up, 10, 40),
        (Down, 20, 40),
        (Up, 20, 35),
        (Down, 25, 36),
        (Up, 22, 45),
        (Down, 38, 50),
    ])
}

fn add_later_window(units: &mut Vec<UnitRange>) {
    let offset = units.len() * 4;
    units.extend(
        from_endpoints(&CONNECTED.map(|p| p + 100))
            .into_iter()
            .map(|mut u| {
                u.start_index += offset;
                u.end_index += offset;
                u
            }),
    );
}

fn assert_windows(facts: &CenterScanFacts, expected: &[(usize, usize)]) {
    let windows: Vec<_> = facts.windows.iter().map(|w| (w.seed_at, w.exit)).collect();
    assert_eq!(windows, expected, "共用扫描窗口（seed, exit）");
}

fn single_proof(facts: &CenterScanFacts, units: &[UnitRange]) -> R5Proof {
    let witnesses = facts.r5_witnesses(units);
    let [R5Witness::Proven(p)] = witnesses.as_slice() else {
        panic!("期望 R5 见证，实际 {witnesses:?}");
    };
    *p
}

#[test]
fn connected_down_break_k8_proves_first_pullback() {
    let units = from_endpoints(&CONNECTED);
    let facts = scan_center_facts_full(&units, center_from_segments);
    assert_windows(&facts, &[(0, 8)]);
    let p = single_proof(&facts, &units);
    assert_eq!((p.leave_unit(), p.pullback_unit(), p.side()), (7, 8, Down));
    assert_eq!(p.core(), (20, 35));
    assert_eq!(p.pullback_extreme(), 15);
}

#[test]
fn connected_up_break_k8_proves_first_pullback() {
    let units = from_endpoints(&CONNECTED.map(|p| 45 - p));
    let facts = scan_center_facts_full(&units, center_from_segments);
    assert_windows(&facts, &[(0, 8)]);
    let p = single_proof(&facts, &units);
    assert_eq!((p.leave_unit(), p.pullback_unit(), p.side()), (7, 8, Up));
    assert_eq!(p.core(), (10, 25));
    assert_eq!(p.pullback_extreme(), 30);
}

#[test]
fn outward_break_unit_has_no_witness() {
    let mut units = outward();
    let before = scan_center_facts_full(&units, center_from_segments);
    assert_windows(&before, &[(0, 4)]);
    assert_eq!((before.centers[0].0.zd, before.centers[0].0.zg), (20, 35));
    let expected = [R5Witness::Absent(R5Gap::BreakUnitOutward)];
    assert_eq!(before.r5_witnesses(&units), expected);

    // 晚一段回到核心不顶替 exit；保留塔当前的窗口。
    units.push(unit(5, (Down, 33, 50)));
    let after = scan_center_facts_full(&units, center_from_segments);
    assert_eq!(after.windows, before.windows);
    assert_eq!(after.centers, before.centers);
    assert_eq!(after.r5_witnesses(&units), expected);
}

#[test]
fn reverse_break_with_unequal_joint_extremes_has_no_witness() {
    let units = unequal_joint();
    let facts = scan_center_facts_full(&units, center_from_segments);
    assert_windows(&facts, &[(0, 5)]);
    assert_eq!(
        facts.r5_witnesses(&units),
        [R5Witness::Absent(R5Gap::JointNotConnected)]
    );
}

#[test]
fn tangent_unit_is_member_not_pullback() {
    let units = from_ranges(&[
        (Up, 10, 40),
        (Down, 20, 40),
        (Up, 20, 35),
        (Down, 25, 35),
        (Up, 25, 45),
        (Down, 35, 45),
    ]);
    let facts = scan_center_facts_full(&units, center_from_segments);
    assert_windows(&facts, &[(0, 6)]);
    assert_eq!(facts.r5_witnesses(&units), [R5Witness::Absent(R5Gap::Open)]);
    assert_eq!(r5_joint(20, 35, &units[4], &units[5]), R5Joint::NotOutside);
}

#[test]
fn upstream_unproven_blocks_later_windows() {
    let mut units = outward();
    add_later_window(&mut units);
    let facts = scan_center_facts_full(&units, center_from_segments);
    assert_windows(&facts, &[(0, 4)]);
    assert_eq!(
        facts.r5_witnesses(&units),
        [R5Witness::Absent(R5Gap::BreakUnitOutward)]
    );

    let mut control = from_endpoints(&CONNECTED);
    add_later_window(&mut control);
    let facts = scan_center_facts_full(&control, center_from_segments);
    assert_windows(&facts, &[(0, 8), (9, 17)]);
    let witnesses = facts.r5_witnesses(&control);
    assert!(
        matches!(
            witnesses.as_slice(),
            [R5Witness::Proven(_), R5Witness::Proven(_)]
        ),
        "{witnesses:?}"
    );
}

#[test]
fn non_alternating_units_have_no_witness() {
    let units = from_ranges(&[
        (Up, 10, 40),
        (Up, 20, 40),
        (Up, 20, 35),
        (Down, 30, 45),
        (Down, 40, 50),
    ]);
    // 上级形状同样按数据核关节，不通过级别闸门。
    let facts = scan_center_facts_full(&units, center_from_window);
    assert_windows(&facts, &[(0, 4)]);
    assert_eq!(
        facts.r5_witnesses(&units),
        [R5Witness::Absent(R5Gap::DirectionNotAlternating)]
    );
}

// 与 classifier/tests/center_scan_1419.rs 的生成器同形，包括偶发大跳。
fn alternating_endpoints(seed: u64, len: usize) -> Vec<Tick> {
    let mut s = seed
        .wrapping_mul(6364136223846793005)
        .wrapping_add(1442695040888963407);
    let mut next = || {
        s = s
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        (s >> 33) as i64
    };
    let mut p = vec![50];
    for k in 0..len {
        let step = 1 + next().rem_euclid(9) + if next().rem_euclid(7) == 0 { 15 } else { 0 };
        let last = *p.last().unwrap();
        p.push(if k % 2 == 0 { last + step } else { last - step });
    }
    p
}

#[test]
fn connected_alternating_streams_prove_every_settled_window() {
    let (mut proven, mut upgraded, mut open) = (0, 0, 0);
    for seed in 0..128 {
        let units = from_endpoints(&alternating_endpoints(seed, 48));
        let facts = scan_center_facts_full(&units, center_from_segments);
        let witnesses = facts.r5_witnesses(&units);
        assert_eq!(witnesses.len(), facts.windows.len());
        for (w, witness) in facts.windows.iter().zip(witnesses) {
            if w.boundary == R5Boundary::Open {
                assert_eq!(
                    witness,
                    R5Witness::Absent(R5Gap::Open),
                    "seed={seed}, {w:?}"
                );
                open += 1;
            } else if w.upgraded {
                assert_eq!(
                    witness,
                    R5Witness::Absent(R5Gap::UpgradePending),
                    "seed={seed}, {w:?}"
                );
                upgraded += 1;
            } else {
                let R5Witness::Proven(p) = witness else {
                    panic!("seed={seed}, {w:?}：期望首回抽见证，实际 {witness:?}");
                };
                assert_eq!((p.leave_unit(), p.pullback_unit()), (w.exit - 1, w.exit));
                proven += 1;
            }
        }
    }
    assert!(proven > 0 && upgraded > 0 && open > 0);
}

#[test]
fn settled_witness_is_stable_under_append() {
    let connected = from_endpoints(&alternating_endpoints(7, 48));
    let mut ragged = unequal_joint();
    add_later_window(&mut ragged);
    for (name, units) in [("相连", connected), ("关节不齐", ragged)] {
        let mut settled = Vec::new();
        for len in 0..=units.len() {
            let prefix = &units[..len];
            let facts = scan_center_facts_full(prefix, center_from_segments);
            let now: Vec<_> = facts
                .windows
                .iter()
                .copied()
                .zip(facts.r5_witnesses(prefix))
                .filter(|(w, _)| {
                    matches!(w.boundary, R5Boundary::Destroyed(_) | R5Boundary::Upgrade)
                })
                .collect();
            assert!(
                now.starts_with(&settled),
                "{name}，前缀 {len}: {settled:?} → {now:?}"
            );
            settled = now;
        }
        if name == "相连" {
            assert!(settled.len() >= 2, "相连流须覆盖多个已结算或已升级窗口");
        } else {
            assert!(settled.is_empty(), "首关节缺证不允许产生权威后窗");
        }
    }
}

#[derive(Deserialize)]
enum DirectionRow {
    #[serde(alias = "UP")]
    Up,
    #[serde(alias = "DOWN")]
    Down,
}

#[derive(Deserialize)]
struct UnitRow {
    #[serde(alias = "dir")]
    direction: DirectionRow,
    lo: Tick,
    hi: Tick,
    start_index: usize,
    end_index: usize,
}

impl From<UnitRow> for UnitRange {
    fn from(row: UnitRow) -> Self {
        Self {
            direction: match row.direction {
                DirectionRow::Up => Up,
                DirectionRow::Down => Down,
            },
            lo: row.lo,
            hi: row.hi,
            start_index: row.start_index,
            end_index: row.end_index,
        }
    }
}

#[test]
fn real_l0_fixture_joints_are_not_all_connected() {
    #[derive(Deserialize)]
    struct Real {
        tower_units: Vec<UnitRow>,
    }
    let real: Real = serde_json::from_str(include_str!(
        "../../s_session/tests/fixtures/tb02e-real/btc-tail50k-first600.json"
    ))
    .unwrap();
    let units: Vec<UnitRange> = real.tower_units.into_iter().map(Into::into).collect();
    let joints: Vec<_> = units
        .windows(2)
        .map(|u| {
            let (prev, cur) = (&u[0], &u[1]);
            let (end, start) = match (prev.direction, cur.direction) {
                (Up, Down) => (prev.hi, cur.hi),
                (Down, Up) => (prev.lo, cur.lo),
                _ => panic!("实样方向应交替"),
            };
            prev.end_index == cur.start_index && end == start
        })
        .collect();
    assert_eq!(joints, [false, true, true, false, true]);

    let facts = scan_center_facts_full(&units, center_from_segments);
    assert_windows(&facts, &[(0, 5)]);
    let p = single_proof(&facts, &units);
    assert_eq!(p.core(), (7_762_000_000_000, 7_773_905_000_000));
    assert_eq!((p.leave_unit(), p.pullback_unit(), p.side()), (4, 5, Down));
}

#[test]
fn r5_joint_matches_lean_fixture() {
    #[derive(Deserialize)]
    struct Fixture {
        schema: String,
        cases: Vec<Case>,
    }
    #[derive(Deserialize)]
    struct Case {
        name: String,
        zd: Tick,
        zg: Tick,
        prev: UnitRow,
        cur: UnitRow,
        expected: Value,
    }
    let fixture: Fixture =
        serde_json::from_str(include_str!("fixtures/r5_witness_1496_lean.json")).unwrap();
    assert_eq!(fixture.schema, "tb1496-r5-joint/1");
    assert!(fixture.cases.len() >= 9);
    for c in fixture.cases {
        let actual = match r5_joint(c.zd, c.zg, &c.prev.into(), &c.cur.into()) {
            R5Joint::NotOutside => json!("NotOutside"),
            R5Joint::BreakUnitOutward => json!("BreakUnitOutward"),
            R5Joint::DirectionNotAlternating => json!("DirectionNotAlternating"),
            R5Joint::PrevOutsideCore => json!("PrevOutsideCore"),
            R5Joint::JointNotConnected => json!("JointNotConnected"),
            R5Joint::Proven { side: Up } => json!({"Proven":"Up"}),
            R5Joint::Proven { side: Down } => json!({"Proven":"Down"}),
        };
        assert_eq!(actual, c.expected, "Lean 例 {}", c.name);
    }
}

fn c_example(j: usize, return_lo: Tick) -> Vec<UnitRange> {
    let mut legs = vec![(Down, 20, 40), (Up, 20, 35), (Down, 25, 35)];
    legs.extend((3..j).map(|k| (if k % 2 == 1 { Up } else { Down }, 25, 35)));
    legs.extend([(Up, 36, 50), (Down, return_lo, 50)]);
    from_ranges(&legs)
}

fn roles(j: usize) -> R5AttestedLegs {
    R5AttestedLegs {
        seed: 0,
        leave: j,
        side: Up,
        first_pullback: Some(j + 1),
        leave_is_zn: Some(false),
    }
}

#[test]
fn return_forms_five_or_upgrades_at_nine_without_connector() {
    use newchan_rust::theta_v0::classifier::center::RoleVar;
    for j in [3, 7] {
        let units = c_example(j, 33);
        for build in [center_from_window, center_from_segments] {
            let facts =
                scan_center_facts_with_r5(&units, build, R5DirectionSource::Native, &[roles(j)]);
            let ws = facts.window_facts(&units);
            assert_eq!(ws[0].count(), j + 2);
            assert_eq!(ws[0].upgrade_pending, j == 7);
            assert!(!ws[0].settled);
            assert_eq!(ws[0].resume_anchor, None);
            assert_eq!(facts.windows[0].last_return.unwrap().pullback_unit(), j + 1);
            assert_eq!(ws[0].role(RoleVar::Gg).value, 50);
            assert_eq!(ws[0].role(RoleVar::D).value, 33);
            assert!(!ws[0].zn_members.contains(&j));
            assert!(ws[0].zn_members.contains(&(j + 1)));
            assert!(!facts
                .unit_facts()
                .iter()
                .any(|u| matches!(u.assignment, UnitAssignment::Connector { .. })));
        }
    }
}

#[test]
fn late_return_does_not_replace_first_and_proof_read_horizon_contains_retest() {
    let mut units = c_example(3, 37);
    units.push(unit(5, (Up, 29, 38)));
    let pending = scan_center_facts_with_r5(
        &units[..4],
        center_from_segments,
        R5DirectionSource::Native,
        &[roles(3)],
    );
    assert_eq!(
        pending.r5_witnesses(&units[..4]),
        [R5Witness::Absent(R5Gap::AwaitingFirstPullback)]
    );
    let facts = scan_center_facts_with_r5(
        &units,
        center_from_segments,
        R5DirectionSource::Native,
        &[roles(3)],
    );
    let w = &facts.window_facts(&units)[0];
    let proof = w.settlement.unwrap();
    assert_eq!(
        (w.last, w.break_unit, w.resume_anchor),
        (2, Some(3), Some(4))
    );
    assert_eq!((proof.leave_unit(), proof.pullback_unit()), (3, 4));
    assert_eq!(facts.metas[0].read_end_src, units[4].end_index);
    assert_eq!(facts.metas[0].settlement, Some(proof));
    assert_eq!(
        facts.unit_facts()[3].assignment,
        UnitAssignment::Connector {
            left: 0,
            right: None
        }
    );
    assert!(facts.pair_facts(&units).is_empty());
}

#[test]
fn unknown_roles_never_grant_member_or_destruction_even_with_strict_geometry() {
    let units = c_example(3, 33);
    let no_roles =
        scan_center_facts_with_r5(&units, center_from_segments, R5DirectionSource::Native, &[]);
    assert_eq!(no_roles.window_facts(&units)[0].count(), 3);
    let mut evidence = roles(3);
    evidence.leave_is_zn = None;
    let unknown = scan_center_facts_with_r5(
        &units,
        center_from_segments,
        R5DirectionSource::Native,
        &[evidence],
    );
    assert_eq!(
        unknown.r5_witnesses(&units),
        [R5Witness::Absent(R5Gap::ReturnedMembershipUnresolved)]
    );
    assert!(unknown.windows[0].last_return.is_some());
    let connected = from_endpoints(&CONNECTED);
    let placeholder = scan_center_facts_with_r5(
        &connected,
        center_from_segments,
        R5DirectionSource::Unproven,
        &[],
    );
    assert_eq!(
        placeholder.r5_witnesses(&connected),
        [R5Witness::Absent(R5Gap::DirectionUnproven)]
    );
}

#[test]
fn nine_counts_waves_and_return_at_touch_reopens_same_seed_only() {
    let mut units = c_example(7, 35);
    units[4].lo = 30;
    units[4].hi = 30;
    units.push(unit(9, (Up, 30, 40)));
    let a = scan_center_facts_with_r5(
        &units[..9],
        center_from_segments,
        R5DirectionSource::Native,
        &[roles(7)],
    );
    assert_eq!(a.windows[0].boundary, R5Boundary::Open);
    assert_eq!(a.windows[0].exit, 9);
    let b = scan_center_facts_with_r5(
        &units,
        center_from_segments,
        R5DirectionSource::Native,
        &[roles(7)],
    );
    assert_eq!(b.windows[0].boundary, R5Boundary::Upgrade);
    assert_eq!(b.windows[0].exit, 10);
    assert_eq!(b.windows[0].last_return.unwrap().pullback_extreme(), 35);
}

#[test]
fn lean_r5_worked_examples_match_production_scan() {
    use newchan_rust::theta_v0::classifier::center::RoleVar;
    let oracle: Value =
        serde_json::from_str(include_str!("fixtures/theta_v0_center_parity.json")).unwrap();
    for (name, j, lo) in [
        ("r5_return_five", 3, 33),
        ("r5_return_nine", 7, 33),
        ("r5_strict_first_pullback", 3, 37),
    ] {
        let units = c_example(j, lo);
        let facts = scan_center_facts_with_r5(
            &units,
            center_from_segments,
            R5DirectionSource::Native,
            &[roles(j)],
        );
        let w = &facts.window_facts(&units)[0];
        let expected = &oracle[name][0];
        assert_eq!(
            w.count(),
            expected["count"].as_u64().unwrap() as usize,
            "{name}"
        );
        assert_eq!(w.settled, expected["settled"].as_bool().unwrap(), "{name}");
        assert_eq!(
            w.upgrade_pending,
            expected["upgraded"].as_bool().unwrap(),
            "{name}"
        );
        assert_eq!(
            json!(w.settlement.map(|p| p.leave_unit())),
            expected["leave"],
            "{name}"
        );
        assert_eq!(
            json!(w.settlement.map(|p| p.pullback_unit())),
            expected["pullback"],
            "{name}"
        );
        assert_eq!(
            json!(facts.windows[0].last_return.map(|p| p.pullback_unit())),
            expected["returned"],
            "{name}"
        );
        assert_eq!(json!(w.role(RoleVar::Gg).value), expected["gg"], "{name}");
        assert_eq!(json!(w.role(RoleVar::Dd).value), expected["dd"], "{name}");
    }
}

#[test]
fn five_non_alternating_members_use_seed_direction_for_zn() {
    use newchan_rust::theta_v0::classifier::center::RoleVar;
    let units = from_ranges(&[
        (Down, 20, 40),
        (Up, 20, 35),
        (Down, 25, 35),
        (Down, 24, 60),
        (Up, 30, 55),
    ]);
    for build in [center_from_segments, center_from_window] {
        let facts = scan_center_facts_full(&units, build);
        let window = &facts.window_facts(&units)[0];
        assert_eq!((window.first, window.last), (0, 4));
        assert_eq!(window.zn_members, [0, 2, 3]);
        assert_eq!(window.role(RoleVar::Gg).value, 60);
        assert_eq!(window.role(RoleVar::Gg).contributors, [3]);
    }
}
