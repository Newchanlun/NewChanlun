//! #1426 TB-02-G 形成侧验收锁：
//! 1. #1426 2026-11-19 评论 123 根下行序列：第 111 根 B 开放仅报开放期严格分离（不得报已形成），
//!    第 123 根 B 结算并判下跌形成（B.GG=2900 < A.DD=3000）；
//! 2. 8500-p 镜像上行序列：同位置（111 开放期分离、123 结算上涨形成，B.DD=5600 > A.GG=5500）；
//! 3. 202 根追加 OHLC 分叉反例：同前 111 根，B 外缘扩至 3411 越过 A.DD=3000，由开放期分离翻成下行扩展；
//! 4. 9011 链 1262→1527→1883（合成中枢级数值）中非相邻 A→C（C.DD−A.GG=+8051）不得判趋势；
//! 5. 扩展对（含上下双侧外缘恰等相切）交上级、不判盘整；只有单一未升级中枢判盘整；
//! 6. 边界与类型锁：拒绝冒充/重复/倒序连接段、拒绝 ≥9 构造成普通中枢、拒绝 <9 构造成待升级、
//!    保留未决对与混合链完整依据、方向由已验证叶唯一推导；
//! 7. #804 总缝规则：上下行同判据镜像锁（含非对称放宽锁）与级别不变锁。

use serde_json::Value;

