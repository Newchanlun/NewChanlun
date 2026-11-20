//! #1426 TB-02-G 形成侧验收锁：
//! 1. #1426 2026-11-19 评论 123 根下行序列：第 111 根读到严格分离，第 123 根 B 结算并判下跌形成（B.GG=2900 < A.DD=3000）；
//! 2. 8500-p 镜像上行序列：同位置判上涨形成（B.DD=5600 > A.GG=5500）；
//! 3. 9011 链 1262→1527→1883（合成中枢级数值）中非相邻 A→C（C.DD−A.GG=+8051）不得判趋势；
//! 4. 扩展对不在本级判盘整、结果为交上级；只有单一未升级中枢判盘整；
//! 5. #804 总缝规则：上下行同判据镜像锁与级别只作输入值的级别不变锁。

use serde_json::Value;

use super::super::super::config::ThetaConfig;
use super::super::super::parser::parse_layer;
use super::super::super::types::{Bar, Center, Direction, Tick};
use super::super::center::{center_from_segments, center_pair_facts, PairLeaf, UnitRange};
use super::super::center_scan::{l0_units, scan_center_facts_full, PairOutcome};
use super::super::trend_formation::{
    judge_adjacent_pair, judge_center_chain_pairs, judge_from_center_chain, judge_from_scan,
    judge_scan_pairs, AdjacentPairError, AdjacentPairInput, CenterEvidence, CenterSettlement,
    ChainCenterInput, ConnectorUnit, FormationKind, InsufficientReason, TrendFormation,
};

const FIXTURE: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/tests/fixtures/trend_formation_1426.json"
));

fn doc() -> Value {
    serde_json::from_str(FIXTURE).expect("夹具是合法 JSON")
}

fn build_bars(prices: &[Tick], spread: Tick) -> Vec<Bar> {
    prices
        .iter()
        .enumerate()
        .map(|(i, &p)| Bar {
            source_index: i,
            timestamp: i as i64,
            open: p,
            high: p + spread,
            low: p - spread,
            close: p,
            volume: 1.0,
            untradable: false,
        })
        .collect()
}

fn fixture_123_bars() -> (Vec<Bar>, Vec<Bar>, Value) {
    let d = doc();
    let cfg = &d["bars_123_down"];
    let spread = cfg["bar_half_spread"].as_i64().unwrap();
    let mirror = cfg["mirror_offset"].as_i64().unwrap();
    let prices: Vec<Tick> = cfg["mid_prices"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_i64().unwrap())
        .collect();
    assert_eq!(prices.len(), 123, "123 根序列长度固定");
    let mirrored: Vec<Tick> = prices.iter().map(|&p| mirror - p).collect();
    (
        build_bars(&prices, spread),
        build_bars(&mirrored, spread),
        d,
    )
}

fn units_from_endpoints(p: &[Tick]) -> Vec<UnitRange> {
    p.windows(2)
        .enumerate()
        .map(|(k, w)| UnitRange {
            start_index: k * 4,
            end_index: k * 4 + 4,
            direction: if w[1] > w[0] {
                Direction::Up
            } else {
                Direction::Down
            },
            lo: w[0].min(w[1]),
            hi: w[0].max(w[1]),
        })
        .collect()
}

fn parse_and_scan(bars: &[Bar]) -> (Vec<UnitRange>, super::super::center_scan::CenterScanFacts) {
    let cfg = ThetaConfig::default();
    let layer = parse_layer(bars, &cfg);
    assert!(
        layer.segments_parse_invalid_from.is_none(),
        "测试输入段端门必须干净"
    );
    assert!(
        layer.segments_resource_bound_from.is_none(),
        "测试输入不得触发尾窗资源截断"
    );
    let units = l0_units(&layer.segments);
    let scan = scan_center_facts_full(&units, center_from_segments);
    (units, scan)
}

fn parse_direction(s: &str) -> Direction {
    match s {
        "UP" => Direction::Up,
        "DOWN" => Direction::Down,
        other => panic!("未知方向 {other}"),
    }
}

fn mirror_center(c: Center, offset: Tick) -> Center {
    Center {
        dd: offset - c.gg,
        zd: offset - c.zg,
        zg: offset - c.zd,
        gg: offset - c.dd,
        start_index: c.start_index,
        end_index: c.end_index,
    }
}

fn assert_mirror_pair(
    a: &super::super::trend_formation::AdjacentPairEvidence,
    b: &super::super::trend_formation::AdjacentPairEvidence,
    offset: Tick,
) {
    assert_eq!(a.center_a().window_index(), b.center_a().window_index());
    assert_eq!(a.center_b().window_index(), b.center_b().window_index());
    assert_eq!(a.center_a().member_units(), b.center_a().member_units());
    assert_eq!(a.center_b().member_units(), b.center_b().member_units());
    assert_eq!(a.center_a().settlement(), b.center_a().settlement());
    assert_eq!(a.center_b().settlement(), b.center_b().settlement());
    assert_eq!(
        mirror_center(a.center_a().center(), offset),
        b.center_a().center()
    );
    assert_eq!(
        mirror_center(a.center_b().center(), offset),
        b.center_b().center()
    );
    assert_eq!(a.connector_unit_range(), b.connector_unit_range());
    assert_eq!(a.connector_coord_span(), b.connector_coord_span());
    for (ca, cb) in a.connectors().iter().zip(b.connectors()) {
        assert_eq!(ca.unit_index, cb.unit_index);
        assert_eq!(ca.unit.direction.flip(), cb.unit.direction);
        assert_eq!(offset - ca.unit.hi, cb.unit.lo);
        assert_eq!(offset - ca.unit.lo, cb.unit.hi);
    }
}

