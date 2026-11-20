//! #1426 TB-02-G 形成侧内核 r3 外部集成测试（18 项，对应 `DESIGN.md §10`）。
//!
//! 本文件是外部 crate，只能访问 `newchan_rust::theta_v0::classifier::trend_formation` 的公开面；
//! 不存在任何收证据或构造证据的入口。

use std::collections::BTreeSet;

use serde_json::Value;

use newchan_rust::theta_v0::classifier::center::{
    center_from_segments, center_from_window, PairLeaf, UnitRange,
};
use newchan_rust::theta_v0::classifier::center_scan::{
    l0_units, scan_center_facts_full, PairOutcome,
};
use newchan_rust::theta_v0::classifier::trend_formation::{
    judge_trend_formation, CenterNode, FormedTrend, PairJudgment, PairState, TrendFormation,
    UnitSpan,
};
use newchan_rust::theta_v0::config::ThetaConfig;
use newchan_rust::theta_v0::parser::parse_layer;
use newchan_rust::theta_v0::types::{Bar, Center, Direction, Tick};

const FIXTURE: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/tests/fixtures/trend_formation_1426.json"
));

const TREND_FORMATION_SRC: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/src/theta_v0/classifier/trend_formation.rs"
));

fn doc() -> Value {
    serde_json::from_str(FIXTURE).expect("夹具应为合法 JSON")
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
    assert_eq!(d["schema"].as_str(), Some("tb1426-trend-formation/3"));
    let cfg = &d["bars_123_down"];
    let spread = cfg["bar_half_spread"].as_i64().unwrap();
    let mirror = cfg["mirror_offset"].as_i64().unwrap();
    let prices: Vec<Tick> = cfg["mid_prices"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_i64().unwrap())
        .collect();
    assert_eq!(prices.len(), 123);
    let mirrored: Vec<Tick> = prices.iter().map(|&p| mirror - p).collect();
    (
        build_bars(&prices, spread),
        build_bars(&mirrored, spread),
        d,
    )
}

