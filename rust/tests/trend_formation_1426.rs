//! #1426 TB-02-G 形成侧内核：外部集成测试及 #2114 / #804 行为锁。
//!
//! 本文件是外部 crate，只能访问 `newchan_rust::theta_v0::classifier::trend_formation` 的公开面；
//! 不存在任何收证据或构造证据的入口。

use serde_json::Value;

use newchan_rust::theta_v0::classifier::center::{
    center_from_segments, center_from_window, center_pair_facts, PairLeaf, UnitRange,
};
use newchan_rust::theta_v0::classifier::center_scan::{
    l0_units, scan_center_facts_full, PairOutcome, R5Gap, R5Proof, R5Witness,
};
use newchan_rust::theta_v0::classifier::trend_formation::{
    judge_trend_formation, CenterNode, FormedTrend, PairJudgment, PairState, TrendFormation,
    WindowOrigin,
};
use newchan_rust::theta_v0::config::ThetaConfig;
use newchan_rust::theta_v0::parser::parse_layer;
use newchan_rust::theta_v0::types::{Bar, Center, Direction, Segment, Tick};

const FIXTURE: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/tests/fixtures/trend_formation_1426.json"
));

const TREND_FORMATION_SRC: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/src/theta_v0/classifier/trend_formation.rs"
));

fn judge_from_move_start(level: u32, units: &[UnitRange]) -> TrendFormation {
    judge_trend_formation(level, units, WindowOrigin::MoveStartGuaranteed)
}

fn proof(node: &CenterNode) -> R5Proof {
    let R5Witness::Proven(proof) = node.r5_witness() else {
        panic!("期望共用 R5 见证，实际 {:?}", node.r5_witness());
    };
    proof
}

fn leaf(pair: &PairJudgment) -> PairLeaf {
    let PairOutcome::Evaluated(facts) = pair.outcome() else {
        panic!("期望已判关系叶，实际 {:?}", pair.outcome());
    };
    facts.leaf
}

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

fn units_from_endpoints(prices: &[Tick]) -> Vec<UnitRange> {
    let segments: Vec<_> = prices
        .windows(2)
        .enumerate()
        .map(|(k, w)| Segment {
            start_index: k * 4,
            end_index: k * 4 + 4,
            direction: if w[1] > w[0] {
                Direction::Up
            } else {
                Direction::Down
            },
            start_price: w[0],
            end_price: w[1],
        })
        .collect();
    l0_units(&segments)
}

const UP_FORMATION: &[Tick] = &[40, 10, 35, 20, 60, 55, 65, 45, 55, 48, 90, 80];
const UP_REVERSE_B: &[Tick] = &[40, 10, 35, 20, 60, 55, 65, 51, 60, 50, 61, 44, 47];
const DOWN_EXPANSION_FORK_END: usize = 202;

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
    let s = fc
        .iter()
        .filter(|c| {
            matches!(
                c.r5_witness(),
                R5Witness::Proven(_) | R5Witness::Absent(R5Gap::UpgradePending)
            )
        })
        .count();
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
                    matches!(
                        node.r5_witness(),
                        R5Witness::Proven(_) | R5Witness::Absent(R5Gap::UpgradePending)
                    ),
                    "M4: 非末节点 ordinal={} 的扫描边界必须已固定",
                    node.ordinal()
                );
            }
        }
    }

    // 临时分离的合法后继只有四种：同向已形成、同向临时分离、同向扩展、UpgradeDeferred。
    if let Some(last_f) = f.pairs().last() {
        if let Some(PairState::ProvisionalSeparation { observed_direction }) = last_f.state() {
            let idx = f.pairs().len() - 1;
            assert!(g.pairs().len() > idx, "临时分离对在追加后不得消失");
            let next = &g.pairs()[idx];
            match next.state() {
                Some(PairState::TrendFormed { direction }) => {
                    assert_eq!(direction, observed_direction, "临时分离→已形成必须同向");
                    transition_hits[0] = true;
                }
                Some(PairState::ProvisionalSeparation {
                    observed_direction: d,
                }) => {
                    assert_eq!(d, observed_direction, "临时分离→临时分离必须同向");
                    transition_hits[1] = true;
                }
                Some(PairState::ExpansionHandoff) => {
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
                Some(PairState::UpgradeDeferred) => {
                    transition_hits[3] = true;
                }
                other => panic!("临时分离出现非法后继状态 {other:?}"),
            }
        }
    }
}

fn assert_123_r5(bars: &[Bar], direction: Direction, expected: &Value) {
    let mut previous = None;
    for cut in [111, 123] {
        let units = parse_l0_units(&bars[..cut]);
        let ledger = judge_from_move_start(0, &units);
        assert_eq!(ledger.unit_level(), 0);
        assert_eq!(ledger.unit_count(), units.len());
        let [pair] = ledger.pairs() else {
            panic!("cut {cut} 必为一对");
        };
        assert_eq!(ledger.centers().len(), 2);
        assert_eq!(pair.connectors().range(), 4..5);
        assert_eq!(pair.connectors().units(), &units[4..5]);
        assert_eq!((units[4].start_index, units[4].end_index), (49, 61));
        assert_center_matches_json(pair.left().center().unwrap(), &expected["a"]);
        assert_center_matches_json(pair.right().center().unwrap(), &expected["b"]);
        let a = proof(pair.left());
        assert_eq!(
            (a.side(), a.leave_unit(), a.pullback_unit()),
            (direction, 3, 4)
        );
        if cut == 111 {
            assert_eq!(units.len(), 8);
            assert_eq!(pair.right().r5_witness(), R5Witness::Absent(R5Gap::Open));
            assert_eq!(
                pair.state(),
                Some(PairState::ProvisionalSeparation {
                    observed_direction: direction
                })
            );
            assert!(pair.formed().is_none());
            assert!(ledger.final_pairs().is_empty());
            previous = Some((units, pair.clone()));
        } else {
            let (prev_units, prev_pair) = previous.take().unwrap();
            assert!(
                units.starts_with(&prev_units),
                "须先证明 K 线追加保留已确认单元前缀"
            );
            assert_eq!(pair.left(), prev_pair.left());
            assert_eq!(pair.connectors(), prev_pair.connectors());
            assert_eq!(pair.right().break_unit(), Some((8, &units[8])));
            assert_eq!((units[8].start_index, units[8].end_index), (97, 109));
            let b = proof(pair.right());
            assert_eq!(
                (b.side(), b.leave_unit(), b.pullback_unit()),
                (direction, 7, 8)
            );
            assert_eq!(pair.state(), Some(PairState::TrendFormed { direction }));
            let formed: FormedTrend<'_> = pair.formed().expect("双枢 R5 已真实结算");
            assert_eq!(formed.direction(), direction);
            assert_eq!(formed.pair(), pair);
            assert_eq!(ledger.final_pairs(), ledger.pairs());
        }
        println!(
            "cut={cut} {direction:?} A={:?} B={:?} state={:?}",
            pair.left().r5_witness(),
            pair.right().r5_witness(),
            pair.state()
        );
    }
}