/// 验收 1：#1426 11-19 评论 123 根下行序列——第 111 根读到严格分离（A 结算、B 开放），
/// 第 123 根 B 结算并判下跌形成（B.GG=2900 < A.DD=3000，连接段 u4 49→61）。
#[test]
fn down_123_bars_prefix_111_reads_strict_separation_and_123_settles_down_trend() {
    let (down, _, d) = fixture_123_bars();
    let exp = &d["bars_123_down"]["expected"];
    let exp_down = &exp["down"];

    // 第 110 根尚只有一个已结算中枢 A：判盘整，未达严格分离。
    let (units_110, scan_110) = parse_and_scan(&down[..110]);
    let f110 = judge_from_scan(0, &scan_110, &units_110);
    assert_eq!(f110.kind(), FormationKind::Consolidation);
    assert_eq!(f110.direction(), None);

    // 第 111 根首次读到严格分离：A 已结算，B 仍开放，连接段 u4 (49→61)。
    let (units_111, scan_111) = parse_and_scan(&down[..111]);
    let pairs_111 = scan_111.pair_facts(&units_111);
    assert_eq!(pairs_111.len(), 1);
    assert_eq!(
        pairs_111[0].outcome,
        PairOutcome::Evaluated(center_pair_facts(
            &scan_111.window_center(&units_111, 0),
            &scan_111.window_center(&units_111, 1),
        ))
    );
    match judge_from_scan(0, &scan_111, &units_111) {
        TrendFormation::DownTrendFormed(ev) => {
            let p = ev.forming_pair();
            assert_eq!(ev.level(), 0);
            assert!(p.center_a().is_settled());
            assert_eq!(p.center_a().break_unit(), Some(4));
            assert!(!p.center_b().is_settled(), "第 111 根 B 仍开放");
            assert_eq!(p.center_b().settlement(), CenterSettlement::Open);
            assert!(!ev.is_settled());
            assert_eq!(p.pair_facts().leaf, PairLeaf::DownNewbirth);
            assert_eq!(p.center_a().center().dd, 3000);
            assert_eq!(p.center_b().center().gg, 2900);
            assert!(p.center_b().center().gg < p.center_a().center().dd);
            assert_eq!(p.connector_unit_range(), 4..5);
            assert_eq!(p.connector_coord_span(), (49, 61));
            assert_eq!(p.connectors()[0].unit.direction, Direction::Up);
        }
        other => panic!("第 111 根应读到严格分离的下跌形成（B 开放），实际 {other:?}"),
    }

    // 第 123 根原成员与连接段不变，u8 (97→109) 确认 B 结算并判下跌形成。
    let (units_123, scan_123) = parse_and_scan(&down[..123]);
    assert_eq!(units_123[8].start_index, 97);
    assert_eq!(units_123[8].end_index, 109);
    match judge_from_scan(0, &scan_123, &units_123) {
        TrendFormation::DownTrendFormed(ev) => {
            let p = ev.forming_pair();
            assert_eq!(ev.level(), 0);
            assert!(ev.is_settled(), "第 123 根 A、B 均结算");
            assert!(ev.continuation_pairs().is_empty());
            assert_eq!(p.center_a().member_units(), 0..4);
            assert_eq!(
                p.center_a().settlement(),
                CenterSettlement::Settled { break_unit: 4 }
            );
            assert_eq!(p.center_b().member_units(), 5..8);
            assert_eq!(
                p.center_b().settlement(),
                CenterSettlement::Settled { break_unit: 8 }
            );
            assert_eq!(
                p.center_a().center().dd,
                exp_down["a"]["dd"].as_i64().unwrap()
            );
            assert_eq!(
                p.center_a().center().zd,
                exp_down["a"]["zd"].as_i64().unwrap()
            );
            assert_eq!(
                p.center_a().center().zg,
                exp_down["a"]["zg"].as_i64().unwrap()
            );
            assert_eq!(
                p.center_a().center().gg,
                exp_down["a"]["gg"].as_i64().unwrap()
            );
            assert_eq!(
                p.center_b().center().dd,
                exp_down["b"]["dd"].as_i64().unwrap()
            );
            assert_eq!(
                p.center_b().center().zd,
                exp_down["b"]["zd"].as_i64().unwrap()
            );
            assert_eq!(
                p.center_b().center().zg,
                exp_down["b"]["zg"].as_i64().unwrap()
            );
            assert_eq!(
                p.center_b().center().gg,
                exp_down["b"]["gg"].as_i64().unwrap()
            );
            assert!(p.center_b().center().gg < p.center_a().center().dd);
            assert_eq!(p.connector_unit_range(), 4..5);
            assert_eq!(p.connector_coord_span(), (49, 61));
            assert_eq!(
                p.connectors()[0].unit.direction,
                parse_direction(exp_down["connector_direction"].as_str().unwrap())
            );
            assert_eq!(
                p.pair_facts().leaf.as_str(),
                exp_down["leaf"].as_str().unwrap()
            );

            // R26 负控：若误把 A 的全部成员（含非 Zn 末段 u3）计入外缘，A.DD 降至 2500，退回扩展交上级。
            let full_a_dd = units_123[0..4].iter().map(|u| u.lo).min().unwrap();
            assert_eq!(full_a_dd, exp_down["full_outer_a_dd"].as_i64().unwrap());
            let wrong_a = CenterEvidence::try_new(
                0,
                0..4,
                Center {
                    dd: full_a_dd,
                    ..p.center_a().center()
                },
                CenterSettlement::Settled { break_unit: 4 },
            )
            .unwrap();
            let wrong_chain = judge_from_center_chain(
                0,
                &[
                    ChainCenterInput::Normal(wrong_a),
                    ChainCenterInput::Normal(p.center_b().clone()),
                ],
                &[p.connectors().to_vec()],
            )
            .unwrap();
            assert_eq!(wrong_chain.kind(), FormationKind::HandoffToUpperLevel);
        }
        other => panic!("第 123 根应判下跌形成，实际 {other:?}"),
    }
}