use super::super::super::config::ThetaConfig;
use super::super::super::parser::parse_layer;
use super::super::super::types::{Bar, Center, Direction, Tick};
use super::super::center::{center_from_segments, center_pair_facts, PairLeaf, UnitRange};
use super::super::center_scan::{l0_units, scan_center_facts_full, CenterScanFacts, PairOutcome};
use super::super::trend_formation::{
    judge_adjacent_pair, judge_center_chain_pairs, judge_from_center_chain, judge_from_scan,
    judge_scan_pairs, AdjacentPairError, AdjacentPairEvidence, AdjacentPairInput, CenterEvidence,
    CenterEvidenceError, CenterSettlement, ChainCenterInput, ConnectorUnit, FormationKind,
    InsufficientReason, PendingUpgradeError, PendingUpgradeEvidence, TrendFormation,
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

fn parse_and_scan(bars: &[Bar]) -> (Vec<UnitRange>, CenterScanFacts) {
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

fn assert_mirror_pair(a: &AdjacentPairEvidence, b: &AdjacentPairEvidence, offset: Tick) {
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

/// 验收 1：#1426 11-19 评论 123 根下行序列——第 111 根 B 开放仅报开放期严格分离（不得报已形成），
/// 第 123 根 B 结算并判下跌形成（B.GG=2900 < A.DD=3000，连接段 u4 49→61）。
#[test]
fn down_123_bars_prefix_111_reads_strict_separation_and_123_settles_down_trend() {
    let (down, _, d) = fixture_123_bars();
    let exp_down = &d["bars_123_down"]["expected"]["down"];

    // 第 110 根尚只有一个已结算中枢 A：判盘整，未达严格分离。
    let (units_110, scan_110) = parse_and_scan(&down[..110]);
    let f110 = judge_from_scan(0, &scan_110, &units_110);
    assert_eq!(f110.kind(), FormationKind::Consolidation);
    assert_eq!(f110.direction(), None);

    // 第 111 根首次读到严格分离：A 已结算、B 开放，只能报 ProvisionalSeparation，不得报 TrendFormed。
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
    let r111 = judge_from_scan(0, &scan_111, &units_111);
    assert_eq!(
        r111.kind().as_str(),
        exp_down["provisional_kind_at_111"].as_str().unwrap()
    );
    assert_eq!(r111.direction(), None, "开放期严格分离尚未确立趋势方向");
    assert_eq!(r111.observed_direction(), Some(Direction::Down));
    match r111 {
        TrendFormation::ProvisionalSeparation(ev) => {
            let p = ev.forming_pair();
            assert_eq!(ev.level(), 0);
            assert_eq!(ev.observed_direction(), Direction::Down);
            assert!(p.center_a().is_settled());
            assert_eq!(p.center_a().break_unit(), Some(4));
            assert!(!p.center_b().is_settled(), "第 111 根 B 仍开放");
            assert_eq!(ev.open_center().settlement(), CenterSettlement::Open);
            assert_eq!(p.pair_facts().leaf, PairLeaf::DownNewbirth);
            assert_eq!(p.center_a().center().dd, 3000);
            assert_eq!(p.center_b().center().gg, 2900);
            assert!(p.center_b().center().gg < p.center_a().center().dd);
            assert_eq!(p.connector_unit_range(), 4..5);
            assert_eq!(p.connector_coord_span(), (49, 61));
            assert_eq!(p.connectors()[0].unit.direction, Direction::Up);
        }
        other => panic!("第 111 根应报开放期严格分离而非已形成，实际 {other:?}"),
    }

    // 第 123 根原成员与连接段不变，u8 (97→109) 确认 B 结算并判下跌形成。
    let (units_123, scan_123) = parse_and_scan(&down[..123]);
    assert_eq!(units_123[8].start_index, 97);
    assert_eq!(units_123[8].end_index, 109);
    let r123 = judge_from_scan(0, &scan_123, &units_123);
    assert_eq!(
        r123.kind().as_str(),
        exp_down["formation_kind_at_123"].as_str().unwrap()
    );
    assert_eq!(r123.direction(), Some(Direction::Down));
    match r123 {
        TrendFormation::TrendFormed(ev) => {
            let p = ev.forming_pair();
            assert_eq!(ev.level(), 0);
            assert_eq!(ev.direction(), Direction::Down);
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

/// 验收 2：8500-p 镜像上行序列——同位置（111 根开放期分离、123 根 B 结算判上涨形成，B.DD=5600 > A.GG=5500）。
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
    let r111 = judge_from_scan(0, &scan_111, &units_111);
    assert_eq!(
        r111.kind().as_str(),
        exp_up["provisional_kind_at_111"].as_str().unwrap()
    );
    assert_eq!(r111.direction(), None);
    assert_eq!(r111.observed_direction(), Some(Direction::Up));
    match r111 {
        TrendFormation::ProvisionalSeparation(ev) => {
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
        other => panic!("镜像第 111 根应报开放期严格分离，实际 {other:?}"),
    }

    let (units_123, scan_123) = parse_and_scan(&up[..123]);
    assert_eq!(units_123[8].start_index, 97);
    assert_eq!(units_123[8].end_index, 109);
    let r123 = judge_from_scan(0, &scan_123, &units_123);
    assert_eq!(
        r123.kind().as_str(),
        exp_up["formation_kind_at_123"].as_str().unwrap()
    );
    assert_eq!(r123.direction(), Some(Direction::Up));
    match r123 {
        TrendFormation::TrendFormed(ev) => {
            let p = ev.forming_pair();
            assert_eq!(ev.direction(), Direction::Up);
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

/// 独审 HIGH 1 反例锁：保留前 111 根完全不动，仅追加 91 根 OHLC 至第 202 根；
/// 第 111 根 B 开放不得报已形成，第 202 根同一 A、B 核心与连接段 u4 (49→61) 下 B.GG 扩到 3411 ≥ A.DD=3000，
/// 翻转为下行扩展交上级。
#[test]
fn open_b_202_bar_fork_reverts_provisional_separation_to_expansion() {
    let (down, _, d) = fixture_123_bars();
    let fork = &d["open_b_revert_fork_202"];
    let exp = &fork["expected"];
    let spread = d["bars_123_down"]["bar_half_spread"].as_i64().unwrap();
    let prefix_len = fork["prefix_len"].as_u64().unwrap() as usize;
    assert_eq!(prefix_len, 111);

    let mut prices: Vec<Tick> = down[..prefix_len].iter().map(|b| b.close).collect();
    for v in fork["suffix_mid_prices"].as_array().unwrap() {
        prices.push(v.as_i64().unwrap());
    }
    assert_eq!(prices.len(), exp["total_bars"].as_u64().unwrap() as usize);
    let bars = build_bars(&prices, spread);

    // 第 111 根：与原历史同前缀，B 开放，只能是 ProvisionalSeparation，绝不是 TrendFormed。
    let (u111, s111) = parse_and_scan(&bars[..111]);
    let r111 = judge_from_scan(0, &s111, &u111);
    assert_eq!(r111.kind().as_str(), exp["kind_at_111"].as_str().unwrap());
    assert!(matches!(r111, TrendFormation::ProvisionalSeparation(_)));

    // 111..=202 整段前缀中，B 开放期从未报错报成 TrendFormed；至第 202 根翻成 DownExpansion。
    for n in 111..=bars.len() {
        let (u, s) = parse_and_scan(&bars[..n]);
        let r = judge_from_scan(0, &s, &u);
        assert!(
            !matches!(r, TrendFormation::TrendFormed(_)),
            "分叉前缀 n={n} 上 B 未结算且终将翻为扩展，绝不得报 TrendFormed，实际 {r:?}"
        );
    }

    let (u202, s202) = parse_and_scan(&bars);
    let r202 = judge_from_scan(0, &s202, &u202);
    assert_eq!(r202.kind().as_str(), exp["kind_at_202"].as_str().unwrap());
    match r202 {
        TrendFormation::HandoffToUpperLevel(ev) => {
            let p = ev.first_pair();
            assert_eq!(
                p.pair_facts().leaf.as_str(),
                exp["leaf_at_202"].as_str().unwrap()
            );
            assert_eq!(p.center_a().center().dd, exp["a_dd"].as_i64().unwrap());
            assert_eq!(p.center_b().center().zd, exp["b_zd"].as_i64().unwrap());
            assert_eq!(p.center_b().center().zg, exp["b_zg"].as_i64().unwrap());
            assert_eq!(
                p.center_b().center().gg,
                exp["b_gg_at_202"].as_i64().unwrap()
            );
            assert!(p.center_b().center().gg >= p.center_a().center().dd);
            assert_eq!(p.center_b().member_units(), 5..10);
            assert!(!p.center_b().is_settled());
            assert_eq!(p.connector_unit_range(), 4..5);
            assert_eq!(p.connector_coord_span(), (49, 61));
        }
        other => panic!("第 202 根应翻转为下行扩展交上级，实际 {other:?}"),
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

    let mk_center = |w: usize, base_u: usize, v: &Value| {
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

    let c_a = mk_center(0, 0, &raw_centers[0]);
    let c_b = mk_center(1, 4, &raw_centers[1]);
    let c_c = mk_center(2, 8, &raw_centers[2]);

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

    // 带首枢 301（11 成员对齐冻结 CC-016，UPGRADE_PENDING_TB02H）的前缀链：从夹具读取成员数与突破段。
    let p301 = &chain["pending_prefix_center_301"];
    let p301_start = p301["member_units"][0].as_u64().unwrap() as usize;
    let p301_end = p301["member_units"][1].as_u64().unwrap() as usize;
    let p301_break = p301["break_unit"].as_u64().unwrap() as usize;
    assert_eq!(
        p301_end - p301_start,
        p301["member_count"].as_u64().unwrap() as usize
    );
    assert_eq!(p301_end - p301_start, 11, "与冻结 301 实际 11 成员对齐");
    assert_eq!(p301["actual_member_ids"].as_array().unwrap().len(), 11);

    let pending_301 = PendingUpgradeEvidence::try_new(
        p301["window_index"].as_u64().unwrap() as usize,
        p301_start..p301_end,
        CenterSettlement::Settled {
            break_unit: p301_break,
        },
    )
    .unwrap();
    let shifted_a = mk_center(1, p301_break + 1, &raw_centers[0]);
    let shifted_b = mk_center(2, p301_break + 5, &raw_centers[1]);
    let shifted_c = mk_center(3, p301_break + 9, &raw_centers[2]);

    let nodes_with_301 = vec![
        ChainCenterInput::PendingUpgrade(pending_301.clone()),
        ChainCenterInput::Normal(shifted_a.clone()),
        ChainCenterInput::Normal(shifted_b),
        ChainCenterInput::Normal(shifted_c),
    ];
    let conns_with_301 = vec![
        vec![mk_conn(p301_break, &p301["connector_to_1262"])],
        vec![mk_conn(p301_break + 4, &raw_conns[0])],
        vec![mk_conn(p301_break + 8, &raw_conns[1])],
    ];
    let full_with_301 = judge_from_center_chain(0, &nodes_with_301, &conns_with_301).unwrap();
    match full_with_301 {
        TrendFormation::InsufficientMaterial(ev) => match ev.reason() {
            InsufficientReason::PendingUpgradePairs {
                upgraded_windows,
                pairs,
            } => {
                assert_eq!(upgraded_windows, std::slice::from_ref(&pending_301));
                assert_eq!(pairs.len(), 1);
                assert_eq!(
                    pairs[0].left(),
                    &ChainCenterInput::PendingUpgrade(pending_301)
                );
                assert_eq!(pairs[0].right(), &ChainCenterInput::Normal(shifted_a));
                assert_eq!(pairs[0].connector_unit_range(), p301_break..p301_break + 1);
                assert_eq!(pairs[0].connector_coord_span(), (1212, 1262));
            }
            other => panic!("应保留待升级窗口与首对依据，实际 {other:?}"),
        },
        other => panic!("含 301 待升级首枢时整链应报素材不足(待升级对)，实际 {other:?}"),
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

/// 验收 4：扩展对（含上行与下行双侧外缘恰等相切）不在本级判盘整、结果为「交上级」；
/// 只有单一未升级中枢判盘整；另覆零中枢、≥9 待升级单枢、核心未严格分离、混合多段链。
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

    // ≥9 段单窗口 → 待升级窗口，不得判成当前级别盘整。
    let upgraded_units = units_from_endpoints(&[10, 40, 20, 35, 25, 34, 22, 33, 24, 32]);
    let upgraded_scan = scan_center_facts_full(&upgraded_units, center_from_segments);
    assert_eq!(upgraded_scan.windows.len(), 1);
    assert!(upgraded_scan.windows[0].upgraded);
    match judge_from_scan(0, &upgraded_scan, &upgraded_units) {
        TrendFormation::InsufficientMaterial(ev) => match ev.reason() {
            InsufficientReason::PendingUpgradeWindow { window } => {
                assert_eq!(window.window_index(), 0);
                assert_eq!(window.member_units(), 0..9);
            }
            other => panic!("应报 PendingUpgradeWindow，实际 {other:?}"),
        },
        other => panic!("≥9 单窗口不得判本级盘整，实际 {other:?}"),
    }

    // 向上扩展（外缘重叠）：交上级，绝不判本级盘整或上涨形成。
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

    // 双向外缘恰等相切（LOW 1 非对称放宽锁）：
    // 上行外缘恰等 B.DD == A.GG = 40（且核心严格分离 B.ZD=42 > A.ZG=35）→ UP_EXPANSION 交上级；
    // 下行外缘恰等 B.GG == A.DD = 60（且核心严格分离 B.ZG=58 < A.ZD=65）→ DOWN_EXPANSION 交上级。
    let up_touch_a = Center {
        dd: 10,
        zd: 20,
        zg: 35,
        gg: 40,
        start_index: 0,
        end_index: 12,
    };
    let up_touch_b = Center {
        dd: 40,
        zd: 42,
        zg: 50,
        gg: 55,
        start_index: 16,
        end_index: 28,
    };
    let up_touch_pair = AdjacentPairInput::try_new(
        ChainCenterInput::Normal(
            CenterEvidence::try_new(
                0,
                0..3,
                up_touch_a,
                CenterSettlement::Settled { break_unit: 3 },
            )
            .unwrap(),
        ),
        ChainCenterInput::Normal(
            CenterEvidence::try_new(
                1,
                4..7,
                up_touch_b,
                CenterSettlement::Settled { break_unit: 7 },
            )
            .unwrap(),
        ),
        vec![ConnectorUnit {
            unit_index: 3,
            unit: UnitRange {
                start_index: 12,
                end_index: 16,
                direction: Direction::Up,
                lo: 35,
                hi: 45,
            },
        }],
        PairOutcome::Evaluated(center_pair_facts(&up_touch_a, &up_touch_b)),
    )
    .unwrap();
    match judge_adjacent_pair(0, &up_touch_pair) {
        TrendFormation::HandoffToUpperLevel(ev) => {
            assert_eq!(ev.first_pair().pair_facts().leaf, PairLeaf::UpExpansion);
        }
        other => panic!("上行外缘恰等（B.DD == A.GG）必须交上级，实际 {other:?}"),
    }

    let down_touch_a = mirror_center(up_touch_a, 100);
    let down_touch_b = mirror_center(up_touch_b, 100);
    assert_eq!(down_touch_b.gg, down_touch_a.dd);
    assert!(down_touch_b.zg < down_touch_a.zd);
    let down_touch_pair = AdjacentPairInput::try_new(
        ChainCenterInput::Normal(
            CenterEvidence::try_new(
                0,
                0..3,
                down_touch_a,
                CenterSettlement::Settled { break_unit: 3 },
            )
            .unwrap(),
        ),
        ChainCenterInput::Normal(
            CenterEvidence::try_new(
                1,
                4..7,
                down_touch_b,
                CenterSettlement::Settled { break_unit: 7 },
            )
            .unwrap(),
        ),
        vec![ConnectorUnit {
            unit_index: 3,
            unit: UnitRange {
                start_index: 12,
                end_index: 16,
                direction: Direction::Down,
                lo: 55,
                hi: 65,
            },
        }],
        PairOutcome::Evaluated(center_pair_facts(&down_touch_a, &down_touch_b)),
    )
    .unwrap();
    match judge_adjacent_pair(0, &down_touch_pair) {
        TrendFormation::HandoffToUpperLevel(ev) => {
            assert_eq!(ev.first_pair().pair_facts().leaf, PairLeaf::DownExpansion);
        }
        other => panic!("下行外缘恰等（B.GG == A.DD）必须交上级，实际 {other:?}"),
    }

    // 核心相切（上下两向均测）：B.ZD == A.ZG 与 B.ZG == A.ZD 均不进 020:58，归 CoreNotStrictlySeparated。
    for (ca, cb, dir) in [
        (
            Center {
                dd: 10,
                zd: 20,
                zg: 35,
                gg: 40,
                start_index: 0,
                end_index: 12,
            },
            Center {
                dd: 30,
                zd: 35,
                zg: 45,
                gg: 50,
                start_index: 16,
                end_index: 28,
            },
            Direction::Up,
        ),
        (
            Center {
                dd: 60,
                zd: 65,
                zg: 80,
                gg: 90,
                start_index: 0,
                end_index: 12,
            },
            Center {
                dd: 50,
                zd: 55,
                zg: 65,
                gg: 70,
                start_index: 16,
                end_index: 28,
            },
            Direction::Down,
        ),
    ] {
        let res = judge_from_center_chain(
            0,
            &[
                ChainCenterInput::Normal(
                    CenterEvidence::try_new(
                        0,
                        0..3,
                        ca,
                        CenterSettlement::Settled { break_unit: 3 },
                    )
                    .unwrap(),
                ),
                ChainCenterInput::Normal(
                    CenterEvidence::try_new(
                        1,
                        4..7,
                        cb,
                        CenterSettlement::Settled { break_unit: 7 },
                    )
                    .unwrap(),
                ),
            ],
            &[vec![ConnectorUnit {
                unit_index: 3,
                unit: UnitRange {
                    start_index: 12,
                    end_index: 16,
                    direction: dir,
                    lo: 36,
                    hi: 64,
                },
            }]],
        )
        .unwrap();
        match res {
            TrendFormation::InsufficientMaterial(ev) => {
                assert!(matches!(
                    ev.reason(),
                    InsufficientReason::CoreNotStrictlySeparated { .. }
                ));
            }
            other => panic!("核心相切不得判盘整/趋势/扩展，实际 {other:?}"),
        }
    }

    // 3 中枢混合关系链（A→B 上涨新生，B→C 下跌新生）：整链不猜切分点，返回混合关系并完整保留两对依据。
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
        CenterSettlement::Settled { break_unit: 11 },
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
        TrendFormation::InsufficientMaterial(ev) => match ev.reason() {
            InsufficientReason::MixedAdjacentRelations { pairs } => {
                assert_eq!(pairs.len(), 2);
                assert_eq!(pairs[0].pair_facts().leaf, PairLeaf::UpNewbirth);
                assert_eq!(pairs[0].connector_unit_range(), 3..4);
                assert_eq!(pairs[1].pair_facts().leaf, PairLeaf::DownNewbirth);
                assert_eq!(pairs[1].connector_unit_range(), 7..8);
            }
            other => panic!("应保留混合链两对完整依据，实际 {other:?}"),
        },
        other => panic!("混合多段链应报混合关系素材不足，实际 {other:?}"),
    }
}

/// 独审 HIGH 2 / HIGH 3 / MED 1 / MED 2 全反例回归锁。
#[test]
fn boundary_rejects_invalid_connectors_ge9_normal_and_preserves_pending_identity() {
    let (down, _, _) = fixture_123_bars();
    let (units_123, scan_123) = parse_and_scan(&down[..123]);
    let center_a = CenterEvidence::try_new(
        0,
        0..4,
        scan_123.window_center(&units_123, 0),
        CenterSettlement::Settled { break_unit: 4 },
    )
    .unwrap();
    let center_b = CenterEvidence::try_new(
        1,
        5..8,
        scan_123.window_center(&units_123, 1),
        CenterSettlement::Settled { break_unit: 8 },
    )
    .unwrap();
    let facts_ab = center_pair_facts(&center_a.center(), &center_b.center());

    // HIGH 2a：用 A 自己的成员 u1 (13→25) 冒充连接段 → 必须拒绝。
    let fake_u1 = ConnectorUnit {
        unit_index: 1,
        unit: units_123[1],
    };
    assert_eq!(
        AdjacentPairInput::try_new(
            ChainCenterInput::Normal(center_a.clone()),
            ChainCenterInput::Normal(center_b.clone()),
            vec![fake_u1],
            PairOutcome::Evaluated(facts_ab),
        ),
        Err(AdjacentPairError::InvalidConnectors {
            expected_start: 4,
            expected_end: 5,
        })
    );

    // HIGH 2b：伪造 unit_index=4 但塞入 u1 的原始坐标 (13→25) → 坐标序校验必须拒绝。
    let forged_coord_u4 = ConnectorUnit {
        unit_index: 4,
        unit: units_123[1],
    };
    assert_eq!(
        AdjacentPairInput::try_new(
            ChainCenterInput::Normal(center_a.clone()),
            ChainCenterInput::Normal(center_b.clone()),
            vec![forged_coord_u4],
            PairOutcome::Evaluated(facts_ab),
        ),
        Err(AdjacentPairError::InvalidConnectorCoordinates)
    );

    // HIGH 2c：重复与倒序连接段 [u4, u4, u1] → 必须拒绝，不可能导出倒置区间 4..2。
    let real_u4 = ConnectorUnit {
        unit_index: 4,
        unit: units_123[4],
    };
    assert_eq!(
        AdjacentPairInput::try_new(
            ChainCenterInput::Normal(center_a.clone()),
            ChainCenterInput::Normal(center_b.clone()),
            vec![real_u4, real_u4, fake_u1],
            PairOutcome::Evaluated(facts_ab),
        ),
        Err(AdjacentPairError::InvalidConnectors {
            expected_start: 4,
            expected_end: 5,
        })
    );

    // HIGH 2d：正常多单元连接段（4..6）缺段或倒序拒绝、升序全集接受。
    let gap_a = CenterEvidence::try_new(
        0,
        0..4,
        Center {
            dd: 10,
            zd: 20,
            zg: 35,
            gg: 40,
            start_index: 0,
            end_index: 16,
        },
        CenterSettlement::Settled { break_unit: 4 },
    )
    .unwrap();
    let gap_b = CenterEvidence::try_new(
        1,
        6..9,
        Center {
            dd: 45,
            zd: 48,
            zg: 55,
            gg: 65,
            start_index: 24,
            end_index: 36,
        },
        CenterSettlement::Settled { break_unit: 9 },
    )
    .unwrap();
    let gap_facts = center_pair_facts(&gap_a.center(), &gap_b.center());
    let u4 = ConnectorUnit {
        unit_index: 4,
        unit: UnitRange {
            start_index: 16,
            end_index: 20,
            direction: Direction::Down,
            lo: 50,
            hi: 60,
        },
    };
    let u5 = ConnectorUnit {
        unit_index: 5,
        unit: UnitRange {
            start_index: 20,
            end_index: 24,
            direction: Direction::Up,
            lo: 45,
            hi: 65,
        },
    };
    assert_eq!(
        AdjacentPairInput::try_new(
            ChainCenterInput::Normal(gap_a.clone()),
            ChainCenterInput::Normal(gap_b.clone()),
            vec![u4],
            PairOutcome::Evaluated(gap_facts),
        ),
        Err(AdjacentPairError::InvalidConnectors {
            expected_start: 4,
            expected_end: 6,
        })
    );
    assert_eq!(
        AdjacentPairInput::try_new(
            ChainCenterInput::Normal(gap_a.clone()),
            ChainCenterInput::Normal(gap_b.clone()),
            vec![u5, u4],
            PairOutcome::Evaluated(gap_facts),
        ),
        Err(AdjacentPairError::InvalidConnectors {
            expected_start: 4,
            expected_end: 6,
        })
    );
    let ok_multi = AdjacentPairInput::try_new(
        ChainCenterInput::Normal(gap_a),
        ChainCenterInput::Normal(gap_b),
        vec![u4, u5],
        PairOutcome::Evaluated(gap_facts),
    )
    .unwrap();
    match judge_adjacent_pair(0, &ok_multi) {
        TrendFormation::TrendFormed(ev) => {
            assert_eq!(ev.forming_pair().connector_unit_range(), 4..6);
            assert_eq!(ev.forming_pair().connector_coord_span(), (16, 24));
        }
        other => panic!("合法双单元连接段应判已形成，实际 {other:?}"),
    }

    // HIGH 3：同一 9 段端点流 [11,42,22,37,29,36,25,34,27,33]（level 2），扫描入口与公开构造器必须一致。
    let nine_units = units_from_endpoints(&[11, 42, 22, 37, 29, 36, 25, 34, 27, 33]);
    let nine_scan = scan_center_facts_full(&nine_units, center_from_segments);
    assert_eq!(nine_scan.windows.len(), 1);
    assert!(nine_scan.windows[0].upgraded);
    let scan_verdict = judge_from_scan(2, &nine_scan, &nine_units);
    assert_eq!(scan_verdict.kind(), FormationKind::InsufficientMaterial);

    let nine_center = nine_scan.window_center(&nine_units, 0);
    assert_eq!(
        CenterEvidence::try_new(0, 0..9, nine_center, CenterSettlement::Open),
        Err(CenterEvidenceError::RequiresUpgrade {
            count: 9,
            threshold: 9,
        })
    );
    assert_eq!(
        PendingUpgradeEvidence::try_new(0, 0..8, CenterSettlement::Open),
        Err(PendingUpgradeError::BelowUpgradeThreshold {
            count: 8,
            threshold: 9,
        })
    );
    let pending_nine = PendingUpgradeEvidence::try_new(0, 0..9, CenterSettlement::Open).unwrap();
    let chain_verdict =
        judge_from_center_chain(2, &[ChainCenterInput::PendingUpgrade(pending_nine)], &[]).unwrap();
    assert_eq!(chain_verdict, scan_verdict);

    // MED 1：下跌依据重新包进 TrendFormation::TrendFormed 仍恒推导出 Down，不可伪造上涨方向。
    let r123 = judge_from_scan(0, &scan_123, &units_123);
    if let TrendFormation::TrendFormed(ev) = r123 {
        let rewrapped = TrendFormation::TrendFormed(ev);
        assert_eq!(rewrapped.direction(), Some(Direction::Down));
        assert_eq!(rewrapped.kind(), FormationKind::DownTrendFormed);
    } else {
        panic!("123 根应为 TrendFormed");
    }

    // MED 2a：A(Normal) → B(PendingUpgrade) 经 u3 与 B(PendingUpgrade) → C(Normal) 经 u13 必须可区分。
    let c = Center {
        dd: 10,
        zd: 21,
        zg: 34,
        gg: 41,
        start_index: 0,
        end_index: 12,
    };
    let node_a = ChainCenterInput::Normal(
        CenterEvidence::try_new(0, 0..3, c, CenterSettlement::Settled { break_unit: 3 }).unwrap(),
    );
    let node_b = ChainCenterInput::PendingUpgrade(
        PendingUpgradeEvidence::try_new(1, 4..13, CenterSettlement::Settled { break_unit: 13 })
            .unwrap(),
    );
    let node_c = ChainCenterInput::Normal(
        CenterEvidence::try_new(
            2,
            14..17,
            Center {
                start_index: 56,
                end_index: 68,
                ..c
            },
            CenterSettlement::Open,
        )
        .unwrap(),
    );
    let mk_u = |i: usize| {
        vec![ConnectorUnit {
            unit_index: i,
            unit: UnitRange {
                start_index: 4 * i,
                end_index: 4 * i + 4,
                direction: Direction::Down,
                lo: 20,
                hi: 33,
            },
        }]
    };
    let pair_verdicts = judge_center_chain_pairs(
        0,
        &[node_a.clone(), node_b.clone(), node_c.clone()],
        &[mk_u(3), mk_u(13)],
    )
    .unwrap();
    assert_eq!(pair_verdicts.len(), 2);
    assert_ne!(
        pair_verdicts[0], pair_verdicts[1],
        "A→B (u3) 与 B→C (u13) 两个未决对不得碰撞相等"
    );
    match (&pair_verdicts[0], &pair_verdicts[1]) {
        (TrendFormation::InsufficientMaterial(e0), TrendFormation::InsufficientMaterial(e1)) => {
            match (e0.reason(), e1.reason()) {
                (
                    InsufficientReason::PendingUpgradePairs { pairs: p0, .. },
                    InsufficientReason::PendingUpgradePairs { pairs: p1, .. },
                ) => {
                    assert_eq!(p0[0].left(), &node_a);
                    assert_eq!(p0[0].right(), &node_b);
                    assert_eq!(p0[0].connector_unit_range(), 3..4);
                    assert_eq!(p1[0].left(), &node_b);
                    assert_eq!(p1[0].right(), &node_c);
                    assert_eq!(p1[0].connector_unit_range(), 13..14);
                }
                other => panic!("应为 PendingUpgradePairs，实际 {other:?}"),
            }
        }
        other => panic!("两对均应为 InsufficientMaterial，实际 {other:?}"),
    }

    // MED 2b：两条同叶序但不同中枢/价格的混合链，返回值不得相等。
    let mk_mixed = |shift: Tick| {
        let a = CenterEvidence::try_new(
            0,
            0..3,
            Center {
                dd: 10 + shift,
                zd: 12 + shift,
                zg: 18 + shift,
                gg: 20 + shift,
                start_index: 0,
                end_index: 12,
            },
            CenterSettlement::Settled { break_unit: 3 },
        )
        .unwrap();
        let b = CenterEvidence::try_new(
            1,
            4..7,
            Center {
                dd: 30 + shift,
                zd: 32 + shift,
                zg: 38 + shift,
                gg: 40 + shift,
                start_index: 16,
                end_index: 28,
            },
            CenterSettlement::Settled { break_unit: 7 },
        )
        .unwrap();
        let z = CenterEvidence::try_new(
            2,
            8..11,
            Center {
                dd: 15 + shift,
                zd: 17 + shift,
                zg: 23 + shift,
                gg: 25 + shift,
                start_index: 32,
                end_index: 44,
            },
            CenterSettlement::Settled { break_unit: 11 },
        )
        .unwrap();
        judge_from_center_chain(
            0,
            &[
                ChainCenterInput::Normal(a),
                ChainCenterInput::Normal(b),
                ChainCenterInput::Normal(z),
            ],
            &[
                vec![ConnectorUnit {
                    unit_index: 3,
                    unit: UnitRange {
                        start_index: 12,
                        end_index: 16,
                        direction: Direction::Up,
                        lo: 18 + shift,
                        hi: 32 + shift,
                    },
                }],
                vec![ConnectorUnit {
                    unit_index: 7,
                    unit: UnitRange {
                        start_index: 28,
                        end_index: 32,
                        direction: Direction::Down,
                        lo: 23 + shift,
                        hi: 32 + shift,
                    },
                }],
            ],
        )
        .unwrap()
    };
    assert_ne!(
        mk_mixed(0),
        mk_mixed(100),
        "同叶序不同依据的混合链不得碰撞相等"
    );
}

/// 验收 5：#804 总缝规则——上下行同判据镜像锁（含独立四类非对称对双向镜像）与级别不变锁。
#[test]
fn rule_804_mirror_and_level_invariance_lock() {
    // 5a. 123 根双向序列逐前缀镜像锁（0..=123 全前缀通过同一 judge_from_scan 函数）。
    let (down, up, d) = fixture_123_bars();
    let offset = d["bars_123_down"]["mirror_offset"].as_i64().unwrap();
    let mut saw_no_center = false;
    let mut saw_consolidation = false;
    let mut saw_provisional = false;
    let mut saw_formed = false;

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
            "prefix n={n}: 已确立趋势方向镜像"
        );
        assert_eq!(
            r_up.observed_direction(),
            r_dn.observed_direction().map(Direction::flip),
            "prefix n={n}: 可观察分离方向镜像"
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
            (
                TrendFormation::ProvisionalSeparation(pd),
                TrendFormation::ProvisionalSeparation(pu),
            ) => {
                saw_provisional = true;
                assert_eq!(pd.observed_direction(), Direction::Down);
                assert_eq!(pu.observed_direction(), Direction::Up);
                assert_mirror_pair(pd.forming_pair(), pu.forming_pair(), offset);
            }
            (TrendFormation::TrendFormed(td), TrendFormation::TrendFormed(tu)) => {
                saw_formed = true;
                assert_eq!(td.direction(), Direction::Down);
                assert_eq!(tu.direction(), Direction::Up);
                assert_mirror_pair(td.forming_pair(), tu.forming_pair(), offset);
            }
            other => panic!("prefix n={n}: 意外镜像对 {other:?}"),
        }
    }
    assert!(
        saw_no_center && saw_consolidation && saw_provisional && saw_formed,
        "123 根全前缀应覆盖 零中枢/盘整/开放期分离/结算形成 四阶段"
    );

    // 5b. 合成端点族镜像锁：覆盖 3 中枢开放期分离、3 中枢全结算延续趋势、扩展、≥9 待升级、单枢盘整。
    let mirror_offset = 200;
    let suites: [(&str, &[Tick], FormationKind); 6] = [
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
            "three_center_up_open_c",
            &[40, 10, 35, 20, 60, 55, 65, 45, 55, 48, 90, 80, 105, 85, 100],
            FormationKind::ProvisionalUpSeparation,
        ),
        (
            "three_center_up_settled",
            &[
                40, 10, 35, 20, 60, 55, 65, 45, 55, 48, 90, 80, 105, 85, 100, 82, 120, 110,
            ],
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
        if let (TrendFormation::TrendFormed(ea), TrendFormation::TrendFormed(eb)) = (&r_a, &r_b) {
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
        let ps_a = judge_scan_pairs(0, &s_a, &u_a);
        let ps_b = judge_scan_pairs(0, &s_b, &u_b);
        assert_eq!(ps_a.len(), ps_b.len(), "{name}: 逐对数一致");
        for (pa, pb) in ps_a.iter().zip(&ps_b) {
            assert_eq!(pb.kind(), pa.kind().mirror(), "{name}: 逐对镜像一致");
        }
    }

    // 5c. 独立四类非对称对双向镜像（严格新生、外缘恰等扩展、外缘穿入扩展、核心相切不足）跨 level 0/2/8。
    let asym_offset = 1003;
    let asym_a = Center {
        dd: 11,
        zd: 23,
        zg: 41,
        gg: 67,
        start_index: 0,
        end_index: 12,
    };
    let asym_cases = [
        (
            "strict_newbirth",
            Center {
                dd: 73,
                zd: 82,
                zg: 83,
                gg: 119,
                start_index: 16,
                end_index: 28,
            },
            FormationKind::UpTrendFormed,
            FormationKind::DownTrendFormed,
        ),
        (
            "outer_touch_expansion",
            Center {
                dd: 67,
                zd: 76,
                zg: 92,
                gg: 135,
                start_index: 16,
                end_index: 28,
            },
            FormationKind::HandoffToUpperLevel,
            FormationKind::HandoffToUpperLevel,
        ),
        (
            "outer_overlap_expansion",
            Center {
                dd: 50,
                zd: 58,
                zg: 71,
                gg: 102,
                start_index: 16,
                end_index: 28,
            },
            FormationKind::HandoffToUpperLevel,
            FormationKind::HandoffToUpperLevel,
        ),
        (
            "core_tangent_insufficient",
            Center {
                dd: 36,
                zd: 41,
                zg: 55,
                gg: 98,
                start_index: 16,
                end_index: 28,
            },
            FormationKind::InsufficientMaterial,
            FormationKind::InsufficientMaterial,
        ),
    ];
    for (name, cb, want_up, want_dn) in asym_cases {
        let ma = mirror_center(asym_a, asym_offset);
        let mb = mirror_center(cb, asym_offset);
        let pair_up = AdjacentPairInput::try_new(
            ChainCenterInput::Normal(
                CenterEvidence::try_new(
                    0,
                    0..3,
                    asym_a,
                    CenterSettlement::Settled { break_unit: 3 },
                )
                .unwrap(),
            ),
            ChainCenterInput::Normal(
                CenterEvidence::try_new(1, 4..7, cb, CenterSettlement::Settled { break_unit: 7 })
                    .unwrap(),
            ),
            vec![ConnectorUnit {
                unit_index: 3,
                unit: UnitRange {
                    start_index: 12,
                    end_index: 16,
                    direction: Direction::Up,
                    lo: 41,
                    hi: 82,
                },
            }],
            PairOutcome::Evaluated(center_pair_facts(&asym_a, &cb)),
        )
        .unwrap();
        let pair_dn = AdjacentPairInput::try_new(
            ChainCenterInput::Normal(
                CenterEvidence::try_new(0, 0..3, ma, CenterSettlement::Settled { break_unit: 3 })
                    .unwrap(),
            ),
            ChainCenterInput::Normal(
                CenterEvidence::try_new(1, 4..7, mb, CenterSettlement::Settled { break_unit: 7 })
                    .unwrap(),
            ),
            vec![ConnectorUnit {
                unit_index: 3,
                unit: UnitRange {
                    start_index: 12,
                    end_index: 16,
                    direction: Direction::Down,
                    lo: asym_offset - 82,
                    hi: asym_offset - 41,
                },
            }],
            PairOutcome::Evaluated(center_pair_facts(&ma, &mb)),
        )
        .unwrap();
        for lvl in [0usize, 2, 8] {
            let ru = judge_adjacent_pair(lvl, &pair_up);
            let rd = judge_adjacent_pair(lvl, &pair_dn);
            assert_eq!(ru.level(), lvl);
            assert_eq!(rd.level(), lvl);
            assert_eq!(ru.kind(), want_up, "{name} lvl={lvl} up");
            assert_eq!(rd.kind(), want_dn, "{name} lvl={lvl} down");
            assert_eq!(rd.kind(), ru.kind().mirror(), "{name} lvl={lvl} mirror");
        }
    }

    // 5d. #804 级别不变锁：同一输入传不同 level 值，判定与依据逐位一致，仅 level 字段不同。
    let (units_123, scan_123) = parse_and_scan(&down[..123]);
    let base = judge_from_scan(0, &scan_123, &units_123);
    for lvl in [1usize, 2, 3, 7] {
        let at_lvl = judge_from_scan(lvl, &scan_123, &units_123);
        assert_eq!(at_lvl.level(), lvl);
        assert_eq!(at_lvl.kind(), base.kind());
        assert_eq!(at_lvl.direction(), base.direction());
        match (&base, &at_lvl) {
            (TrendFormation::TrendFormed(b), TrendFormation::TrendFormed(cur)) => {
                assert_eq!(b.forming_pair(), cur.forming_pair());
                assert_eq!(b.continuation_pairs(), cur.continuation_pairs());
            }
            _ => unreachable!(),
        }
    }
}