#[test]
fn down_123_provisional_at_111_formed_at_123() {
    let (down, _, d) = fixture_123_bars();
    assert_123_r5(
        &down,
        Direction::Down,
        &d["bars_123_down"]["expected"]["down"],
    );
}

#[test]
fn up_mirror_123() {
    let (_, up, d) = fixture_123_bars();
    assert_123_r5(
        &up,
        Direction::Up,
        &d["bars_123_down"]["expected"]["up_mirror"],
    );
}

#[test]
fn provisional_is_still_a_cc020_newbirth_leaf() {
    let (down, up, _) = fixture_123_bars();
    for (bars, want) in [(&down, PairLeaf::DownNewbirth), (&up, PairLeaf::UpNewbirth)] {
        let ledger = judge_from_move_start(0, &parse_l0_units(&bars[..111]));
        let pair = &ledger.pairs()[0];
        assert_eq!(leaf(pair), want);
        assert_eq!(
            pair.state().unwrap().label(),
            "开放期严格分离（当下读法；TrendFormed 未发）"
        );
        assert!(pair.formed().is_none());
    }
}

#[test]
fn unverified_or_prior_tail_cannot_sign_even_with_two_r5_witnesses() {
    let units = units_from_endpoints(UP_FORMATION);
    let guaranteed = judge_from_move_start(0, &units);
    let unverified = judge_trend_formation(0, &units, WindowOrigin::UnverifiedOrPriorTail);
    let pair = &unverified.pairs()[0];
    assert_eq!(unverified.centers(), guaranteed.centers());
    assert_eq!(pair.connectors(), guaranteed.pairs()[0].connectors());
    assert_eq!(pair.outcome(), guaranteed.pairs()[0].outcome());
    assert!(guaranteed.pairs()[0].formed().is_some());
    assert_eq!(proof(pair.left()).side(), Direction::Up);
    assert_eq!(proof(pair.right()).side(), Direction::Up);
    assert!(pair.is_final(), "扫描边界已固定不等于获准签发");
    assert_eq!(
        pair.state(),
        Some(PairState::ProvisionalSeparation {
            observed_direction: Direction::Up
        })
    );
    assert!(pair.formed().is_none());
    assert!(
        unverified.formed_open_center().is_none(),
        "不得借旧走势末枢担保实例"
    );
}

#[test]
fn reverse_b_r5_forms_in_pair_direction_not_same_direction_third_point() {
    let up = units_from_endpoints(UP_REVERSE_B);
    let down = mirror_units(&up, 1000);
    for (units, direction) in [(&up, Direction::Up), (&down, Direction::Down)] {
        let before_pullback = judge_from_move_start(0, &units[..units.len() - 1]);
        assert!(before_pullback.pairs()[0].formed().is_none());
        let tf = judge_from_move_start(0, units);
        let [pair] = tf.pairs() else {
            panic!("双枢反向 R5 要保留同一首对");
        };
        assert_eq!(pair.left(), before_pullback.pairs()[0].left());
        assert_eq!(pair.connectors(), before_pullback.pairs()[0].connectors());
        assert_eq!(pair.connectors().range(), 4..5);
        assert_eq!(
            pair.right().members(),
            before_pullback.pairs()[0].right().members()
        );
        assert_eq!(
            pair.right().center(),
            before_pullback.pairs()[0].right().center()
        );
        assert_eq!(leaf(pair).direction(), Some(direction));
        let b = proof(pair.right());
        assert_eq!(
            (b.leave_unit(), b.pullback_unit(), b.side()),
            (10, 11, direction.flip())
        );
        assert_ne!(b.side(), direction, "后枢的反向证据不得当作同向 c 内三类点");
        assert_eq!(pair.state(), Some(PairState::TrendFormed { direction }));
        assert_eq!(pair.formed().unwrap().direction(), direction);
    }
}