/// 验收 2：8500-p 镜像上行序列——同位置（111 根严格分离、123 根 B 结算）判上涨形成（B.DD=5600 > A.GG=5500）。
#[test]
fn up_mirror_123_bars_prefix_111_and_123_form_up_trend() {
    let (_, up, d) = fixture_123_bars();
    let exp_up = &d["bars_123_down"]["expected"]["up_mirror"];

    let (units_110, scan_110) = parse_and_scan(&up[..110]);
    assert_eq!(
        judge_from_scan(0, &scan_110, &units_110).kind(),
        FormationKind::Consolidation
    );

    let (units_111, scan_111) = parse_and_scan(&up[..111]);
    match judge_from_scan(0, &scan_111, &units_111) {
        TrendFormation::UpTrendFormed(ev) => {
            let p = ev.forming_pair();
            assert!(p.center_a().is_settled());
            assert!(!p.center_b().is_settled(), "第 111 根 B 仍开放");
            assert_eq!(p.center_a().center().gg, 5500);
            assert_eq!(p.center_b().center().dd, 5600);
            assert!(p.center_b().center().dd > p.center_a().center().gg);
            assert_eq!(p.connector_unit_range(), 4..5);
            assert_eq!(p.connector_coord_span(), (49, 61));
            assert_eq!(p.connectors()[0].unit.direction, Direction::Down);
        }
        other => panic!("镜像第 111 根应读到严格分离的上涨形成（B 开放），实际 {other:?}"),
    }

    let (units_123, scan_123) = parse_and_scan(&up[..123]);
    assert_eq!(units_123[8].start_index, 97);
    assert_eq!(units_123[8].end_index, 109);
    match judge_from_scan(0, &scan_123, &units_123) {
        TrendFormation::UpTrendFormed(ev) => {
            let p = ev.forming_pair();
            assert!(ev.is_settled());
            assert_eq!(
                p.center_a().center().dd,
                exp_up["a"]["dd"].as_i64().unwrap()
            );
            assert_eq!(
                p.center_a().center().zd,
                exp_up["a"]["zd"].as_i64().unwrap()
            );
            assert_eq!(
                p.center_a().center().zg,
                exp_up["a"]["zg"].as_i64().unwrap()
            );
            assert_eq!(
                p.center_a().center().gg,
                exp_up["a"]["gg"].as_i64().unwrap()
            );
            assert_eq!(
                p.center_b().center().dd,
                exp_up["b"]["dd"].as_i64().unwrap()
            );
            assert_eq!(
                p.center_b().center().zd,
                exp_up["b"]["zd"].as_i64().unwrap()
            );
            assert_eq!(
                p.center_b().center().zg,
                exp_up["b"]["zg"].as_i64().unwrap()
            );
            assert_eq!(
                p.center_b().center().gg,
                exp_up["b"]["gg"].as_i64().unwrap()
            );
            assert!(p.center_b().center().dd > p.center_a().center().gg);
            assert_eq!(p.center_b().break_unit(), Some(8));
            assert_eq!(p.connector_unit_range(), 4..5);
            assert_eq!(p.connector_coord_span(), (49, 61));
            assert_eq!(
                p.connectors()[0].unit.direction,
                parse_direction(exp_up["connector_direction"].as_str().unwrap())
            );
            assert_eq!(
                p.pair_facts().leaf.as_str(),
                exp_up["leaf"].as_str().unwrap()
            );

            // R26 负控：全成员外缘使 A.GG 升至 6000，退回扩展交上级。
            let full_a_gg = units_123[0..4].iter().map(|u| u.hi).max().unwrap();
            assert_eq!(full_a_gg, exp_up["full_outer_a_gg"].as_i64().unwrap());
            let wrong_a = CenterEvidence::try_new(
                0,
                0..4,
                Center {
                    gg: full_a_gg,
                    ..p.center_a().center()
                },
                CenterSettlement::Settled { break_unit: 4 },
            )
            .unwrap();
            let wrong_chain = judge_from_center_chain(
                0,
                &[
                    ChainCenterInput::Normal(wrong_a),
                    ChainCenterInput::Normal(p.center_b().clone()),
                ],
                &[p.connectors().to_vec()],
            )
            .unwrap();
            assert_eq!(wrong_chain.kind(), FormationKind::HandoffToUpperLevel);
        }
        other => panic!("镜像第 123 根应判上涨形成，实际 {other:?}"),
    }
}

