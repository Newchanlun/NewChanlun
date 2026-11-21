use super::*;
use crate::theta_v0::classifier::{
    center::{center_from_segments, UnitRange},
    center_scan::scan_center_facts_full,
    decompose::decompose,
    recursive_tower::{compose_level, ElementId},
};
use crate::theta_v0::config::TowerBase;

fn native_stream(seed: u64) -> Vec<UnitRange> {
    let mut state = seed + 1;
    let mut price = 100;
    (0..96)
        .map(|k| {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
            let step = 2 + ((state >> 32) % 23) as i64;
            let (start, direction, end) = if k % 2 == 0 {
                (price, Direction::Up, price + step)
            } else {
                (price, Direction::Down, price - step)
            };
            price = end;
            UnitRange {
                start_index: k,
                end_index: k + 1,
                lo: start.min(end),
                hi: start.max(end),
                direction,
            }
        })
        .collect()
}

fn native_projection(units: &[UnitRange]) -> (ExactThreeProjection, Vec<LowerLeg>) {
    let moves = units
        .iter()
        .enumerate()
        .map(|(k, u)| {
            LeveledMove::from_unit(
                u,
                ElementId {
                    level: 0,
                    ordinal: k as u64,
                },
            )
        })
        .collect::<Vec<_>>();
    let (_, upper, _) = compose_level(units, &moves, true, 1, TowerBase::Segment);
    (
        project_extended_windows_carried_only(&upper).unwrap(),
        lower_legs_from(&moves).unwrap(),
    )
}

#[test]
fn r5_b1_a_excludes_b_terminal_leave_without_moving_c() {
    let units = native_stream(1);
    let (projection, lower) = native_projection(&units);
    let centers = projection
        .seeds
        .iter()
        .map(|seed| seed.center)
        .collect::<Vec<_>>();
    let facts = scan_center_facts_full(&units, center_from_segments);
    let proofs = facts
        .metas
        .iter()
        .map(|meta| meta.settlement)
        .collect::<Vec<_>>();
    let b = centers[5];
    assert_eq!((b.start_index, b.end_index, b.zd, b.zg), (22, 25, 100, 103));
    let proof = proofs[5].unwrap();
    assert_eq!(
        (
            proof.leave_unit(),
            proof.pullback_unit(),
            proof.pullback_extreme()
        ),
        (24, 25, 107)
    );
    let pairs =
        provide_divergence_pairs_with_r5(1, &projection, &decompose(&centers), &lower, 96, &proofs);
    let pair = pairs
        .iter()
        .find(|pair| pair.id.block_end_center == 5)
        .unwrap();
    assert_eq!(pair.seg_c, (24, 95));
    assert_eq!(pair.seg_a, (20, 23));
}