/// 测试 1/2 的双向反控：110 根仍是单枢；111 根若错用 A 的全成员外缘，几何判据会给扩展。
#[test]
fn cut_110_and_full_member_outer_edge_controls() {
    let (down, up, d) = fixture_123_bars();
    let exp = &d["bars_123_down"]["expected"];
    let cut = exp["prefix_before_separation"].as_u64().unwrap() as usize;
    assert_eq!(cut, 110);
    for (bars, direction, fixture, want) in [
        (
            &down,
            Direction::Down,
            &exp["down"],
            PairLeaf::DownExpansion,
        ),
        (&up, Direction::Up, &exp["up_mirror"], PairLeaf::UpExpansion),
    ] {
        let r110 = judge_from_move_start(0, &parse_l0_units(&bars[..cut]));
        assert!(
            r110.consolidation().is_some(),
            "cut-110 {direction:?} 应为单枢"
        );
        assert!(r110.pairs().is_empty(), "cut-110 {direction:?} 不应有对");

        let r111 = judge_from_move_start(0, &parse_l0_units(&bars[..111]));
        let [pair] = r111.pairs() else {
            panic!("cut-111 {direction:?} 应恰有一对");
        };
        let a = pair.left().center().unwrap();
        let b = pair.right().center().unwrap();
        let members = pair.left().members().units();
        let wrong_a = Center {
            dd: members.iter().map(|u| u.lo).min().unwrap(),
            gg: members.iter().map(|u| u.hi).max().unwrap(),
            ..a
        };
        let (edge, name) = match direction {
            Direction::Down => (wrong_a.dd, "full_outer_a_dd"),
            Direction::Up => (wrong_a.gg, "full_outer_a_gg"),
        };
        assert_eq!(edge, fixture[name].as_i64().unwrap());
        let leaf = center_pair_facts(&wrong_a, &b).leaf;
        assert_eq!(leaf, want);
        assert_eq!(leaf.as_str(), fixture["full_outer_leaf"].as_str().unwrap());
    }
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
    assert_eq!(prices.len(), DOWN_EXPANSION_FORK_END);
    let bars = build_bars(&prices, spread);

    let u111 = parse_l0_units(&bars[..111]);
    let r111 = judge_from_move_start(0, &u111);
    assert_eq!(
        r111.pairs()[0].state(),
        Some(PairState::ProvisionalSeparation {
            observed_direction: Direction::Down
        })
    );

    assert_eq!(r111.formed_open_center(), Some(r111.pairs()[0].left()));
    let mut prev_units = u111.clone();
    let mut prev_res = r111.clone();
    let mut dummy_hits = [false; 4];

    for n in 111..=DOWN_EXPANSION_FORK_END {
        let u = parse_l0_units(&bars[..n]);
        let r = judge_from_move_start(0, &u);
        assert_eq!(
            r.formed_open_center(),
            r111.formed_open_center(),
            "cut {n}: 保留开放实例原单枢形成事实"
        );
        for p in r.pairs() {
            assert!(
                p.formed().is_none(),
                "分叉第 {n} 根不得签发 FormedTrend，实际 {:?}",
                p.state()
            );
            assert!(
                !matches!(p.state(), Some(PairState::TrendFormed { .. })),
                "分叉第 {n} 根不得报 TrendFormed"
            );
        }
        // `segments_valid_prefix()` 只裁段端失败、不证明跨 bar 稳定（见 parser/mod.rs:103-106,145-157
        // 及模块头「调用方负责只传解析器的稳定前缀；见 #2114」）。
        // 独审逐次比较本夹具的 91 次追加，单元前缀无失配；这里先断言前缀，再验 M1–M4。
        assert!(
            u.starts_with(&prev_units),
            "分叉第 {n} 根预期保持单元前缀单调延伸，不得静默跳过 M1-M4"
        );
        assert_monotone_pair(&prev_res, &r, &mut dummy_hits);
        prev_units = u;
        prev_res = r;
    }

    let u202 = prev_units;
    let r202 = prev_res;
    // A 与连接段前缀未变。
    assert!(u202.starts_with(&u111[..5]));
    assert_eq!(r202.pairs().len(), 1);
    let p202 = &r202.pairs()[0];
    assert_eq!(p202.state(), Some(PairState::ExpansionHandoff));
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
    assert_eq!(r202.formed_open_center(), Some(p202.left()));
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
                prefix_results.push(judge_from_move_start(level, &seq[..len]));
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

/// 普通后续开放、反向、扩展及待升级都只改后续对的台账。
#[test]
fn formed_first_pair_is_monotone_across_ordinary_continuations() {
    let cases = [
        (
            UP_FORMATION,
            &[105, 85, 100][..],
            Some(PairLeaf::UpNewbirth),
        ),
        (
            UP_REVERSE_B,
            &[10, 30, 15][..],
            Some(PairLeaf::DownNewbirth),
        ),
        (
            UP_FORMATION,
            &[105, 60, 100][..],
            Some(PairLeaf::UpExpansion),
        ),
        (
            UP_FORMATION,
            &[105, 85, 100, 86, 99, 87, 98, 88, 97][..],
            None,
        ),
    ];

    for (base, suffix, want_leaf) in cases {
        let mut prices = base.to_vec();
        prices.extend(suffix);
        let units = units_from_endpoints(&prices);
        let start = base.len() - 1;
        let first = judge_from_move_start(0, &units[..start]).pairs()[0].clone();
        assert_eq!(first.formed().unwrap().direction(), Direction::Up);
        for len in start..=units.len() {
            let tf = judge_from_move_start(0, &units[..len]);
            let pair = &tf.pairs()[0];
            assert_eq!(pair, &first, "want_leaf={want_leaf:?} len={len}");
            assert_eq!(
                pair.state(),
                Some(PairState::TrendFormed {
                    direction: Direction::Up
                })
            );
            assert_eq!(pair.formed().unwrap().direction(), Direction::Up);
            assert!(tf.formed_open_center().is_none());
        }
        let tf = judge_from_move_start(0, &units);
        let [_, continuation] = tf.pairs() else {
            panic!("后续关系必须实际出现");
        };
        assert_eq!(continuation.state(), None);
        assert!(continuation.formed().is_none());
        if let Some(want) = want_leaf {
            assert_eq!(leaf(continuation), want);
            assert_eq!(
                continuation.right().r5_witness(),
                R5Witness::Absent(R5Gap::Open)
            );
        } else {
            assert_eq!(continuation.outcome(), PairOutcome::PendingUpgrade);
            assert_eq!(
                continuation.right().r5_witness(),
                R5Witness::Absent(R5Gap::UpgradePending)
            );
        }
    }
}

#[test]
fn first_pair_does_not_change_direction_when_b_breaks_against_it() {
    let mut prices = UP_REVERSE_B.to_vec();
    prices.extend([10, 30, 15, 26, 7, 12]);
    let units = units_from_endpoints(&prices);
    let ledger = judge_from_move_start(0, &units);
    let [first, reverse] = ledger.pairs() else {
        panic!("须含后续反向对");
    };
    assert_eq!(
        first.right(),
        reverse.left(),
        "B 是两个相邻关系共享的同一枢"
    );
    assert_eq!(proof(first.right()).side(), Direction::Down);
    assert_eq!(leaf(reverse), PairLeaf::DownNewbirth);
    assert_eq!(proof(reverse.right()).side(), Direction::Down);
    assert_eq!(reverse.state(), None);
    assert!(reverse.formed().is_none());
    assert_eq!(first.formed().unwrap().direction(), Direction::Up);
}

/// 6. `settlement_is_read_from_source`（R2-2）：只有 u0..u7 时 B 的 `break_unit()` 为 None，没有已形成。
#[test]
fn settlement_is_read_from_source() {
    let (down, _, _) = fixture_123_bars();
    let u111 = parse_l0_units(&down[..111]);
    assert_eq!(u111.len(), 8, "111 根切面只有 u0..u7 共 8 段");

    let r = judge_from_move_start(0, &u111);
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
    let rs = judge_from_move_start(0, &syn);
    assert_eq!(rs.centers().len(), 2);
    assert_eq!(rs.centers()[1].members().range(), 6..9);
    assert!(rs.centers()[1].break_unit().is_none());
    assert!(rs.pairs()[0].formed().is_none());
}

#[test]
fn bare_scan_exit_does_not_authorize_r5_or_trend_formation() {
    let mut units = units_from_endpoints(UP_FORMATION);
    // 同一关节的待测单元自身朝外，不能充当首回抽。
    units[10].direction = Direction::Up;
    let tf = judge_from_move_start(1, &units);
    let pair = &tf.pairs()[0];
    assert!(pair.right().is_settled(), "旧扫描退出标记仍可观察");
    assert_eq!(pair.right().break_unit(), Some((10, &units[10])));
    assert_eq!(
        pair.right().r5_witness(),
        R5Witness::Absent(R5Gap::BreakUnitOutward)
    );
    assert!(!pair.is_final());
    assert_eq!(
        pair.state(),
        Some(PairState::ProvisionalSeparation {
            observed_direction: Direction::Up
        })
    );
    assert!(pair.formed().is_none());
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
    let r_orig = judge_from_move_start(0, &u123);
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
    let r_mod = judge_from_move_start(0, &modified);
    assert_all_spans_match_source(&modified, &r_mod);
    assert!(r_mod.pairs().is_empty(), "首枢的未证退出不能形成一条假连接");
    let a = r_mod.centers()[0];
    assert!(a.break_unit().is_some());
    assert!(!matches!(a.r5_witness(), R5Witness::Proven(_)));
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
            let tf = judge_from_move_start(level, units);
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

    let parent_tf = judge_from_move_start(0, &units);
    assert_eq!(parent_tf.centers().len(), 1);
    assert!(parent_tf.centers()[0].center().is_none());
    assert!(parent_tf.consolidation().is_none());

    let sub = &units[3..6];
    let own_core = center_from_segments(&sub[0], &sub[1], &sub[2]).unwrap();
    assert_eq!((own_core.zd, own_core.zg), (25, 37));
    assert_ne!((own_core.zd, own_core.zg), (parent_core.zd, parent_core.zg));

    for &level in &[0u32, 1] {
        let sub_tf = judge_from_move_start(level, sub);
        let lone = sub_tf.consolidation().expect("三段独立来源构成单中枢盘整");
        let c = lone.center().expect("未升级窗口必有中枢");
        assert_eq!((c.zd, c.zg), (own_core.zd, own_core.zg));
        assert_ne!((c.zd, c.zg), (parent_core.zd, parent_core.zg));
    }
}

/// 10. `chain_keeps_evaluated_pair_beside_deferred`（R2-6）：含待升级对的链保留已知对；
///     只改首端点时两结果不等，`pairs()[0]` 分别为已形成 Up 与 `ExpansionHandoff`，`pairs()[1]` 仅保留待升级关系。
#[test]
fn chain_keeps_evaluated_pair_beside_deferred() {
    let x_pts = [
        40, 10, 35, 20, 60, 55, 65, 45, 55, 48, 90, 80, 105, 85, 100, 86, 99, 87, 98, 88, 97,
    ];
    let mut y_pts = x_pts;
    y_pts[0] = 46;

    let ux = units_from_endpoints(&x_pts);
    let uy = units_from_endpoints(&y_pts);
    let fx = judge_from_move_start(0, &ux);
    let fy = judge_from_move_start(0, &uy);

    assert_ne!(fx, fy);
    assert_eq!(fx.pairs().len(), 2);
    assert_eq!(fy.pairs().len(), 2);
    assert_eq!(
        fx.pairs()[0].state(),
        Some(PairState::TrendFormed {
            direction: Direction::Up
        })
    );
    assert_eq!(fy.pairs()[0].state(), Some(PairState::ExpansionHandoff));
    for p in [&fx.pairs()[1], &fy.pairs()[1]] {
        assert_eq!(p.outcome(), PairOutcome::PendingUpgrade);
        assert_eq!(p.state(), None);
        assert!(p.formed().is_none());
        assert!(p.is_final());
        assert_eq!(
            p.right().r5_witness(),
            R5Witness::Absent(R5Gap::UpgradePending)
        );
        assert!(p.right().break_unit().is_none());
    }
    assert!(fx.pairs()[0].formed().is_some());
    assert!(fy.pairs()[0].formed().is_none());
}

/// 升级后共用扫描保留 C→D，不能编造 B→C，也不能把 C→D 认作首对。
#[test]
fn distinct_pairs_are_distinct() {
    let units = units_from_endpoints(&[
        40, 10, 35, 20, 60, 55, 65, 45, 55, 48, 56, 47, 55, 46, 54, 49, 85, 65, 79, 72, 83, 41, 45,
        10, 32, 15, 26, 7, 12,
    ]);
    let tf = judge_from_move_start(0, &units);
    let [first, later] = tf.pairs() else {
        panic!("须保留升级前后两条真实关系");
    };
    assert_eq!(
        tf.centers().iter().map(|c| c.ordinal()).collect::<Vec<_>>(),
        [0, 1, 2, 3]
    );
    assert_eq!((first.left().ordinal(), first.right().ordinal()), (0, 1));
    assert_eq!((later.left().ordinal(), later.right().ordinal()), (2, 3));
    assert_eq!(first.state(), Some(PairState::UpgradeDeferred));
    assert_eq!(first.outcome(), PairOutcome::PendingUpgrade);
    assert_eq!(leaf(later), PairLeaf::DownNewbirth);
    assert!(matches!(later.left().r5_witness(), R5Witness::Proven(_)));
    assert!(matches!(later.right().r5_witness(), R5Witness::Proven(_)));
    assert_eq!(later.state(), None);
    assert!(later.formed().is_none());
    assert!(first.formed().is_none());
    assert_ne!(first, later);
    assert_eq!(tf.formed_open_center(), Some(first.left()));

    // 若窗首本身待升级，台账首项也可能不是起始首对。
    let cut = first.right().members().range().start;
    let from_upgrade = judge_from_move_start(0, &units[cut..]);
    let [only] = from_upgrade.pairs() else {
        panic!("仅保留升级后的独立关系");
    };
    assert_eq!(only.left().ordinal(), 1);
    assert_eq!(leaf(only), PairLeaf::DownNewbirth);
    assert_eq!(only.state(), None);
    assert!(only.formed().is_none());
    assert!(from_upgrade.formed_open_center().is_none());
}

#[test]
fn blocked_first_pair_never_promotes_a_later_eligible_pair() {
    let cases = [
        (
            PairState::ExpansionHandoff,
            &[40, 10, 35, 20, 60, 55, 65, 40, 55, 48, 90, 80][..],
        ),
        (
            PairState::CoreNotStrictlySeparated,
            &[40, 10, 35, 20, 60, 55, 65, 18, 33, 23, 90, 80][..],
        ),
    ];
    for (blocked, prefix) in cases {
        let mut prices = prefix.to_vec();
        prices.extend([105, 85, 100, 90, 120, 110]);
        let units = units_from_endpoints(&prices);
        let tf = judge_from_move_start(0, &units);
        let [first, later] = tf.pairs() else {
            panic!("须含首对和后序对：{blocked:?}");
        };
        assert_eq!(first.state(), Some(blocked));
        assert!(first.formed().is_none());
        assert_eq!(tf.formed_open_center(), Some(first.left()));
        assert_eq!(leaf(later), PairLeaf::UpNewbirth);
        assert_eq!(later.state(), None);
        assert!(later.formed().is_none());
        // 仅当构造方另担保 B 是另一实例的首枢，B→C 才有资格签发。
        let independent = judge_from_move_start(0, &units[later.left().members().range().start..]);
        assert_eq!(
            independent.pairs()[0].formed().unwrap().direction(),
            Direction::Up
        );
    }
}

/// 只对首对读形成侧。每一关系叶与实际 R5 缺席／具证的可达分支都固定预期。
#[test]
fn state_table() {
    use Direction::{Down, Up};
    use PairState::{
        CoreNotStrictlySeparated, ExpansionHandoff, ProvisionalSeparation, TrendFormed,
        UpgradeDeferred,
    };
    let up_new = units_from_endpoints(UP_FORMATION);
    let down_new = mirror_units(&up_new, 1000);
    let up_exp = units_from_endpoints(&[40, 10, 35, 20, 60, 55, 65, 40, 55, 48, 90, 80]);
    let down_exp = mirror_units(&up_exp, 1000);
    let core = units_from_endpoints(&[40, 10, 35, 20, 60, 55, 65, 18, 33, 23, 90, 80]);
    let upgrade = units_from_endpoints(&[
        40, 10, 35, 20, 60, 55, 65, 45, 55, 48, 56, 47, 55, 46, 54, 49,
    ]);
    for (units, want_leaf, open, final_state) in [
        (
            &up_new,
            PairLeaf::UpNewbirth,
            ProvisionalSeparation {
                observed_direction: Up,
            },
            TrendFormed { direction: Up },
        ),
        (
            &down_new,
            PairLeaf::DownNewbirth,
            ProvisionalSeparation {
                observed_direction: Down,
            },
            TrendFormed { direction: Down },
        ),
        (
            &up_exp,
            PairLeaf::UpExpansion,
            ExpansionHandoff,
            ExpansionHandoff,
        ),
        (
            &down_exp,
            PairLeaf::DownExpansion,
            ExpansionHandoff,
            ExpansionHandoff,
        ),
        (
            &core,
            PairLeaf::CoreNotStrictlySeparated,
            CoreNotStrictlySeparated,
            CoreNotStrictlySeparated,
        ),
    ] {
        let before = judge_from_move_start(0, &units[..units.len() - 1]);
        let after = judge_from_move_start(0, units);
        for (ledger, want, final_) in [(&before, open, false), (&after, final_state, true)] {
            let [p] = ledger.pairs() else {
                panic!("须实际命中状态表行：{want:?}");
            };
            assert_eq!(leaf(p), want_leaf);
            assert_eq!(p.state(), Some(want));
            assert_eq!(p.is_final(), final_);
            assert_eq!(
                p.formed().map(|ft| ft.direction()),
                match want {
                    TrendFormed { direction } => Some(direction),
                    _ => None,
                }
            );
        }
    }
    let result = judge_from_move_start(0, &upgrade);
    assert_eq!(result.pairs()[0].state(), Some(UpgradeDeferred));
    assert_eq!(result.pairs()[0].outcome(), PairOutcome::PendingUpgrade);
    assert!(result.pairs()[0].formed().is_none());
}

/// 13. `non_adjacent_never_pairs`：两对均为 `UP_EXPANSION`，即便 C.DD=91 > A.GG=66 也绝不跨中枢配对。
#[test]
fn non_adjacent_never_pairs() {
    let pts = [
        30, 53, 36, 65, 36, 66, 57, 87, 69, 98, 91, 118, 103, 108, 94, 98, 85,
    ];
    let units = units_from_endpoints(&pts);
    let tf = judge_from_move_start(0, &units);

    assert_eq!(tf.centers().len(), 3);
    assert_eq!(tf.pairs().len(), 2);
    assert!(tf.consolidation().is_none());

    let a = tf.centers()[0].center().unwrap();
    let c = tf.centers()[2].center().unwrap();
    assert_eq!(a.gg, 66);
    assert_eq!(c.dd, 91);
    assert!(c.dd > a.gg, "非相邻 A→C 外缘严格分离，但绝不可跨枢配对");

    for (k, p) in tf.pairs().iter().enumerate() {
        assert_eq!(p.right().ordinal(), p.left().ordinal() + 1);
        assert_eq!(p.state(), (k == 0).then_some(PairState::ExpansionHandoff));
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

    let touch_up = judge_from_move_start(0, &units_from_endpoints(&touch_pts));
    assert_eq!(touch_up.pairs().len(), 1);
    assert_eq!(
        touch_up.pairs()[0].state(),
        Some(PairState::ExpansionHandoff)
    );
    let PairOutcome::Evaluated(f_tu) = touch_up.pairs()[0].outcome() else {
        panic!("预期 Evaluated");
    };
    assert_eq!(f_tu.leaf, PairLeaf::UpExpansion);
    assert!(f_tu.outer_touch());

    let strict_up = judge_from_move_start(0, &units_from_endpoints(&strict_pts));
    assert_eq!(strict_up.pairs().len(), 1);
    assert_eq!(
        strict_up.pairs()[0].state(),
        Some(PairState::TrendFormed {
            direction: Direction::Up
        })
    );
    assert_eq!(
        strict_up.pairs()[0].formed().unwrap().direction(),
        Direction::Up
    );

    // 100 - p 镜像：锁定下行外缘恰等相切（放宽下行不等式必红）。
    let touch_dn_pts: Vec<Tick> = touch_pts.iter().map(|&p| 100 - p).collect();
    let strict_dn_pts: Vec<Tick> = strict_pts.iter().map(|&p| 100 - p).collect();

    let touch_dn = judge_from_move_start(0, &units_from_endpoints(&touch_dn_pts));
    assert_eq!(touch_dn.pairs().len(), 1);
    assert_eq!(
        touch_dn.pairs()[0].state(),
        Some(PairState::ExpansionHandoff)
    );
    let PairOutcome::Evaluated(f_td) = touch_dn.pairs()[0].outcome() else {
        panic!("预期 Evaluated");
    };
    assert_eq!(f_td.leaf, PairLeaf::DownExpansion);
    assert!(f_td.outer_touch());

    let strict_dn = judge_from_move_start(0, &units_from_endpoints(&strict_dn_pts));
    assert_eq!(strict_dn.pairs().len(), 1);
    assert_eq!(
        strict_dn.pairs()[0].state(),
        Some(PairState::TrendFormed {
            direction: Direction::Down
        })
    );
    assert_eq!(
        strict_dn.pairs()[0].formed().unwrap().direction(),
        Direction::Down
    );

    // 核心未严格分离。
    let core_pts = [40, 10, 35, 20, 60, 55, 65, 18, 33, 23, 90, 80];
    let core_res = judge_from_move_start(0, &units_from_endpoints(&core_pts));
    assert_eq!(core_res.pairs().len(), 1);
    assert_eq!(
        core_res.pairs()[0].state(),
        Some(PairState::CoreNotStrictlySeparated)
    );
    assert!(core_res.pairs()[0].formed().is_none());

    // 零窗口与单窗口盘整。
    let none_res = judge_from_move_start(0, &units_from_endpoints(&[10, 20, 15]));
    assert!(none_res.centers().is_empty());
    assert!(none_res.pairs().is_empty());
    assert!(none_res.consolidation().is_none());

    let single_res = judge_from_move_start(0, &units_from_endpoints(&[10, 40, 20, 35, 25, 50, 42]));
    assert_eq!(single_res.centers().len(), 1);
    assert!(single_res.pairs().is_empty());
    let consol = single_res.consolidation().expect("单未升级窗口必判盘整");
    assert_eq!(consol.ordinal(), 0);
    assert!(consol.center().is_some());
}

/// 15. `rule_804_level_and_mirror_lock`：1 级与 2 级除 `unit_level()` 外逐位相等；
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

    // E1 锁：同向三段在 0 级不建枢、在 1 级与 2 级建出相同单中枢盘整（核心 [18, 20]）。
    let l0_same = judge_from_move_start(0, &same_dir_three);
    let l1_same = judge_from_move_start(1, &same_dir_three);
    let l2_same = judge_from_move_start(2, &same_dir_three);
    assert!(l0_same.centers().is_empty());
    assert!(l0_same.consolidation().is_none());
    let c1 = l1_same
        .consolidation()
        .expect("1 级几何判据应建单中枢")
        .center()
        .unwrap();
    assert_eq!((c1.zd, c1.zg), (18, 20));
    assert_eq!(l1_same.centers(), l2_same.centers());
    assert_eq!(l1_same.pairs(), l2_same.pairs());
    assert_eq!(l1_same.consolidation(), l2_same.consolidation());

    let (down, _, _) = fixture_123_bars();
    let alternating_suite: Vec<Vec<UnitRange>> = vec![
        parse_l0_units(&down[..111]),
        parse_l0_units(&down),
        units_from_endpoints(UP_REVERSE_B),
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
        let r0 = judge_from_move_start(0, units);
        let r1 = judge_from_move_start(1, units);
        let r2 = judge_from_move_start(2, units);

        // 1 级与 2 级在任意输入上除 unit_level() 外逐位相等。
        assert_eq!(r1.unit_level(), 1);
        assert_eq!(r2.unit_level(), 2);
        assert_eq!(r1.unit_count(), r2.unit_count());
        assert_eq!(r1.centers(), r2.centers());
        assert_eq!(r1.pairs(), r2.pairs());
        assert_eq!(r1.final_pairs(), r2.final_pairs());
        assert_eq!(r1.consolidation(), r2.consolidation());
        assert_eq!(r1.formed_open_center(), r2.formed_open_center());

        // 方向交替输入上 0 级与 1 级除 unit_level() 外逐位相等。
        if is_alternating {
            assert_eq!(r0.centers(), r1.centers());
            assert_eq!(r0.pairs(), r1.pairs());
            assert_eq!(r0.final_pairs(), r1.final_pairs());
            assert_eq!(r0.consolidation(), r1.consolidation());
            assert_eq!(r0.formed_open_center(), r1.formed_open_center());
        }

        // 价格与方向镜像输入得镜像结果（0、1、2 级全测）。
        let mir = mirror_units(units, offset);
        for &lvl in &[0u32, 1, 2] {
            let a = judge_from_move_start(lvl, units);
            let b = judge_from_move_start(lvl, &mir);
            assert_eq!(a.centers().len(), b.centers().len());
            assert_eq!(a.consolidation().is_some(), b.consolidation().is_some());
            for (ca, cb) in a.centers().into_iter().zip(b.centers()) {
                assert_eq!(ca.ordinal(), cb.ordinal());
                assert_eq!(ca.members().range(), cb.members().range());
                assert_eq!(ca.is_settled(), cb.is_settled());
                assert_eq!(
                    mirror_units(ca.members().units(), offset),
                    cb.members().units()
                );
                assert_eq!(
                    ca.break_unit().map(|(i, _)| i),
                    cb.break_unit().map(|(i, _)| i)
                );
                match (ca.r5_witness(), cb.r5_witness()) {
                    (R5Witness::Absent(a), R5Witness::Absent(b)) => assert_eq!(a, b),
                    (R5Witness::Proven(a), R5Witness::Proven(b)) => {
                        assert_eq!(a.leave_unit(), b.leave_unit());
                        assert_eq!(a.pullback_unit(), b.pullback_unit());
                        assert_eq!(a.side().flip(), b.side());
                        assert_eq!((offset - a.core().1, offset - a.core().0), b.core());
                        assert_eq!(offset - a.pullback_extreme(), b.pullback_extreme());
                    }
                    other => panic!("镜像的 R5 结算状态不符：{other:?}"),
                }
                assert_eq!(ca.center().map(|c| mirror_center(c, offset)), cb.center());
            }
            assert_eq!(a.pairs().len(), b.pairs().len());
            for (pa, pb) in a.pairs().iter().zip(b.pairs()) {
                assert_eq!(pb.state(), pa.state().map(mirror_state));
                assert_eq!(pb.is_final(), pa.is_final());
                assert_eq!(pb.connectors().range(), pa.connectors().range());
                assert_eq!(
                    mirror_units(pa.connectors().units(), offset),
                    pb.connectors().units()
                );
                match pa.outcome() {
                    PairOutcome::PendingUpgrade => {
                        assert_eq!(pb.outcome(), PairOutcome::PendingUpgrade)
                    }
                    PairOutcome::Evaluated(facts) => {
                        use PairLeaf::*;
                        let mirrored = match facts.leaf {
                            UpNewbirth => DownNewbirth,
                            DownNewbirth => UpNewbirth,
                            UpExpansion => DownExpansion,
                            DownExpansion => UpExpansion,
                            CoreNotStrictlySeparated => CoreNotStrictlySeparated,
                        };
                        assert_eq!(leaf(pb), mirrored);
                    }
                }
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
            let witnesses = scan.r5_witnesses(units);
            let pfs = scan.pair_facts(units);
            let tf = judge_from_move_start(level, units);

            assert_eq!(tf.unit_level(), level);
            assert_eq!(tf.unit_count(), units.len());
            let centers = tf.centers();
            assert_eq!(centers.len(), wfs.len());
            for (k, (node, wf)) in centers.iter().zip(&wfs).enumerate() {
                assert_eq!(node.ordinal(), k);
                assert_eq!(node.members().range(), wf.first..wf.last + 1);
                assert_eq!(node.members().units(), &units[wf.first..wf.last + 1]);
                assert_eq!(node.r5_witness(), witnesses[k]);
                assert_eq!(
                    wf.settled,
                    matches!(node.r5_witness(), R5Witness::Proven(_))
                );
                assert_eq!(
                    node.break_unit().map(|(i, _)| i),
                    wf.break_unit.or(wf.pending_boundary)
                );
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
                assert_eq!(p.state().is_some(), pf.left == 0);
            }
        }
    }
}

/// 17. 源码文本锁只提示 DESIGN §3、§4 的回归；外部不能用字面量构造证据由第 18 项编译负例验证。
#[test]
fn public_surface_lock() {
    check_public_surface(TREND_FORMATION_SRC).unwrap();

    let with_async = format!("{TREND_FORMATION_SRC}\npub async fn x() {{}}\n");
    assert!(check_public_surface(&with_async).is_err());

    let with_string = format!("{TREND_FORMATION_SRC}\nconst _: &str = \"Default\";\n");
    check_public_surface(&with_string).unwrap();

    let with_comment = TREND_FORMATION_SRC.replace("pub fn range", "pub /* Default */ fn range");
    assert_ne!(with_comment, TREND_FORMATION_SRC);
    check_public_surface(&with_comment).unwrap();
}

// 只切分源码锁所需的标识符、标点；注释与字符串内容不参加匹配。
fn surface_tokens(mut src: &str) -> Vec<&str> {
    let mut tokens = Vec::new();
    while let Some(c) = src.chars().next() {
        if c.is_whitespace() {
            src = &src[c.len_utf8()..];
        } else if src.starts_with("//") {
            src = src.find('\n').map_or("", |end| &src[end..]);
        } else if let Some(rest) = src.strip_prefix("/*") {
            src = rest;
            let mut depth = 1;
            while depth != 0 {
                let end = src.find(['/', '*']).expect("未闭合的块注释");
                match &src[end..] {
                    s if s.starts_with("/*") => {
                        depth += 1;
                        src = &s[2..];
                    }
                    s if s.starts_with("*/") => {
                        depth -= 1;
                        src = &s[2..];
                    }
                    s => src = &s[1..],
                }
            }
        } else {
            // 普通、字节、C 字符串及其 raw 形式。
            let literal = src.strip_prefix(['b', 'c']).unwrap_or(src);
            if let Some(rest) = literal.strip_prefix('"') {
                let mut escaped = false;
                let end = rest
                    .find(|ch| {
                        let closing = !escaped && ch == '"';
                        escaped = !escaped && ch == '\\';
                        closing
                    })
                    .expect("未闭合的字符串");
                src = &rest[end + 1..];
                continue;
            }
            if let Some(raw) = literal.strip_prefix('r') {
                let hashes = raw.len() - raw.trim_start_matches('#').len();
                if let Some(rest) = raw[hashes..].strip_prefix('"') {
                    let close = format!("\"{}", &raw[..hashes]);
                    let end = rest.find(&close).expect("未闭合的 raw 字符串");
                    src = &rest[end + close.len()..];
                    continue;
                }
            }
            // 字符字面量（包括字节字符）不应把括号传给源码锁；生命周期不是字符字面量。
            if let Some(rest) = literal.strip_prefix('\'') {
                let end = if let Some(escaped) = rest.strip_prefix('\\') {
                    escaped
                        .get(1..)
                        .and_then(|tail| tail.find('\''))
                        .map(|n| n + 3)
                } else if let Some(ch) = rest.chars().next() {
                    let len = ch.len_utf8();
                    rest[len..].starts_with('\'').then_some(len + 1)
                } else {
                    None
                };
                if let Some(end) = end {
                    src = &rest[end..];
                    continue;
                }
            }
            let ident = src.strip_prefix("r#").unwrap_or(src);
            let end = ident
                .find(|ch: char| !(ch.is_alphanumeric() || ch == '_'))
                .unwrap_or(ident.len());
            if end != 0 {
                tokens.push(&ident[..end]);
                src = &ident[end..];
            } else {
                let (token, rest) = src.split_at(c.len_utf8());
                tokens.push(token);
                src = rest;
            }
        }
    }
    tokens
}

fn after_group<'a, 's>(tokens: &'a [&'s str], open: &str, close: &str) -> &'a [&'s str] {
    if tokens.first() != Some(&open) {
        return tokens;
    }
    let mut depth = 1;
    for (i, token) in tokens.iter().enumerate().skip(1) {
        if *token == open {
            depth += 1;
        } else if *token == close {
            depth -= 1;
            if depth == 0 {
                return &tokens[i + 1..];
            }
        }
    }
    panic!("未闭合的 {open}");
}