/// 验收 3：9011 链 1262→1527→1883（合成，取自 #1426 评论中枢级数值）中，非相邻 A→C
/// （C.DD−A.GG = +8051）不得判趋势：只有相邻中枢对 A→B、B→C 参与且均为向上扩展交上级。
#[test]
fn chain_9011_synthetic_non_adjacent_ac_never_forms_trend() {
    let d = doc();
    let chain = &d["chain_9011_synthetic"];
    assert_eq!(
        chain["synthetic"].as_bool(),
        Some(true),
        "9011 夹具必须明确标注为合成中枢级数值"
    );

    let raw_centers = chain["centers"].as_array().unwrap();
    let raw_conns = chain["connectors"].as_array().unwrap();
    let exp = &chain["expected"];

    let mk_center = |w: usize, v: &Value| {
        let base_u = w * 4;
        CenterEvidence::try_new(
            w,
            base_u..base_u + 3,
            Center {
                dd: v["dd"].as_i64().unwrap(),
                zd: v["zd"].as_i64().unwrap(),
                zg: v["zg"].as_i64().unwrap(),
                gg: v["gg"].as_i64().unwrap(),
                start_index: v["start_index"].as_u64().unwrap() as usize,
                end_index: v["end_index"].as_u64().unwrap() as usize,
            },
            CenterSettlement::Settled {
                break_unit: base_u + 3,
            },
        )
        .unwrap()
    };

    let c_a = mk_center(0, &raw_centers[0]);
    let c_b = mk_center(1, &raw_centers[1]);
    let c_c = mk_center(2, &raw_centers[2]);

    // 先验证反事实前提：跳过 B 时 C.DD − A.GG = 32149 − 24098 = +8051，裸看像向上新生。
    assert_eq!(
        c_c.center().dd - c_a.center().gg,
        exp["non_adjacent_ac_outer_diff"].as_i64().unwrap()
    );
    let ac_raw_facts = center_pair_facts(&c_a.center(), &c_c.center());
    assert_eq!(ac_raw_facts.leaf, PairLeaf::UpNewbirth);

    let mk_conn = |unit_idx: usize, v: &Value| ConnectorUnit {
        unit_index: unit_idx,
        unit: UnitRange {
            start_index: v["start_index"].as_u64().unwrap() as usize,
            end_index: v["end_index"].as_u64().unwrap() as usize,
            direction: parse_direction(v["direction"].as_str().unwrap()),
            lo: v["lo"].as_i64().unwrap(),
            hi: v["hi"].as_i64().unwrap(),
        },
    };
    let conn_ab = vec![mk_conn(3, &raw_conns[0])];
    let conn_bc = vec![mk_conn(7, &raw_conns[1])];

    // 类型/边界锁：强行把非相邻的 A(0)→C(2) 送入相邻对构造器必须被拒绝，无法进入形成判定。
    let non_adj_err = AdjacentPairInput::try_new(
        ChainCenterInput::Normal(c_a.clone()),
        ChainCenterInput::Normal(c_c.clone()),
        conn_ab.clone(),
        PairOutcome::Evaluated(ac_raw_facts),
    );
    assert_eq!(
        non_adj_err,
        Err(AdjacentPairError::NonAdjacent { left: 0, right: 2 })
    );

    // 真实相邻链 1262→1527→1883：两对相邻均为 UP_EXPANSION → 交上级，绝不判上涨形成或本级盘整。
    let nodes = vec![
        ChainCenterInput::Normal(c_a),
        ChainCenterInput::Normal(c_b),
        ChainCenterInput::Normal(c_c),
    ];
    let conns = vec![conn_ab, conn_bc];
    let verdict = judge_from_center_chain(0, &nodes, &conns).unwrap();
    match &verdict {
        TrendFormation::HandoffToUpperLevel(ev) => {
            assert_eq!(ev.level(), 0);
            assert_eq!(ev.target_upper_level(), 1);
            let pairs: Vec<_> = ev.all_pairs().collect();
            assert_eq!(pairs.len(), 2);
            assert_eq!(pairs[0].pair_facts().leaf, PairLeaf::UpExpansion);
            assert_eq!(
                pairs[0].center_b().center().zd - pairs[0].center_a().center().zg,
                exp["ab_core_gap"].as_i64().unwrap()
            );
            assert_eq!(
                pairs[0].center_b().center().dd - pairs[0].center_a().center().gg,
                exp["ab_outer_diff"].as_i64().unwrap()
            );
            assert_eq!(pairs[0].connector_coord_span(), (1489, 1527));

            assert_eq!(pairs[1].pair_facts().leaf, PairLeaf::UpExpansion);
            assert_eq!(
                pairs[1].center_b().center().zd - pairs[1].center_a().center().zg,
                exp["bc_core_gap"].as_i64().unwrap()
            );
            assert_eq!(
                pairs[1].center_b().center().dd - pairs[1].center_a().center().gg,
                exp["bc_outer_diff"].as_i64().unwrap()
            );
            assert_eq!(pairs[1].connector_coord_span(), (1815, 1883));
        }
        other => panic!("9011 相邻扩展链应交上级，实际 {other:?}"),
    }
    assert_eq!(
        verdict.kind().as_str(),
        exp["chain_formation_kind"].as_str().unwrap()
    );
    assert_eq!(verdict.direction(), None);

    // 带首枢 301（UPGRADE_PENDING_TB02H）的前缀链：首对未决，后两对各自交上级。
    let p301 = &chain["pending_prefix_center_301"];
    let mut nodes_with_301 = vec![ChainCenterInput::PendingUpgrade {
        window_index: 0,
        member_units: 0..9,
        settlement: CenterSettlement::Settled { break_unit: 9 },
    }];
    let shifted_a = CenterEvidence::try_new(
        1,
        10..13,
        match &nodes[0] {
            ChainCenterInput::Normal(c) => c.center(),
            _ => unreachable!(),
        },
        CenterSettlement::Settled { break_unit: 13 },
    )
    .unwrap();
    let shifted_b = CenterEvidence::try_new(
        2,
        14..17,
        match &nodes[1] {
            ChainCenterInput::Normal(c) => c.center(),
            _ => unreachable!(),
        },
        CenterSettlement::Settled { break_unit: 17 },
    )
    .unwrap();
    let shifted_c = CenterEvidence::try_new(
        3,
        18..21,
        match &nodes[2] {
            ChainCenterInput::Normal(c) => c.center(),
            _ => unreachable!(),
        },
        CenterSettlement::Settled { break_unit: 21 },
    )
    .unwrap();
    nodes_with_301.push(ChainCenterInput::Normal(shifted_a));
    nodes_with_301.push(ChainCenterInput::Normal(shifted_b));
    nodes_with_301.push(ChainCenterInput::Normal(shifted_c));
    let conns_with_301 = vec![
        vec![mk_conn(9, &p301["connector_to_1262"])],
        vec![mk_conn(13, &raw_conns[0])],
        vec![mk_conn(17, &raw_conns[1])],
    ];
    let full_with_301 = judge_from_center_chain(0, &nodes_with_301, &conns_with_301).unwrap();
    match full_with_301 {
        TrendFormation::InsufficientMaterial(ev) => {
            assert_eq!(
                ev.reason(),
                &InsufficientReason::PendingUpgrade {
                    window_indices: vec![0]
                }
            );
        }
        other => panic!("含 301 待升级首枢时整链应报素材不足(待升级)，实际 {other:?}"),
    }
    let per_pair = judge_center_chain_pairs(0, &nodes_with_301, &conns_with_301).unwrap();
    assert_eq!(
        per_pair
            .iter()
            .map(TrendFormation::kind)
            .collect::<Vec<_>>(),
        vec![
            FormationKind::InsufficientMaterial,
            FormationKind::HandoffToUpperLevel,
            FormationKind::HandoffToUpperLevel,
        ]
    );
}