#[test]
fn r5_b3_ordinary_and_resident_consume_native_settlements() {
    // seed 1: B1 removes the old high of 122 from A, so T2 is already true at T3 (26).
    // seed 2: disjoint A/C on both revisions, isolating B3 from the B1 correction.
    for (seed, b, direction, hist_span, a, c, at) in [
        (1, 5, Direction::Up, 20..24, (20, 23), (24, 95), 26),
        (2, 18, Direction::Down, 69..75, (69, 74), (75, 96), 77),
    ] {
        let units = native_stream(seed);
        let (projection, lower) = native_projection(&units);
        let centers = projection
            .seeds
            .iter()
            .map(|seed| seed.center)
            .collect::<Vec<_>>();
        let blocks = decompose(&centers);
        let facts = scan_center_facts_full(&units, center_from_segments);
        let proofs = facts
            .metas
            .iter()
            .map(|meta| meta.settlement)
            .collect::<Vec<_>>();
        let coords = (0..=96).collect::<Vec<_>>();
        let mut hist = vec![0.0; coords.len()];
        hist[hist_span].fill(if direction == Direction::Up {
            8.0
        } else {
            -8.0
        });
        let dif = vec![0.0; coords.len()];
        let query = LevelViewQuery {
            level: 1,
            coordinate_window: CoordinateWindow { start: 0, end: 96 },
            as_of: 96,
            version: C2VersionTuple::auto_pairing(),
        };
        let config = C2LevelViewConfig { enabled: true };
        let material = || LevelViewMaterial {
            projection: ProjectionMaterial::ExactThree(&projection),
            move_blocks: &blocks,
            lower_legs: &lower,
            hist: &hist,
            dif: &dif,
            close_src: &coords,
        };
        let explicit =
            assemble_level_view_with_r5(config, query, material(), &proofs, None).unwrap();
        let ordinary = assemble_level_view(config, query, material()).unwrap();
        let mut store = ConfirmCursorStore::default();
        let resident = assemble_level_view_resident(
            config,
            query,
            material(),
            Some(ConfirmResidence {
                store: &mut store,
                structure_generation: 0,
                stable_lower_len: lower.len(),
            }),
        )
        .unwrap();
        let state = |view: &LevelAsOfView| {
            view.pair_confirmations
                .iter()
                .find(|item| item.pair_id.block_end_center == b)
                .map(|item| item.state)
        };
        assert_eq!(
            state(&explicit),
            Some(ConfirmState::Confirmed(at)),
            "seed {seed}"
        );
        let pair = ordinary
            .pairs
            .iter()
            .find(|pair| pair.id.block_end_center == b)
            .unwrap();
        assert_eq!((pair.seg_a, pair.seg_c), (a, c));
        assert_eq!(ordinary, explicit, "seed {seed}: ordinary");
        assert_eq!(resident, ordinary, "seed {seed}: resident");

        let early = LevelViewQuery {
            as_of: at - 1,
            ..query
        };
        let before = assemble_level_view(config, early, material()).unwrap();
        assert!(!matches!(state(&before), Some(ConfirmState::Confirmed(_))));

        let mut wrong_flow = lower.clone();
        wrong_flow[proofs[b].unwrap().pullback_unit()].id.level = 1;
        let unproven = assemble_level_view(
            config,
            query,
            LevelViewMaterial {
                lower_legs: &wrong_flow,
                ..material()
            },
        )
        .unwrap();
        assert!(!matches!(
            state(&unproven),
            Some(ConfirmState::Confirmed(_))
        ));

        let cropped_lower = assemble_level_view(
            config,
            query,
            LevelViewMaterial {
                lower_legs: &lower[10..],
                ..material()
            },
        )
        .unwrap();
        assert_eq!(state(&cropped_lower), Some(ConfirmState::Confirmed(at)));

        // Projection of one run uses entity identity, not its new index (0).
        let mut cropped = projection.clone();
        cropped.seeds = cropped.seeds[b..=b].to_vec();
        assert_eq!(cropped.native_settlements(&lower), [proofs[b]]);
    }
}

#[test]
fn r5_b3_revised_seed_cannot_reuse_old_window_settlement() {
    let original = native_stream(6);
    let mut revised = original.clone();
    // 顶点 61 是两条相邻原生段的同一高点。只修订这一个源顶点。
    assert_eq!((revised[60].hi, revised[61].hi), (91, 91));
    revised[60].hi = 93;
    revised[61].hi = 93;
    let (old_projection, old_lower) = native_projection(&original);
    let (new_projection, new_lower) = native_projection(&revised);
    let facts = scan_center_facts_full(&revised, center_from_segments);
    let window = facts.windows.iter().find(|w| w.seed_at == 58).unwrap();
    let core = facts.attempts.iter().find(|a| a.at == 58).unwrap().facts;
    assert_eq!((core.zd, core.zg), (85, 93));
    assert!(window.upgraded);

    let coords = (0..=96).collect::<Vec<_>>();
    let mut hist = vec![0.0; coords.len()];
    hist[56..64].fill(8.0);
    let dif = vec![0.0; coords.len()];
    for (label, projection, lower, expected) in [
        (
            "original / original",
            &old_projection,
            &old_lower,
            ConfirmState::Confirmed(66),
        ),
        (
            "revised / revised",
            &new_projection,
            &new_lower,
            ConfirmState::Scanning,
        ),
        (
            "original / revised",
            &old_projection,
            &new_lower,
            ConfirmState::Scanning,
        ),
    ] {
        let centers = projection
            .seeds
            .iter()
            .map(|s| s.center)
            .collect::<Vec<_>>();
        let view = assemble_level_view(
            C2LevelViewConfig { enabled: true },
            LevelViewQuery {
                level: 1,
                coordinate_window: CoordinateWindow { start: 0, end: 96 },
                as_of: 96,
                version: C2VersionTuple::auto_pairing(),
            },
            LevelViewMaterial {
                projection: ProjectionMaterial::ExactThree(projection),
                move_blocks: &decompose(&centers),
                lower_legs: lower,
                hist: &hist,
                dif: &dif,
                close_src: &coords,
            },
        )
        .unwrap();
        let states = view
            .pair_confirmations
            .iter()
            .filter(|item| centers[item.pair_id.block_end_center].start_index == 58)
            .map(|item| item.state)
            .collect::<Vec<_>>();
        assert_eq!(states, [expected], "{label}");
    }
}