fn group_contents<'a, 's>(tokens: &'a [&'s str], open: &str, close: &str) -> &'a [&'s str] {
    let end = tokens.len() - after_group(tokens, open, close).len();
    &tokens[1..end - 1]
}

fn check_public_surface(src: &str) -> Result<(), String> {
    let tokens = surface_tokens(src);
    let forbidden_trait = |name| matches!(name, "Default" | "From" | "Deserialize");
    let mut public = Vec::new();
    let mut private = Vec::new();
    let mut depth = 0;
    let mut owner = "";
    for i in 0..tokens.len() {
        let tail = &tokens[i..];
        match tail {
            ["{", ..] => depth += 1,
            ["}", ..] => {
                depth -= 1;
                if depth == 0 {
                    owner = "";
                }
            }
            ["#", "[", "derive" | "cfg_attr", ..] => {
                let attr = group_contents(&tail[1..], "[", "]");
                let forbidden = attr.windows(2).enumerate().any(|(j, pair)| {
                    pair == ["derive", "("]
                        && group_contents(&attr[j + 1..], "(", ")")
                            .iter()
                            .any(|name| forbidden_trait(name))
                });
                if forbidden {
                    return Err("禁用 Default / From / Deserialize 派生".into());
                }
            }
            ["impl", rest @ ..] => {
                let head = after_group(rest, "<", ">");
                // 读取 trait/类型路径末段，而非泛型实参、where 约束或函数体。
                let path_end = head
                    .iter()
                    .position(|t| matches!(*t, "<" | "for" | "where" | "{"));
                if let Some(end) = path_end.filter(|&end| end > 0) {
                    let name = head[end - 1];
                    let after_type = after_group(&head[end..], "<", ">");
                    if after_type.first() == Some(&"for") {
                        if forbidden_trait(name) {
                            return Err(format!("禁用 impl {name}"));
                        }
                    } else if depth == 0 {
                        owner = name;
                    }
                }
            }
            ["Direction", ":", ":", "Up" | "Down", ..]
            | ["UPGRADE_TOTAL_SEGMENTS" | "center_pair_facts" | "pair_domain_ok", ..]
            | ["fn", "new" | "try_new", ..] => {
                return Err(format!("禁用 token：{:?}", tail.get(..2)))
            }
            ["pub", "fn" | "struct" | "enum", name, rest @ ..] => {
                let kind = tail[1];
                if depth == 0 {
                    public.push(("", kind, *name));
                } else if depth == 1 && !owner.is_empty() && kind == "fn" {
                    if !matches!(rest, ["(", "&", "self", ..] | ["(", "self", ..]) {
                        return Err(format!("公开方法 {owner}::{name} 必须接收 self"));
                    }
                    public.push((owner, kind, *name));
                } else {
                    return Err(format!("禁止在此公开 {kind} {name}"));
                }
            }
            ["pub", "(" | "async" | "const" | "unsafe" | "extern" | "union" | "trait" | "type"
            | "static" | "mod" | "use" | "macro", ..] => {
                return Err(format!("禁用公开项：pub {}", tail[1]));
            }
            ["pub", ..] => return Err(format!("不允许公开字段或未知公开项：{:?}", tail.get(1))),
            // `fn(...)` 是函数指针类型（如 seed_build 的返回类型），不是函数声明。
            ["fn", "(", ..] => {}
            ["fn", name, ..] if depth == 0 && tokens.get(i.wrapping_sub(1)) != Some(&"pub") => {
                private.push(*name);
            }
            _ => {}
        }
    }

    let mut expected = vec![
        ("", "fn", "judge_trend_formation"),
        ("", "enum", "PairState"),
        ("", "enum", "WindowOrigin"),
        ("PairState", "fn", "label"),
    ];
    for (ty, methods) in [
        ("UnitSpan", "range units"),
        (
            "CenterNode",
            "ordinal members break_unit is_settled r5_witness center",
        ),
        (
            "PairJudgment",
            "left right connectors outcome state is_final formed",
        ),
        ("FormedTrend", "direction pair"),
        (
            "TrendFormation",
            "unit_level unit_count centers pairs final_pairs consolidation formed_open_center",
        ),
    ] {
        expected.push(("", "struct", ty));
        expected.extend(methods.split_whitespace().map(|method| (ty, "fn", method)));
    }
    public.sort_unstable();
    expected.sort_unstable();
    if public != expected {
        return Err(format!(
            "公开面与 DESIGN §3 不符：实际 {public:?}，期望 {expected:?}"
        ));
    }
    private.sort_unstable();
    if private != ["confirmed", "seed_build", "span"] {
        return Err(format!("私有自由函数与 DESIGN §4 不符：{private:?}"));
    }
    Ok(())
}
#[cfg(issue1426_fabricated_evidence_refusal)]
use newchan_rust::theta_v0::classifier::trend_formation::UnitSpan;