/// 验收 4：扩展对不在本级判盘整、结果为「交上级」；只有单一未升级中枢判盘整；
/// 另覆零中枢、≥9 待升级单枢、核心未严格分离、混合多段链。
#[test]
fn expansion_pair_hands_off_to_upper_level_and_only_single_center_is_consolidation() {
    // 0 中枢 → 素材不足(NoCenter)。
    let no_center_units = units_from_endpoints(&[10, 20, 15]);
    let no_center_scan = scan_center_facts_full(&no_center_units, center_from_segments);
    match judge_from_scan(0, &no_center_scan, &no_center_units) {
        TrendFormation::InsufficientMaterial(ev) => {
            assert_eq!(ev.reason(), &InsufficientReason::NoCenter);
        }
        other => panic!("零中枢应报素材不足，实际 {other:?}"),
    }

    // 单一中枢（开放与已结算）→ 本级盘整，无语义方向。
    let single_open_units = units_from_endpoints(&[10, 40, 20, 35]);
    let single_open_scan = scan_center_facts_full(&single_open_units, center_from_segments);
    match judge_from_scan(0, &single_open_scan, &single_open_units) {
        TrendFormation::Consolidation(ev) => {
            assert_eq!(ev.level(), 0);
            assert!(!ev.is_settled());
            assert_eq!(ev.center().center().zd, 20);
            assert_eq!(ev.center().center().zg, 35);
        }
        other => panic!("单中枢开放态应判盘整，实际 {other:?}"),
    }
    let single_settled_units = units_from_endpoints(&[10, 40, 20, 35, 25, 50, 42]);
    let single_settled_scan = scan_center_facts_full(&single_settled_units, center_from_segments);
    match judge_from_scan(0, &single_settled_scan, &single_settled_units) {
        TrendFormation::Consolidation(ev) => {
            assert!(ev.is_settled());
            assert_eq!(ev.center().break_unit(), Some(5));
        }
        other => panic!("单中枢结算态应判盘整，实际 {other:?}"),
    }

    // ≥9 段单窗口 → 待升级，不得判成当前级别盘整。
    let upgraded_units = units_from_endpoints(&[10, 40, 20, 35, 25, 34, 22, 33, 24, 32]);
    let upgraded_scan = scan_center_facts_full(&upgraded_units, center_from_segments);
    assert_eq!(upgraded_scan.windows.len(), 1);
    assert!(upgraded_scan.windows[0].upgraded);
    match judge_from_scan(0, &upgraded_scan, &upgraded_units) {
        TrendFormation::InsufficientMaterial(ev) => {
            assert_eq!(
                ev.reason(),
                &InsufficientReason::PendingUpgrade {
                    window_indices: vec![0]
                }
            );
        }
        other => panic!("≥9 单窗口不得判本级盘整，实际 {other:?}"),
    }

    // 向上扩展（含外缘重叠与外缘恰等 B.DD == A.GG）：均交上级，绝不判本级盘整或上涨形成。
    // A = u0..u4 (DD=10, ZD=20, ZG=35, GG=45)，u5=[38,45] 结算，B = u6..u8 (DD=38, ZD=42, ZG=48, GG=52) → UP_EXPANSION。
    let up_exp_units = units_from_endpoints(&[10, 40, 20, 35, 25, 45, 38, 52, 42, 48]);
    let up_exp_scan = scan_center_facts_full(&up_exp_units, center_from_segments);
    match judge_from_scan(0, &up_exp_scan, &up_exp_units) {
        TrendFormation::HandoffToUpperLevel(ev) => {
            assert_eq!(ev.level(), 0);
            assert_eq!(ev.target_upper_level(), 1);
            assert_eq!(ev.first_pair().pair_facts().leaf, PairLeaf::UpExpansion);
            assert_eq!(ev.first_pair().connector_unit_range(), 5..6);
        }
        other => panic!("向上扩展对必须交上级，实际 {other:?}"),
    }

    // 外缘恰等（B.DD == A.GG = 40，仍属扩展，`020-第20课.md:58` 后DD=<前GG）。
    let touch_a = CenterEvidence::try_new(
        0,
        0..3,
        Center {
            dd: 10,
            zd: 20,
            zg: 35,
            gg: 40,
            start_index: 0,
            end_index: 12,
        },
        CenterSettlement::Settled { break_unit: 3 },
    )
    .unwrap();
    let touch_b = CenterEvidence::try_new(
        1,
        4..7,
        Center {
            dd: 40,
            zd: 42,
            zg: 50,
            gg: 55,
            start_index: 16,
            end_index: 28,
        },
        CenterSettlement::Open,
    )
    .unwrap();
    let conn = vec![ConnectorUnit {
        unit_index: 3,
        unit: UnitRange {
            start_index: 12,
            end_index: 16,
            direction: Direction::Up,
            lo: 35,
            hi: 45,
        },
    }];
    let pair = AdjacentPairInput::try_new(
        ChainCenterInput::Normal(touch_a),
        ChainCenterInput::Normal(touch_b),
        conn,
        PairOutcome::Evaluated(center_pair_facts(
            &Center {
                dd: 10,
                zd: 20,
                zg: 35,
                gg: 40,
                start_index: 0,
                end_index: 12,
            },
            &Center {
                dd: 40,
                zd: 42,
                zg: 50,
                gg: 55,
                start_index: 16,
                end_index: 28,
            },
        )),
    )
    .unwrap();
    let touch_verdict = judge_adjacent_pair(0, &pair);
    assert_eq!(touch_verdict.kind(), FormationKind::HandoffToUpperLevel);

    // 核心未严格分离（核心相切 B.ZD == A.ZG = 35）：不进 020:58，归素材不足。
    let core_touch_a = CenterEvidence::try_new(
        0,
        0..3,
        Center {
            dd: 10,
            zd: 20,
            zg: 35,
            gg: 40,
            start_index: 0,
            end_index: 12,
        },
        CenterSettlement::Settled { break_unit: 3 },
    )
    .unwrap();
    let core_touch_b = CenterEvidence::try_new(
        1,
        4..7,
        Center {
            dd: 30,
            zd: 35,
            zg: 45,
            gg: 50,
            start_index: 16,
            end_index: 28,
        },
        CenterSettlement::Settled { break_unit: 7 },
    )
    .unwrap();
    let core_touch_res = judge_from_center_chain(
        0,
        &[
            ChainCenterInput::Normal(core_touch_a),
            ChainCenterInput::Normal(core_touch_b),
        ],
        &[vec![ConnectorUnit {
            unit_index: 3,
            unit: UnitRange {
                start_index: 12,
                end_index: 16,
                direction: Direction::Up,
                lo: 36,
                hi: 48,
            },
        }]],
    )
    .unwrap();
    match core_touch_res {
        TrendFormation::InsufficientMaterial(ev) => {
            assert!(matches!(
                ev.reason(),
                InsufficientReason::CoreNotStrictlySeparated { .. }
            ));
        }
        other => panic!("核心未严格分离不得判盘整/趋势/扩展，实际 {other:?}"),
    }

    // 3 中枢混合关系链（A→B 上涨新生，B→C 下跌新生）：整链不自行猜切分点，返回混合关系素材不足。
    let mix_a = CenterEvidence::try_new(
        0,
        0..3,
        Center {
            dd: 10,
            zd: 12,
            zg: 18,
            gg: 20,
            start_index: 0,
            end_index: 12,
        },
        CenterSettlement::Settled { break_unit: 3 },
    )
    .unwrap();
    let mix_b = CenterEvidence::try_new(
        1,
        4..7,
        Center {
            dd: 30,
            zd: 32,
            zg: 38,
            gg: 40,
            start_index: 16,
            end_index: 28,
        },
        CenterSettlement::Settled { break_unit: 7 },
    )
    .unwrap();
    let mix_c = CenterEvidence::try_new(
        2,
        8..11,
        Center {
            dd: 15,
            zd: 17,
            zg: 23,
            gg: 25,
            start_index: 32,
            end_index: 44,
        },
        CenterSettlement::Open,
    )
    .unwrap();
    let mix_conns = vec![
        vec![ConnectorUnit {
            unit_index: 3,
            unit: UnitRange {
                start_index: 12,
                end_index: 16,
                direction: Direction::Up,
                lo: 18,
                hi: 32,
            },
        }],
        vec![ConnectorUnit {
            unit_index: 7,
            unit: UnitRange {
                start_index: 28,
                end_index: 32,
                direction: Direction::Down,
                lo: 23,
                hi: 32,
            },
        }],
    ];
    let mix_verdict = judge_from_center_chain(
        0,
        &[
            ChainCenterInput::Normal(mix_a),
            ChainCenterInput::Normal(mix_b),
            ChainCenterInput::Normal(mix_c),
        ],
        &mix_conns,
    )
    .unwrap();
    match mix_verdict {
        TrendFormation::InsufficientMaterial(ev) => {
            assert_eq!(
                ev.reason(),
                &InsufficientReason::MixedAdjacentRelations {
                    leaves: vec![PairLeaf::UpNewbirth, PairLeaf::DownNewbirth]
                }
            );
        }
        other => panic!("混合多段链应报混合关系素材不足，实际 {other:?}"),
    }
}