fn parse_l0_units(bars: &[Bar]) -> Vec<UnitRange> {
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
    l0_units(layer.segments_valid_prefix())
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

fn mirror_units(units: &[UnitRange], offset: Tick) -> Vec<UnitRange> {
    units
        .iter()
        .map(|u| UnitRange {
            start_index: u.start_index,
            end_index: u.end_index,
            direction: u.direction.flip(),
            lo: offset - u.hi,
            hi: offset - u.lo,
        })
        .collect()
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

fn mirror_state(s: PairState) -> PairState {
    match s {
        PairState::TrendFormed { direction } => PairState::TrendFormed {
            direction: direction.flip(),
        },
        PairState::ProvisionalSeparation { observed_direction } => {
            PairState::ProvisionalSeparation {
                observed_direction: observed_direction.flip(),
            }
        }
        PairState::ExpansionHandoff => PairState::ExpansionHandoff,
        PairState::CoreNotStrictlySeparated => PairState::CoreNotStrictlySeparated,
        PairState::UpgradeDeferred => PairState::UpgradeDeferred,
    }
}

fn assert_center_matches_json(actual: Center, exp: &Value) {
    assert_eq!(actual.dd, exp["dd"].as_i64().unwrap());
    assert_eq!(actual.zd, exp["zd"].as_i64().unwrap());
    assert_eq!(actual.zg, exp["zg"].as_i64().unwrap());
    assert_eq!(actual.gg, exp["gg"].as_i64().unwrap());
}

fn assert_monotone_pair(f: &TrendFormation, g: &TrendFormation, transition_hits: &mut [bool; 4]) {
    // M1：G.pairs() 的前 F.final_pairs().len() 项与 F.final_pairs() 逐项相等。
    let fin = f.final_pairs();
    assert!(
        g.pairs().len() >= fin.len(),
        "M1: 终态前缀长度不得回缩 ({} < {})",
        g.pairs().len(),
        fin.len()
    );
    assert_eq!(&g.pairs()[..fin.len()], fin, "M1: 已结算前缀对必须逐项不变");

    // M2：G.centers() 的前 s 项与 F 的逐项相等（s 为 F 中已结算节点数）。
    let fc = f.centers();
    let gc = g.centers();
    let s = fc.iter().filter(|c| c.is_settled()).count();
    assert!(gc.len() >= s, "M2: 已结算节点数不得回缩");
    assert_eq!(&gc[..s], &fc[..s], "M2: 已结算节点前缀必须逐项不变");

    // M3：F 中 TrendFormed 的对在 G 同位置整项相等。
    for (idx, pf) in f.pairs().iter().enumerate() {
        if pf.formed().is_some() {
            assert_eq!(
                &g.pairs()[idx],
                pf,
                "M3: 已形成对在追加单元后同位置必须整项相等"
            );
            assert!(g.pairs()[idx].formed().is_some());
        }
    }

    // M4：只有末节点可以开放。
    for centers in [&fc, &gc] {
        if centers.len() > 1 {
            for node in &centers[..centers.len() - 1] {
                assert!(
                    node.is_settled(),
                    "M4: 非末节点 ordinal={} 必须已结算",
                    node.ordinal()
                );
            }
        }
    }

    // 临时分离的合法后继只有四种：同向已形成、同向临时分离、同向扩展、UpgradeDeferred。
    if let Some(last_f) = f.pairs().last() {
        if let PairState::ProvisionalSeparation { observed_direction } = last_f.state() {
            let idx = f.pairs().len() - 1;
            assert!(g.pairs().len() > idx, "临时分离对在追加后不得消失");
            let next = &g.pairs()[idx];
            match next.state() {
                PairState::TrendFormed { direction } => {
                    assert_eq!(direction, observed_direction, "临时分离→已形成必须同向");
                    transition_hits[0] = true;
                }
                PairState::ProvisionalSeparation {
                    observed_direction: d,
                } => {
                    assert_eq!(d, observed_direction, "临时分离→临时分离必须同向");
                    transition_hits[1] = true;
                }
                PairState::ExpansionHandoff => {
                    let PairOutcome::Evaluated(facts) = next.outcome() else {
                        panic!("ExpansionHandoff 必为 Evaluated");
                    };
                    assert_eq!(
                        facts.leaf.direction(),
                        Some(observed_direction),
                        "临时分离→扩展必须同向"
                    );
                    transition_hits[2] = true;
                }
                PairState::UpgradeDeferred => {
                    transition_hits[3] = true;
                }
                other => panic!("临时分离出现非法后继状态 {other:?}"),
            }
        }
    }
}

/// 1. `down_123_provisional_at_111_formed_at_123`：111 根时临时分离 Down，连接段 4..5 且内容等于
///    `units[4]`；123 根时先验单元前缀未变，再验已形成 Down、B 突破段下标 8、左节点与连接段不变。
#[test]
fn down_123_provisional_at_111_formed_at_123() {
    let (down, _, d) = fixture_123_bars();
    let exp = &d["bars_123_down"]["expected"];
    let dn = &exp["down"];

    let u111 = parse_l0_units(&down[..111]);
    let r111 = judge_trend_formation(0, &u111);
    assert_eq!(r111.unit_level(), 0);
    assert_eq!(r111.unit_count(), u111.len());
    assert!(r111.consolidation().is_none());
    assert_eq!(r111.centers().len(), 2);
    assert_eq!(r111.pairs().len(), 1);
    assert!(r111.final_pairs().is_empty());

    let p111: &PairJudgment = &r111.pairs()[0];
    let left_node: &CenterNode = p111.left();
    let conn_span: &UnitSpan = p111.connectors();
    assert_eq!(
        p111.state(),
        PairState::ProvisionalSeparation {
            observed_direction: Direction::Down
        }
    );
    assert!(p111.formed().is_none());
    assert!(!p111.is_final());
    assert_eq!(conn_span.range(), 4..5);
    assert_eq!(conn_span.units(), &u111[4..5]);
    assert_eq!(
        (
            conn_span.units()[0].start_index,
            conn_span.units()[0].end_index
        ),
        (49, 61)
    );
    assert_center_matches_json(left_node.center().unwrap(), &dn["a"]);
    assert_center_matches_json(p111.right().center().unwrap(), &dn["b"]);
    assert!(left_node.is_settled());
    assert!(!p111.right().is_settled());
    assert!(p111.right().break_unit().is_none());

    let u123 = parse_l0_units(&down[..123]);
    // 按 K 线追加测试先断言单元前缀未变（DESIGN §7 末句、主控裁定 #5）。
    assert!(
        u123.starts_with(&u111),
        "123 根的 L0 单元序列须保留 111 根单元前缀"
    );

    let r123 = judge_trend_formation(0, &u123);
    assert_eq!(r123.pairs().len(), 1);
    assert_eq!(r123.final_pairs().len(), 1);
    let p123 = &r123.pairs()[0];
    assert_eq!(
        p123.state(),
        PairState::TrendFormed {
            direction: Direction::Down
        }
    );
    assert!(p123.is_final());
    let formed: FormedTrend<'_> = p123.formed().expect("123 根应签发 FormedTrend");
    assert_eq!(formed.direction(), Direction::Down);
    assert_eq!(formed.pair(), p123);
    let (brk_idx, brk_unit) = p123.right().break_unit().expect("123 根 B 应已结算");
    assert_eq!(brk_idx, 8);
    assert_eq!(*brk_unit, u123[8]);
    assert_eq!((brk_unit.start_index, brk_unit.end_index), (97, 109));
    assert_eq!(p123.left(), p111.left());
    assert_eq!(p123.connectors(), p111.connectors());
}

/// 2. `up_mirror_123`：`8500 - p` 镜像序列，方向翻转，111 根临时分离 Up，123 根已形成 Up。
#[test]
fn up_mirror_123() {
    let (_, up, d) = fixture_123_bars();
    let up_exp = &d["bars_123_down"]["expected"]["up_mirror"];

    let u111 = parse_l0_units(&up[..111]);
    let r111 = judge_trend_formation(0, &u111);
    assert_eq!(r111.pairs().len(), 1);
    let p111 = &r111.pairs()[0];
    assert_eq!(
        p111.state(),
        PairState::ProvisionalSeparation {
            observed_direction: Direction::Up
        }
    );
    assert!(p111.formed().is_none());
    assert_eq!(p111.connectors().range(), 4..5);
    assert_eq!(p111.connectors().units(), &u111[4..5]);
    assert_center_matches_json(p111.left().center().unwrap(), &up_exp["a"]);
    assert_center_matches_json(p111.right().center().unwrap(), &up_exp["b"]);

    let u123 = parse_l0_units(&up[..123]);
    assert!(
        u123.starts_with(&u111),
        "镜像 123 根的 L0 单元序列须保留 111 根单元前缀"
    );

    let r123 = judge_trend_formation(0, &u123);
    assert_eq!(r123.pairs().len(), 1);
    let p123 = &r123.pairs()[0];
    assert_eq!(
        p123.state(),
        PairState::TrendFormed {
            direction: Direction::Up
        }
    );
    let formed = p123.formed().expect("镜像 123 根应签发上涨 FormedTrend");
    assert_eq!(formed.direction(), Direction::Up);
    assert_eq!(formed.pair(), p123);
    assert_eq!(p123.right().break_unit(), Some((8, &u123[8])));
    assert_eq!(p123.left(), p111.left());
    assert_eq!(p123.connectors(), p111.connectors());
}

/// 3. `open_b_fork_202_never_formed`（R1-a）：111..=202 每个前缀均无已形成，末切面为 `ExpansionHandoff`。
#[test]
fn open_b_fork_202_never_formed() {
    let (down, _, d) = fixture_123_bars();
    let fork = &d["open_b_revert_fork_202"];
    let spread = d["bars_123_down"]["bar_half_spread"].as_i64().unwrap();
    let prefix_len = fork["prefix_len"].as_u64().unwrap() as usize;
    let mut prices: Vec<Tick> = down[..prefix_len].iter().map(|b| b.close).collect();
    for v in fork["suffix_mid_prices"].as_array().unwrap() {
        prices.push(v.as_i64().unwrap());
    }
    assert_eq!(prices.len(), 202);
    let bars = build_bars(&prices, spread);

    let u111 = parse_l0_units(&bars[..111]);
    let r111 = judge_trend_formation(0, &u111);
    assert_eq!(
        r111.pairs()[0].state(),
        PairState::ProvisionalSeparation {
            observed_direction: Direction::Down
        }
    );

    let mut prev_units = u111.clone();
    let mut prev_res = r111.clone();
    let mut dummy_hits = [false; 4];

    for n in 111..=202 {
        let u = parse_l0_units(&bars[..n]);
        let r = judge_trend_formation(0, &u);
        for p in r.pairs() {
            assert!(
                p.formed().is_none(),
                "分叉第 {n} 根不得签发 FormedTrend，实际 {:?}",
                p.state()
            );
            assert!(
                !matches!(p.state(), PairState::TrendFormed { .. }),
                "分叉第 {n} 根不得报 TrendFormed"
            );
        }
        // 仅在单元序列构成前缀延伸时校验 M1-M4（DESIGN §7 末句、主控裁定 #5）。
        if u.starts_with(&prev_units) {
            assert_monotone_pair(&prev_res, &r, &mut dummy_hits);
        }
        prev_units = u;
        prev_res = r;
    }

    let u202 = prev_units;
    let r202 = prev_res;
    // A 与连接段前缀未变。
    assert!(u202.starts_with(&u111[..5]));
    assert_eq!(r202.pairs().len(), 1);
    let p202 = &r202.pairs()[0];
    assert_eq!(p202.state(), PairState::ExpansionHandoff);
    let PairOutcome::Evaluated(facts) = p202.outcome() else {
        panic!("202 根应为 Evaluated(DownExpansion)");
    };
    assert_eq!(facts.leaf, PairLeaf::DownExpansion);
    assert_eq!(p202.left().center().unwrap().dd, 3000);
    assert_eq!(p202.right().center().unwrap().gg, 3411);
    assert_eq!(p202.right().members().range(), 5..10);
    assert_eq!(p202.connectors().units(), &u202[4..5]);
    assert_eq!(
        (
            p202.connectors().units()[0].start_index,
            p202.connectors().units()[0].end_index
        ),
        (49, 61)
    );
    assert_eq!(p202.left(), r111.pairs()[0].left());
    assert_eq!(p202.connectors(), r111.pairs()[0].connectors());
}

/// 4. `append_monotone_final_prefix`：固定种子，级别取 0、1、6，逐前缀断言 M1–M4 与四种后继。
#[test]
fn append_monotone_final_prefix() {
    // 确定性 xorshift64 伪随机源。
    struct Rng(u64);
    impl Rng {
        fn next_u64(&mut self) -> u64 {
            let mut x = self.0;
            x ^= x << 13;
            x ^= x >> 7;
            x ^= x << 17;
            self.0 = x;
            x
        }
        fn range(&mut self, lo: i64, hi: i64) -> i64 {
            lo + (self.next_u64() % (hi - lo + 1) as u64) as i64
        }
    }

    // 针对性序列确保四种临时分离后继（已形成、继续临时、同向扩展、待升级）全部命中。
    let targeted: Vec<Vec<UnitRange>> = vec![
        // 1) Provisional → TrendFormed + open continuation
        units_from_endpoints(&[
            40, 10, 35, 20, 60, 55, 65, 45, 55, 48, 90, 80, 105, 85, 100, 82, 120, 110,
        ]),
        // 2) Provisional → Provisional (B 延伸但外缘仍高于 A.gg=40) → ExpansionHandoff (B.dd 跌破 40)
        units_from_endpoints(&[
            40, 10, 35, 20, 60, 55, 65, 45, 55, 48, 56, 46, 54, 38, 52, 80,
        ]),
        // 3) Provisional → UpgradeDeferred (B 持续延伸至 9 段且保持高于 A.gg=40)
        units_from_endpoints(&[
            40, 10, 35, 20, 60, 55, 65, 45, 55, 48, 56, 47, 55, 46, 54, 49, 53,
        ]),
    ];

    let mut rng = Rng(0x1426_2026_0303_u64);
    let mut sequences: Vec<Vec<UnitRange>> = targeted;

    // 固定种子生成 48 条不同尺度、含交替与非交替方向的多中枢序列。
    for s_idx in 0..48 {
        let len = 22 + (s_idx % 8);
        let mut units = Vec::with_capacity(len);
        let mut anchor: Tick = 500;
        let alternating = s_idx % 3 != 0;
        for k in 0..len {
            let drift: Tick = match s_idx % 4 {
                0 => 18,
                1 => -18,
                2 => 0,
                _ => {
                    if k < len / 2 {
                        15
                    } else {
                        -15
                    }
                }
            };
            let span_len = rng.range(12, 48);
            let dir = if alternating {
                if (k + s_idx) % 2 == 0 {
                    Direction::Up
                } else {
                    Direction::Down
                }
            } else if rng.next_u64().is_multiple_of(2) {
                Direction::Up
            } else {
                Direction::Down
            };
            let mid = anchor + drift + rng.range(-25, 25);
            let lo = mid - span_len / 2;
            let hi = lo + span_len;
            anchor = if dir == Direction::Up { hi } else { lo };
            units.push(UnitRange {
                start_index: k * 4,
                end_index: k * 4 + 4,
                direction: dir,
                lo,
                hi,
            });
        }
        sequences.push(units);
    }

    for &level in &[0u32, 1, 6] {
        let mut hits = [false; 4];
        for seq in &sequences {
            let mut prefix_results = Vec::with_capacity(seq.len() + 1);
            for len in 0..=seq.len() {
                prefix_results.push(judge_trend_formation(level, &seq[..len]));
            }
            // 对所有前缀对 (p, p + 1) 及 (p, seq.len()) 断言 M1–M4 与四种后继。
            for p in 0..seq.len() {
                assert_monotone_pair(&prefix_results[p], &prefix_results[p + 1], &mut hits);
                assert_monotone_pair(&prefix_results[p], &prefix_results[seq.len()], &mut hits);
            }
        }
        assert!(
            hits.iter().all(|&h| h),
            "level={level}: 必须实际命中全部四种临时分离后继，当前 {hits:?}"
        );
    }
}

/// 5. `formed_pair_survives_open_continuation`（R2-1）：11..=13 个单元时已形成 Up，
///    第 14 个单元加入开放第三枢 C 后为 `[已形成 Up, 临时分离 Up]`，`pairs()[0]` 逐字段不变。
#[test]
fn formed_pair_survives_open_continuation() {
    let pts = [40, 10, 35, 20, 60, 55, 65, 45, 55, 48, 90, 80, 105, 85, 100];
    let units = units_from_endpoints(&pts);
    assert_eq!(units.len(), 14);

    let mut formed_first: Option<PairJudgment> = None;
    for n in 11..=13 {
        let r = judge_trend_formation(0, &units[..n]);
        assert_eq!(r.pairs().len(), 1, "n={n}");
        assert_eq!(r.final_pairs().len(), 1, "n={n}");
        let p0 = &r.pairs()[0];
        assert_eq!(
            p0.state(),
            PairState::TrendFormed {
                direction: Direction::Up
            },
            "n={n}"
        );
        assert_eq!(p0.formed().unwrap().direction(), Direction::Up);
        if let Some(prev) = &formed_first {
            assert_eq!(p0, prev, "11..=13 间首对必须不变");
        } else {
            formed_first = Some(p0.clone());
        }
    }

    let r14 = judge_trend_formation(0, &units[..14]);
    assert!(r14.consolidation().is_none());
    assert_eq!(r14.centers().len(), 3);
    assert_eq!(r14.pairs().len(), 2);
    assert_eq!(r14.final_pairs().len(), 1);
    assert_eq!(&r14.pairs()[0], formed_first.as_ref().unwrap());
    assert_eq!(
        r14.pairs()[0].state(),
        PairState::TrendFormed {
            direction: Direction::Up
        }
    );
    assert_eq!(
        r14.pairs()[1].state(),
        PairState::ProvisionalSeparation {
            observed_direction: Direction::Up
        }
    );
    assert!(r14.pairs()[0].formed().is_some());
    assert!(r14.pairs()[1].formed().is_none());
}

/// 6. `settlement_is_read_from_source`（R2-2）：只有 u0..u7 时 B 的 `break_unit()` 为 None，没有已形成。
#[test]
fn settlement_is_read_from_source() {
    let (down, _, _) = fixture_123_bars();
    let u111 = parse_l0_units(&down[..111]);
    assert_eq!(u111.len(), 8, "111 根切面只有 u0..u7 共 8 段");

    let r = judge_trend_formation(0, &u111);
    assert_eq!(r.centers().len(), 2);
    let b = r.centers()[1];
    assert_eq!(b.members().range(), 5..8);
    assert!(b.break_unit().is_none());
    assert!(!b.is_settled());
    assert_eq!(r.pairs().len(), 1);
    assert!(r.pairs()[0].formed().is_none());
    assert!(!r.pairs()[0].is_final());
    assert!(r.final_pairs().is_empty());

    // 合成 9 单元（B 占 6..9，无 u9）同样无法签出 B 已结算。
    let syn = units_from_endpoints(&[40, 10, 35, 20, 60, 55, 65, 45, 55, 48]);
    assert_eq!(syn.len(), 9);
    let rs = judge_trend_formation(0, &syn);
    assert_eq!(rs.centers().len(), 2);
    assert_eq!(rs.centers()[1].members().range(), 6..9);
    assert!(rs.centers()[1].break_unit().is_none());
    assert!(rs.pairs()[0].formed().is_none());
}

/// 7. `evidence_content_equals_source`（R2-3、R1-b）：每段 `units()` 等于来源同区间切片，
///    连接段区间为左末到右首、非空且首项等于左突破段；替换 `units[4]` 后整体重扫仍全部成立。
#[test]
fn evidence_content_equals_source() {
    fn assert_all_spans_match_source(units: &[UnitRange], tf: &TrendFormation) {
        assert_eq!(tf.unit_count(), units.len());
        for c in tf.centers() {
            let r = c.members().range();
            assert!(!r.is_empty());
            assert_eq!(c.members().units(), &units[r.clone()]);
            if let Some((brk_idx, brk_unit)) = c.break_unit() {
                assert_eq!(brk_idx, r.end);
                assert_eq!(*brk_unit, units[brk_idx]);
            }
        }
        for p in tf.pairs() {
            let expected_range = p.left().members().range().end..p.right().members().range().start;
            assert!(!expected_range.is_empty(), "连接段区间非空");
            assert_eq!(p.connectors().range(), expected_range.clone());
            assert_eq!(p.connectors().units(), &units[expected_range]);
            let (left_brk_idx, left_brk_unit) = p.left().break_unit().expect("左节点恒已结算");
            assert_eq!(left_brk_idx, p.connectors().range().start);
            assert_eq!(p.connectors().units()[0], *left_brk_unit);
        }
    }

    let (down, _, _) = fixture_123_bars();
    let u123 = parse_l0_units(&down[..123]);
    let r_orig = judge_trend_formation(0, &u123);
    assert_eq!(r_orig.pairs().len(), 1);
    assert_all_spans_match_source(&u123, &r_orig);

    // 独审 R2-3 反例：把 units[4] 替换成 50→60、Down、[3140, 3240]，作为新来源整体重扫。
    let mut modified = u123.clone();
    modified[4] = UnitRange {
        start_index: 50,
        end_index: 60,
        direction: Direction::Down,
        lo: 3140,
        hi: 3240,
    };
    let r_mod = judge_trend_formation(0, &modified);
    assert_all_spans_match_source(&modified, &r_mod);
    assert_ne!(r_mod, r_orig, "修改来源单元后重扫证据同步变化");
}

/// 8. `upgrade_flag_mirrors_scanner`（R1-c、R2-4）：`center().is_none()` 恒等于
///    `scan.windows[k].upgraded`，不写死真值。
#[test]
fn upgrade_flag_mirrors_scanner() {
    let seqs = [
        units_from_endpoints(&[10, 40, 20, 35, 25, 34, 22, 33, 24, 32]),
        units_from_endpoints(&[11, 42, 22, 37, 37, 37, 37, 37, 37, 37]),
    ];

    for units in &seqs {
        for &level in &[0u32, 1] {
            let build = if level == 0 {
                center_from_segments
            } else {
                center_from_window
            };
            let scan = scan_center_facts_full(units, build);
            let tf = judge_trend_formation(level, units);
            assert_eq!(tf.centers().len(), scan.windows.len());
            for (k, node) in tf.centers().iter().enumerate() {
                assert_eq!(
                    node.center().is_none(),
                    scan.windows[k].upgraded,
                    "level={level}, window={k}: center().is_none() 须镜像扫描器 upgraded 标记"
                );
            }
            let expect_consol = scan.windows.len() == 1 && !scan.windows[0].upgraded;
            assert_eq!(tf.consolidation().is_some(), expect_consol);
        }
    }
}

/// 9. `subwindow_is_its_own_source`（R2-5）：使用独审 R2-5 原始九段序列
///    `[11, 42, 22, 37, 19, 40, 25, 34, 27, 33]`（母核心 `[22, 37]`、子窗 `units[3..6]` 核心 `[25, 37]`）。
///    整窗被标升级无中枢；单独传入 `units[3..6]` 作为独立来源时核心由这三段自己算，不继承母核心。
#[test]
fn subwindow_is_its_own_source() {
    let pts = [11, 42, 22, 37, 19, 40, 25, 34, 27, 33];
    let units = units_from_endpoints(&pts);
    assert_eq!(units.len(), 9);

    let parent_scan = scan_center_facts_full(&units, center_from_segments);
    assert_eq!(parent_scan.windows.len(), 1);
    assert!(parent_scan.windows[0].upgraded);
    let parent_core = center_from_segments(&units[0], &units[1], &units[2]).unwrap();
    assert_eq!((parent_core.zd, parent_core.zg), (22, 37));

    let parent_tf = judge_trend_formation(0, &units);
    assert_eq!(parent_tf.centers().len(), 1);
    assert!(parent_tf.centers()[0].center().is_none());
    assert!(parent_tf.consolidation().is_none());

    let sub = &units[3..6];
    let own_core = center_from_segments(&sub[0], &sub[1], &sub[2]).unwrap();
    assert_eq!((own_core.zd, own_core.zg), (25, 37));
    assert_ne!((own_core.zd, own_core.zg), (parent_core.zd, parent_core.zg));

    for &level in &[0u32, 1] {
        let sub_tf = judge_trend_formation(level, sub);
        let lone = sub_tf.consolidation().expect("三段独立来源构成单中枢盘整");
        let c = lone.center().expect("未升级窗口必有中枢");
        assert_eq!((c.zd, c.zg), (own_core.zd, own_core.zg));
        assert_ne!((c.zd, c.zg), (parent_core.zd, parent_core.zg));
    }
}

/// 10. `chain_keeps_evaluated_pair_beside_deferred`（R2-6）：含待升级对的链保留已知对；
///     只改首端点时两结果不等，`pairs()[0]` 分别为已形成 Up 与 `ExpansionHandoff`，`pairs()[1]` 均为 `UpgradeDeferred`。
#[test]
fn chain_keeps_evaluated_pair_beside_deferred() {
    let x_pts = [
        40, 10, 35, 20, 60, 55, 65, 45, 55, 48, 90, 80, 105, 85, 100, 86, 99, 87, 98, 88, 97,
    ];
    let mut y_pts = x_pts;
    y_pts[0] = 46;

    let ux = units_from_endpoints(&x_pts);
    let uy = units_from_endpoints(&y_pts);
    let fx = judge_trend_formation(0, &ux);
    let fy = judge_trend_formation(0, &uy);

    assert_ne!(fx, fy);
    assert_eq!(fx.pairs().len(), 2);
    assert_eq!(fy.pairs().len(), 2);
    assert_eq!(
        fx.pairs()[0].state(),
        PairState::TrendFormed {
            direction: Direction::Up
        }
    );
    assert_eq!(fy.pairs()[0].state(), PairState::ExpansionHandoff);
    assert_eq!(fx.pairs()[1].state(), PairState::UpgradeDeferred);
    assert_eq!(fy.pairs()[1].state(), PairState::UpgradeDeferred);
    assert!(fx.pairs()[0].formed().is_some());
    assert!(fy.pairs()[0].formed().is_none());
}

/// 11. `distinct_pairs_are_distinct`（R1-e）：同链中两个 `UpgradeDeferred` 对不相等。
#[test]
fn distinct_pairs_are_distinct() {
    let pts = [
        40, 10, 35, 20, 60, 55, 80, 60, 78, 61, 77, 62, 76, 63, 75, 64, 120, 100, 130, 110, 125,
    ];
    let units = units_from_endpoints(&pts);
    let tf = judge_trend_formation(0, &units);

    assert_eq!(tf.pairs().len(), 2);
    assert_eq!(tf.pairs()[0].state(), PairState::UpgradeDeferred);
    assert_eq!(tf.pairs()[1].state(), PairState::UpgradeDeferred);
    assert_ne!(tf.pairs()[0], tf.pairs()[1]);
    assert_ne!(tf.pairs()[0].connectors(), tf.pairs()[1].connectors());
    assert_ne!(
        tf.pairs()[0].left().ordinal(),
        tf.pairs()[1].left().ordinal()
    );
}

/// 12. `state_table`（R1-d，#2114 唯一对照表锁）：逐项核对 `(叶 / 待升级, 右端是否结算)` 到 `PairState` 的全表映射。
#[test]
fn state_table() {
    #[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
    enum RowKey {
        Pending(bool),
        CoreOverlap(bool),
        UpExp(bool),
        DownExp(bool),
        UpNew(bool),
        DownNew(bool),
    }

    fn row_key(outcome: PairOutcome, right_settled: bool) -> RowKey {
        match outcome {
            PairOutcome::PendingUpgrade => RowKey::Pending(right_settled),
            PairOutcome::Evaluated(f) => match f.leaf {
                PairLeaf::CoreNotStrictlySeparated => RowKey::CoreOverlap(right_settled),
                PairLeaf::UpExpansion => RowKey::UpExp(right_settled),
                PairLeaf::DownExpansion => RowKey::DownExp(right_settled),
                PairLeaf::UpNewbirth => RowKey::UpNew(right_settled),
                PairLeaf::DownNewbirth => RowKey::DownNew(right_settled),
            },
        }
    }

    // #2114 裁定变更时只改 confirmed() 与下表两行（UpNew(false) / DownNew(false)）。
    fn expected_state(key: RowKey) -> PairState {
        match key {
            RowKey::Pending(_) => PairState::UpgradeDeferred,
            RowKey::CoreOverlap(_) => PairState::CoreNotStrictlySeparated,
            RowKey::UpExp(_) | RowKey::DownExp(_) => PairState::ExpansionHandoff,
            RowKey::UpNew(false) => PairState::ProvisionalSeparation {
                observed_direction: Direction::Up,
            },
            RowKey::UpNew(true) => PairState::TrendFormed {
                direction: Direction::Up,
            },
            RowKey::DownNew(false) => PairState::ProvisionalSeparation {
                observed_direction: Direction::Down,
            },
            RowKey::DownNew(true) => PairState::TrendFormed {
                direction: Direction::Down,
            },
        }
    }

    let up_new = units_from_endpoints(&[40, 10, 35, 20, 60, 55, 65, 41, 55, 48, 90, 80]);
    let down_new = mirror_units(&up_new, 100);
    let up_exp = units_from_endpoints(&[40, 10, 35, 20, 60, 55, 65, 40, 55, 48, 90, 80]);
    let down_exp = mirror_units(&up_exp, 100);
    let core_ov = units_from_endpoints(&[16, 37, 29, 57, 47, 53, 37, 41, 37, 55, 41, 59, 54, 10]);
    let pending_both = units_from_endpoints(&[
        40, 10, 35, 20, 60, 55, 80, 60, 78, 61, 77, 62, 76, 63, 75, 64, 120, 100, 130, 110, 125,
    ]);

    let corpus = [
        &up_new,
        &down_new,
        &up_exp,
        &down_exp,
        &core_ov,
        &pending_both,
    ];
    let mut covered = BTreeSet::new();

    for seq in corpus {
        for len in 0..=seq.len() {
            let tf = judge_trend_formation(0, &seq[..len]);
            for p in tf.pairs() {
                let key = row_key(p.outcome(), p.right().is_settled());
                covered.insert(key);
                let want = expected_state(key);
                assert_eq!(p.state(), want, "len={len}, key={key:?}");
                assert_eq!(p.is_final(), p.right().is_settled());
                match p.formed() {
                    Some(ft) => {
                        assert_eq!(ft.pair(), p);
                        assert_eq!(
                            p.state(),
                            PairState::TrendFormed {
                                direction: ft.direction()
                            }
                        );
                        let PairOutcome::Evaluated(facts) = p.outcome() else {
                            panic!("FormedTrend 必来自 Evaluated");
                        };
                        assert_eq!(Some(ft.direction()), facts.leaf.direction());
                    }
                    None => {
                        assert!(!matches!(p.state(), PairState::TrendFormed { .. }));
                    }
                }
            }
        }
    }

    assert_eq!(
        covered.len(),
        12,
        "12 行状态对照表必须全部命中，实际覆盖 {:?}",
        covered
    );
}

/// 13. `non_adjacent_never_pairs`：两对均为 `UP_EXPANSION`，即便 C.DD=91 > A.GG=66 也绝不跨中枢配对。
#[test]
fn non_adjacent_never_pairs() {
    let pts = [
        30, 53, 36, 65, 36, 66, 57, 87, 69, 98, 91, 118, 103, 108, 94, 98, 85,
    ];
    let units = units_from_endpoints(&pts);
    let tf = judge_trend_formation(0, &units);

    assert_eq!(tf.centers().len(), 3);
    assert_eq!(tf.pairs().len(), 2);
    assert!(tf.consolidation().is_none());

    let a = tf.centers()[0].center().unwrap();
    let c = tf.centers()[2].center().unwrap();
    assert_eq!(a.gg, 66);
    assert_eq!(c.dd, 91);
    assert!(c.dd > a.gg, "非相邻 A→C 外缘严格分离，但绝不可跨枢配对");

    for p in tf.pairs() {
        assert_eq!(p.right().ordinal(), p.left().ordinal() + 1);
        assert_eq!(p.state(), PairState::ExpansionHandoff);
        let PairOutcome::Evaluated(f) = p.outcome() else {
            panic!("预期 Evaluated");
        };
        assert_eq!(f.leaf, PairLeaf::UpExpansion);
        assert!(p.formed().is_none());
    }
}

/// 14. `tangency_and_single_center`：双向外缘恰等相切归 `ExpansionHandoff`、差 1 tick 归 `TrendFormed`、
///     核心未严格分离归 `CoreNotStrictlySeparated`、单窗口归盘整。
#[test]
fn tangency_and_single_center() {
    let touch_pts = [40, 10, 35, 20, 60, 55, 65, 40, 55, 48, 90, 80];
    let strict_pts = [40, 10, 35, 20, 60, 55, 65, 41, 55, 48, 90, 80];

    let touch_up = judge_trend_formation(0, &units_from_endpoints(&touch_pts));
    assert_eq!(touch_up.pairs().len(), 1);
    assert_eq!(touch_up.pairs()[0].state(), PairState::ExpansionHandoff);
    let PairOutcome::Evaluated(f_tu) = touch_up.pairs()[0].outcome() else {
        panic!("预期 Evaluated");
    };
    assert_eq!(f_tu.leaf, PairLeaf::UpExpansion);
    assert!(f_tu.outer_touch());

    let strict_up = judge_trend_formation(0, &units_from_endpoints(&strict_pts));
    assert_eq!(strict_up.pairs().len(), 1);
    assert_eq!(
        strict_up.pairs()[0].state(),
        PairState::TrendFormed {
            direction: Direction::Up
        }
    );
    assert_eq!(
        strict_up.pairs()[0].formed().unwrap().direction(),
        Direction::Up
    );

    // 100 - p 镜像：锁定下行外缘恰等相切（放宽下行不等式必红）。
    let touch_dn_pts: Vec<Tick> = touch_pts.iter().map(|&p| 100 - p).collect();
    let strict_dn_pts: Vec<Tick> = strict_pts.iter().map(|&p| 100 - p).collect();

    let touch_dn = judge_trend_formation(0, &units_from_endpoints(&touch_dn_pts));
    assert_eq!(touch_dn.pairs().len(), 1);
    assert_eq!(touch_dn.pairs()[0].state(), PairState::ExpansionHandoff);
    let PairOutcome::Evaluated(f_td) = touch_dn.pairs()[0].outcome() else {
        panic!("预期 Evaluated");
    };
    assert_eq!(f_td.leaf, PairLeaf::DownExpansion);
    assert!(f_td.outer_touch());

    let strict_dn = judge_trend_formation(0, &units_from_endpoints(&strict_dn_pts));
    assert_eq!(strict_dn.pairs().len(), 1);
    assert_eq!(
        strict_dn.pairs()[0].state(),
        PairState::TrendFormed {
            direction: Direction::Down
        }
    );
    assert_eq!(
        strict_dn.pairs()[0].formed().unwrap().direction(),
        Direction::Down
    );

    // 核心未严格分离。
    let core_pts = [16, 37, 29, 57, 47, 53, 37, 41, 37, 55, 41, 59, 54];
    let core_res = judge_trend_formation(0, &units_from_endpoints(&core_pts));
    assert_eq!(core_res.pairs().len(), 1);
    assert_eq!(
        core_res.pairs()[0].state(),
        PairState::CoreNotStrictlySeparated
    );
    assert!(core_res.pairs()[0].formed().is_none());

    // 零窗口与单窗口盘整。
    let none_res = judge_trend_formation(0, &units_from_endpoints(&[10, 20, 15]));
    assert!(none_res.centers().is_empty());
    assert!(none_res.pairs().is_empty());
    assert!(none_res.consolidation().is_none());

    let single_res = judge_trend_formation(0, &units_from_endpoints(&[10, 40, 20, 35, 25, 50, 42]));
    assert_eq!(single_res.centers().len(), 1);
    assert!(single_res.pairs().is_empty());
    let consol = single_res.consolidation().expect("单未升级窗口必判盘整");
    assert_eq!(consol.ordinal(), 0);
    assert!(consol.center().is_some());
}

/// 15. `rule_804_level_and_mirror_lock`：1 级与 6 级除 `unit_level()` 外逐位相等；
///     0 级与 1 级在方向交替输入上相等，在同向三段 `[10,20]`、`[18,25]`、`[18,22]` 上不同（E1）；镜像得镜像。
#[test]
fn rule_804_level_and_mirror_lock() {
    let same_dir_three = vec![
        UnitRange {
            start_index: 0,
            end_index: 4,
            direction: Direction::Up,
            lo: 10,
            hi: 20,
        },
        UnitRange {
            start_index: 4,
            end_index: 8,
            direction: Direction::Up,
            lo: 18,
            hi: 25,
        },
        UnitRange {
            start_index: 8,
            end_index: 12,
            direction: Direction::Up,
            lo: 18,
            hi: 22,
        },
    ];

    // E1 锁：同向三段在 0 级不建枢、在 1 级与 6 级建出相同单中枢盘整（核心 [18, 20]）。
    let l0_same = judge_trend_formation(0, &same_dir_three);
    let l1_same = judge_trend_formation(1, &same_dir_three);
    let l6_same = judge_trend_formation(6, &same_dir_three);
    assert!(l0_same.centers().is_empty());
    assert!(l0_same.consolidation().is_none());
    let c1 = l1_same
        .consolidation()
        .expect("1 级几何判据应建单中枢")
        .center()
        .unwrap();
    assert_eq!((c1.zd, c1.zg), (18, 20));
    assert_eq!(l1_same.centers(), l6_same.centers());
    assert_eq!(l1_same.pairs(), l6_same.pairs());
    assert_eq!(l1_same.consolidation(), l6_same.consolidation());

    let alternating_suite: Vec<Vec<UnitRange>> = vec![
        units_from_endpoints(&[10, 20, 15]),
        units_from_endpoints(&[10, 40, 20, 35, 25, 50, 42]),
        units_from_endpoints(&[40, 10, 35, 20, 60, 55, 65, 41, 55, 48, 90, 80]),
        units_from_endpoints(&[40, 10, 35, 20, 60, 55, 65, 40, 55, 48, 90, 80]),
        units_from_endpoints(&[16, 37, 29, 57, 47, 53, 37, 41, 37, 55, 41, 59, 54]),
        units_from_endpoints(&[40, 10, 35, 20, 60, 55, 65, 45, 55, 48, 90, 80, 105, 85, 100]),
        units_from_endpoints(&[
            40, 10, 35, 20, 60, 55, 80, 60, 78, 61, 77, 62, 76, 63, 75, 64, 120, 100, 130, 110, 125,
        ]),
    ];

    let all_inputs: Vec<(&[UnitRange], bool)> = alternating_suite
        .iter()
        .map(|u| (u.as_slice(), true))
        .chain(std::iter::once((same_dir_three.as_slice(), false)))
        .collect();

    let offset = 1000;
    for (units, is_alternating) in all_inputs {
        let r0 = judge_trend_formation(0, units);
        let r1 = judge_trend_formation(1, units);
        let r6 = judge_trend_formation(6, units);

        // 1 级与 6 级在任意输入上除 unit_level() 外逐位相等。
        assert_eq!(r1.unit_level(), 1);
        assert_eq!(r6.unit_level(), 6);
        assert_eq!(r1.unit_count(), r6.unit_count());
        assert_eq!(r1.centers(), r6.centers());
        assert_eq!(r1.pairs(), r6.pairs());
        assert_eq!(r1.final_pairs(), r6.final_pairs());
        assert_eq!(r1.consolidation(), r6.consolidation());

        // 方向交替输入上 0 级与 1 级除 unit_level() 外逐位相等。
        if is_alternating {
            assert_eq!(r0.centers(), r1.centers());
            assert_eq!(r0.pairs(), r1.pairs());
            assert_eq!(r0.final_pairs(), r1.final_pairs());
            assert_eq!(r0.consolidation(), r1.consolidation());
        }

        // 价格与方向镜像输入得镜像结果（0、1、6 级全测）。
        let mir = mirror_units(units, offset);
        for &lvl in &[0u32, 1, 6] {
            let a = judge_trend_formation(lvl, units);
            let b = judge_trend_formation(lvl, &mir);
            assert_eq!(a.centers().len(), b.centers().len());
            assert_eq!(a.consolidation().is_some(), b.consolidation().is_some());
            for (ca, cb) in a.centers().into_iter().zip(b.centers()) {
                assert_eq!(ca.ordinal(), cb.ordinal());
                assert_eq!(ca.members().range(), cb.members().range());
                assert_eq!(ca.is_settled(), cb.is_settled());
                assert_eq!(ca.center().map(|c| mirror_center(c, offset)), cb.center());
            }
            assert_eq!(a.pairs().len(), b.pairs().len());
            for (pa, pb) in a.pairs().iter().zip(b.pairs()) {
                assert_eq!(pb.state(), mirror_state(pa.state()));
                assert_eq!(pb.is_final(), pa.is_final());
                assert_eq!(pb.connectors().range(), pa.connectors().range());
                assert_eq!(
                    pb.formed().map(|ft| ft.direction()),
                    pa.formed().map(|ft| ft.direction().flip())
                );
            }
        }
    }
}

/// 16. `parity_with_shared_scan`：节点与对逐位等于独立调用 `scan_center_facts_full` 后的
///     `window_facts`、`window_center`、`pair_facts`（0 级 `center_from_segments`，其余 `center_from_window`）。
#[test]
fn parity_with_shared_scan() {
    let (down, up, _) = fixture_123_bars();
    let corpus: Vec<Vec<UnitRange>> = vec![
        parse_l0_units(&down[..111]),
        parse_l0_units(&down[..123]),
        parse_l0_units(&up[..123]),
        units_from_endpoints(&[40, 10, 35, 20, 60, 55, 65, 45, 55, 48, 90, 80, 105, 85, 100]),
        units_from_endpoints(&[11, 42, 22, 37, 19, 40, 25, 34, 27, 33]),
        units_from_endpoints(&[11, 42, 22, 37, 37, 37, 37, 37, 37, 37]),
        units_from_endpoints(&[
            40, 10, 35, 20, 60, 55, 80, 60, 78, 61, 77, 62, 76, 63, 75, 64, 120, 100, 130, 110, 125,
        ]),
        units_from_endpoints(&[
            30, 53, 36, 65, 36, 66, 57, 87, 69, 98, 91, 118, 103, 108, 94, 98, 85,
        ]),
        units_from_endpoints(&[16, 37, 29, 57, 47, 53, 37, 41, 37, 55, 41, 59, 54]),
    ];

    for units in &corpus {
        for &level in &[0u32, 1, 6] {
            let build = if level == 0 {
                center_from_segments
            } else {
                center_from_window
            };
            let scan = scan_center_facts_full(units, build);
            let wfs = scan.window_facts(units);
            let pfs = scan.pair_facts(units);
            let tf = judge_trend_formation(level, units);

            assert_eq!(tf.unit_level(), level);
            assert_eq!(tf.unit_count(), units.len());
            let centers = tf.centers();
            assert_eq!(centers.len(), wfs.len());
            for (k, (node, wf)) in centers.iter().zip(&wfs).enumerate() {
                assert_eq!(node.ordinal(), k);
                assert_eq!(node.members().range(), wf.first..wf.last + 1);
                assert_eq!(node.members().units(), &units[wf.first..wf.last + 1]);
                assert_eq!(node.is_settled(), wf.settled);
                assert_eq!(node.break_unit().map(|(i, _)| i), wf.break_unit);
                if let Some((i, u)) = node.break_unit() {
                    assert_eq!(*u, units[i]);
                }
                let expected_center = (!wf.upgrade_pending).then(|| scan.window_center(units, k));
                assert_eq!(node.center(), expected_center);
            }

            let pairs = tf.pairs();
            assert_eq!(pairs.len(), pfs.len());
            for (p, pf) in pairs.iter().zip(&pfs) {
                assert_eq!(p.left().ordinal(), pf.left);
                assert_eq!(p.right().ordinal(), pf.right);
                assert_eq!(p.connectors().range(), pf.connectors);
                assert_eq!(p.connectors().units(), &units[pf.connectors.clone()]);
                assert_eq!(p.outcome(), pf.outcome);
            }
        }
    }
}

/// 17. `public_surface_lock`：`include_str!` 读模块源码，剥离注释后断言 DESIGN §3、§4 的
///     禁用项、唯一自由公开入口、精确公开类型/方法清单与零公开字段。
#[test]
fn public_surface_lock() {
    // 剥离 // 与 /* ... */ 注释，保留原始换行。
    fn strip_comments(src: &str) -> String {
        let bytes = src.as_bytes();
        let mut out = String::with_capacity(src.len());
        let mut i = 0;
        let mut in_str = false;
        while i < bytes.len() {
            if in_str {
                let c = bytes[i] as char;
                out.push(c);
                if c == '\\' && i + 1 < bytes.len() {
                    i += 1;
                    out.push(bytes[i] as char);
                } else if c == '"' {
                    in_str = false;
                }
                i += 1;
                continue;
            }
            if bytes[i] == b'"' {
                in_str = true;
                out.push('"');
                i += 1;
            } else if i + 1 < bytes.len() && bytes[i] == b'/' && bytes[i + 1] == b'/' {
                while i < bytes.len() && bytes[i] != b'\n' {
                    i += 1;
                }
            } else if i + 1 < bytes.len() && bytes[i] == b'/' && bytes[i + 1] == b'*' {
                i += 2;
                let mut depth = 1usize;
                while i + 1 < bytes.len() && depth > 0 {
                    if bytes[i] == b'/' && bytes[i + 1] == b'*' {
                        depth += 1;
                        i += 2;
                    } else if bytes[i] == b'*' && bytes[i + 1] == b'/' {
                        depth -= 1;
                        i += 2;
                    } else {
                        if bytes[i] == b'\n' {
                            out.push('\n');
                        }
                        i += 1;
                    }
                }
            } else {
                out.push(bytes[i] as char);
                i += 1;
            }
        }
        out
    }

    let code = strip_comments(TREND_FORMATION_SRC);

    // DESIGN §4 禁用符号与可见性/构造/派生禁令。
    for forbidden in [
        "Direction::Up",
        "Direction::Down",
        "UPGRADE_TOTAL_SEGMENTS",
        "center_pair_facts",
        "pair_domain_ok",
        "pub(crate)",
        "pub(super)",
        "fn new(",
        "fn try_new(",
        "Default",
        "Deserialize",
        "impl From",
        "pub type ",
        "pub const ",
        "pub trait ",
        "pub use ",
    ] {
        assert!(
            !code.contains(forbidden),
            "模块非注释源码不得包含禁用项 `{forbidden}`"
        );
    }

    // 解析公开类型、私有函数、自由公开函数与公开方法清单。
    let mut pub_structs = BTreeSet::new();
    let mut pub_enums = BTreeSet::new();
    let mut free_pub_fns = BTreeSet::new();
    let mut pub_methods = BTreeSet::new();
    let mut private_fns = BTreeSet::new();
    let mut in_pub_struct = false;
    let mut brace_depth: usize = 0;

    for raw_line in code.lines() {
        let line = raw_line.trim();
        if line.is_empty() {
            continue;
        }
        if let Some(rest) = line.strip_prefix("pub struct ") {
            let name = rest
                .split(|c: char| !c.is_ascii_alphanumeric() && c != '_')
                .next()
                .unwrap();
            pub_structs.insert(name.to_string());
            in_pub_struct = true;
        } else if let Some(rest) = line.strip_prefix("pub enum ") {
            let name = rest
                .split(|c: char| !c.is_ascii_alphanumeric() && c != '_')
                .next()
                .unwrap();
            pub_enums.insert(name.to_string());
        } else if in_pub_struct && brace_depth == 1 {
            assert!(
                !line.starts_with("pub ") && !line.starts_with("pub("),
                "公开结构体不得含公开字段：{line}"
            );
        }

        if let Some(rest) = line.strip_prefix("pub fn ") {
            let name = rest
                .split(|c: char| !c.is_ascii_alphanumeric() && c != '_')
                .next()
                .unwrap()
                .to_string();
            if brace_depth == 0 {
                free_pub_fns.insert(name);
            } else {
                assert!(
                    line.contains("&self") || line.contains("self)"),
                    "impl 块中的 pub fn 必须带 self（禁止关联构造器）：{line}"
                );
                pub_methods.insert(name);
            }
        } else if let Some(rest) = line.strip_prefix("fn ") {
            let name = rest
                .split(|c: char| !c.is_ascii_alphanumeric() && c != '_')
                .next()
                .unwrap()
                .to_string();
            private_fns.insert(name);
        }

        for ch in line.chars() {
            match ch {
                '{' => brace_depth += 1,
                '}' => {
                    brace_depth = brace_depth.saturating_sub(1);
                    if brace_depth == 0 {
                        in_pub_struct = false;
                    }
                }
                _ => {}
            }
        }
    }

    assert_eq!(
        free_pub_fns,
        BTreeSet::from(["judge_trend_formation".to_string()]),
        "不带 self 的公开函数只能是 judge_trend_formation"
    );
    assert_eq!(
        pub_structs,
        BTreeSet::from([
            "CenterNode".to_string(),
            "FormedTrend".to_string(),
            "PairJudgment".to_string(),
            "TrendFormation".to_string(),
            "UnitSpan".to_string(),
        ]),
        "公开结构体集合必须与 DESIGN §3 一致"
    );
    assert_eq!(
        pub_enums,
        BTreeSet::from(["PairState".to_string()]),
        "公开枚举只能是 PairState"
    );
    assert_eq!(
        private_fns,
        BTreeSet::from([
            "confirmed".to_string(),
            "seed_build".to_string(),
            "span".to_string(),
        ]),
        "私有函数只能是 seed_build、span、confirmed"
    );
    assert_eq!(
        pub_methods,
        BTreeSet::from([
            "break_unit".to_string(),
            "center".to_string(),
            "centers".to_string(),
            "connectors".to_string(),
            "consolidation".to_string(),
            "direction".to_string(),
            "final_pairs".to_string(),
            "formed".to_string(),
            "is_final".to_string(),
            "is_settled".to_string(),
            "left".to_string(),
            "members".to_string(),
            "ordinal".to_string(),
            "outcome".to_string(),
            "pair".to_string(),
            "pairs".to_string(),
            "range".to_string(),
            "right".to_string(),
            "state".to_string(),
            "unit_count".to_string(),
            "unit_level".to_string(),
            "units".to_string(),
        ]),
        "公开方法清单必须与 DESIGN §3 一致"
    );
}

// 18. 编译负例（DESIGN §10 #18）：五个证据结构体字面量构造均须报 E0451（块长 ≤ 20 行）。
// cargo rustc --locked --test trend_formation_1426 -- --cfg issue1426_fabricated_evidence_refusal
#[cfg(issue1426_fabricated_evidence_refusal)]
#[rustfmt::skip]
fn fabricated_evidence_literals_must_fail(u1: UnitSpan, u2: UnitSpan, c: CenterNode, p: &PairJudgment, t: TrendFormation) {
    let _ = UnitSpan { start: 0, units: Box::new([]) };
    let _ = CenterNode { ordinal: 0, members: u1, break_unit: None, center: None };
    let _ = PairJudgment { left: c.clone(), right: c, connectors: u2, outcome: PairOutcome::PendingUpgrade };
    let _ = TrendFormation { unit_level: 0, unit_count: 0, ..t };
    let _ = FormedTrend { pair: p, direction: Direction::Up };
}