// 18. 编译负例（DESIGN §10 #18）：五个证据结构体完整字面量构造均须被拒（5 条 E0451 + 1 条私有类型
//     `trend_formation::Chain` 错误，块长 ≤ 20 行）。
// cargo rustc --locked --test trend_formation_1426 -- --cfg issue1426_fabricated_evidence_refusal
#[cfg(issue1426_fabricated_evidence_refusal)]
#[rustfmt::skip]
fn fabricated_evidence_literals_must_fail(u1: UnitSpan, u2: UnitSpan, c: CenterNode, p: &PairJudgment) {
    let _ = UnitSpan { start: 0, units: Box::new([]) };
    let _ = CenterNode { ordinal: 0, members: u1, break_unit: None, r5_witness: R5Witness::Absent(R5Gap::Open), center: None };
    let _ = PairJudgment { left: c.clone(), right: c, connectors: u2, outcome: PairOutcome::PendingUpgrade, origin: WindowOrigin::MoveStartGuaranteed };
    let _ = FormedTrend { pair: p, direction: Direction::Up };
    let _ = TrendFormation { unit_level: 0, unit_count: 0, origin: WindowOrigin::MoveStartGuaranteed, chain: todo!() };
}

// 形成侧标签、已声明的归属和 R5 视图不是 FormedTrend，入口也没有隐式归属。
// cargo rustc --locked --test trend_formation_1426 -- --cfg issue1426_formation_type_refusal
#[cfg(issue1426_formation_type_refusal)]
fn formation_types_must_not_bypass_credentials(pair: &PairJudgment, units: &[UnitRange]) {
    let _: FormedTrend<'_> = pair.state().unwrap();
    let _: FormedTrend<'_> = WindowOrigin::MoveStartGuaranteed;
    let _: FormedTrend<'_> = pair.right().r5_witness();
    let _ = judge_trend_formation(0, units);
}