/// 验收 5：#804 总缝规则——上下行同判据镜像锁 + 级别只作输入值的级别不变锁。
#[test]
fn rule_804_mirror_and_level_invariance_lock() {
    // 5a. 123 根双向序列逐前缀镜像锁（0..=123 全前缀通过同一 judge_from_scan 函数）。
    let (down, up, d) = fixture_123_bars();
    let offset = d["bars_123_down"]["mirror_offset"].as_i64().unwrap();
    let mut saw_no_center = false;
    let mut saw_consolidation = false;
    let mut saw_trend_open = false;
    let mut saw_trend_settled = false;

    for n in 0..=123 {
        let (u_dn, s_dn) = parse_and_scan(&down[..n]);
        let (u_up, s_up) = parse_and_scan(&up[..n]);
        let r_dn = judge_from_scan(0, &s_dn, &u_dn);
        let r_up = judge_from_scan(0, &s_up, &u_up);

        assert_eq!(
            r_up.kind(),
            r_dn.kind().mirror(),
            "prefix n={n}: 上下行镜像须走同一判据并得镜像标签"
        );
        assert_eq!(
            r_up.direction(),
            r_dn.direction().map(Direction::flip),
            "prefix n={n}: 方向镜像"
        );

        match (&r_dn, &r_up) {
            (TrendFormation::InsufficientMaterial(_), TrendFormation::InsufficientMaterial(_)) => {
                saw_no_center = true;
            }
            (TrendFormation::Consolidation(cd), TrendFormation::Consolidation(cu)) => {
                saw_consolidation = true;
                assert_eq!(cd.center().settlement(), cu.center().settlement());
                assert_eq!(
                    mirror_center(cd.center().center(), offset),
                    cu.center().center()
                );
            }
            (TrendFormation::DownTrendFormed(td), TrendFormation::UpTrendFormed(tu)) => {
                assert_eq!(td.is_settled(), tu.is_settled());
                if td.is_settled() {
                    saw_trend_settled = true;
                } else {
                    saw_trend_open = true;
                }
                assert_mirror_pair(td.forming_pair(), tu.forming_pair(), offset);
            }
            other => panic!("prefix n={n}: 意外镜像对 {other:?}"),
        }
    }
    assert!(
        saw_no_center && saw_consolidation && saw_trend_open && saw_trend_settled,
        "123 根全前缀应覆盖 零中枢/盘整/开放趋势/结算趋势 四阶段"
    );

    // 5b. 合成端点族镜像锁：覆盖 3 中枢延续趋势、扩展、核心未严格分离、≥9 待升级、单枢盘整。
    let mirror_offset = 200;
    let suites: [(&str, &[Tick], FormationKind); 5] = [
        (
            "no_center",
            &[10, 20, 15],
            FormationKind::InsufficientMaterial,
        ),
        (
            "single_consolidation",
            &[10, 40, 20, 35, 25, 50, 42],
            FormationKind::Consolidation,
        ),
        (
            "up_expansion",
            &[10, 40, 20, 35, 25, 45, 38, 52, 42, 48],
            FormationKind::HandoffToUpperLevel,
        ),
        (
            "three_center_up_trend",
            &[40, 10, 35, 20, 60, 55, 65, 45, 55, 48, 90, 80, 105, 85, 100],
            FormationKind::UpTrendFormed,
        ),
        (
            "upgraded_ge9",
            &[10, 40, 20, 35, 25, 34, 22, 33, 24, 32],
            FormationKind::InsufficientMaterial,
        ),
    ];
    for (name, pts, expected_kind) in suites {
        let mirrored_pts: Vec<Tick> = pts.iter().map(|&p| mirror_offset - p).collect();
        let u_a = units_from_endpoints(pts);
        let u_b = units_from_endpoints(&mirrored_pts);
        let s_a = scan_center_facts_full(&u_a, center_from_segments);
        let s_b = scan_center_facts_full(&u_b, center_from_segments);
        let r_a = judge_from_scan(0, &s_a, &u_a);
        let r_b = judge_from_scan(0, &s_b, &u_b);
        assert_eq!(r_a.kind(), expected_kind, "{name}");
        assert_eq!(r_b.kind(), r_a.kind().mirror(), "{name}: 镜像标签一致");
        assert_eq!(
            r_b.direction(),
            r_a.direction().map(Direction::flip),
            "{name}: 镜像方向一致"
        );
        if let (TrendFormation::UpTrendFormed(ea), TrendFormation::DownTrendFormed(eb)) =
            (&r_a, &r_b)
        {
            assert_eq!(ea.center_count(), 3);
            assert_eq!(eb.center_count(), 3);
            assert_eq!(ea.continuation_pairs().len(), 1);
            assert_mirror_pair(ea.forming_pair(), eb.forming_pair(), mirror_offset);
            assert_mirror_pair(
                &ea.continuation_pairs()[0],
                &eb.continuation_pairs()[0],
                mirror_offset,
            );
        }
        if let (TrendFormation::HandoffToUpperLevel(ea), TrendFormation::HandoffToUpperLevel(eb)) =
            (&r_a, &r_b)
        {
            assert_eq!(ea.first_pair().pair_facts().leaf, PairLeaf::UpExpansion);
            assert_eq!(eb.first_pair().pair_facts().leaf, PairLeaf::DownExpansion);
            assert_mirror_pair(ea.first_pair(), eb.first_pair(), mirror_offset);
        }
        // 逐对接口同步验证。
        let ps_a = judge_scan_pairs(0, &s_a, &u_a);
        let ps_b = judge_scan_pairs(0, &s_b, &u_b);
        assert_eq!(ps_a.len(), ps_b.len(), "{name}: 逐对数一致");
        for (pa, pb) in ps_a.iter().zip(&ps_b) {
            assert_eq!(pb.kind(), pa.kind().mirror(), "{name}: 逐对镜像一致");
        }
    }

    // 5c. #804 级别不变锁：同一输入传不同 level 值，判定与依据逐位一致，仅 level 字段不同。
    let (units_123, scan_123) = parse_and_scan(&down[..123]);
    let base = judge_from_scan(0, &scan_123, &units_123);
    for lvl in [1usize, 2, 3, 7] {
        let at_lvl = judge_from_scan(lvl, &scan_123, &units_123);
        assert_eq!(at_lvl.level(), lvl);
        assert_eq!(at_lvl.kind(), base.kind());
        assert_eq!(at_lvl.direction(), base.direction());
        match (&base, &at_lvl) {
            (TrendFormation::DownTrendFormed(b), TrendFormation::DownTrendFormed(cur)) => {
                assert_eq!(b.forming_pair(), cur.forming_pair());
                assert_eq!(b.continuation_pairs(), cur.continuation_pairs());
            }
            _ => unreachable!(),
        }
    }
}
