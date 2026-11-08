//! #1978：流首段的起点按 xianduan §7.1 第 5 条越过扫描种子时，候选发布的特征事实只能来自本段起点之后
//! （起点之前的笔是未分段前缀）。S 写者按 `[start_stroke, observed_through]` 投影 CC-012 `stroke_refs`、
//! 按 `raw_elements` 投影 CC-055 `member_of`；事实越界即发布自相矛盾的两条事实（S86 第 75 代被来源核拒收）。
use super::super::config::ThetaConfig;
use super::super::types::{Bar, Direction, Stroke};
use super::second_fold::{SecondCandidateId, SecondFoldStore};
use super::segment::{
    divide_segments_with_facts, divide_segments_with_facts_store, SegmentCandidateFact,
    SegmentFacts,
};

/// `.chanlun/review-results/1488-acceptance/s86/bars.s86.json`（开、高、低、收）。前 75 根只有三笔：
/// 向下 2248→1551、向上 1551→2990、向下 2990→792，流首段起点从种子（第 0 笔）挪到第 2 笔。
const S86: [(i64, i64, i64, i64); 86] = [
    (1000, 1341, 961, 1151),
    (1151, 1492, 1112, 1302),
    (1302, 1644, 1264, 1454),
    (1454, 1795, 1415, 1605),
    (1605, 1946, 1566, 1756),
    (1756, 2097, 1717, 1907),
    (1907, 2248, 1868, 2058),
    (2058, 2202, 1822, 2012),
    (2012, 2157, 1777, 1967),
    (1967, 2111, 1731, 1921),
    (1921, 2066, 1686, 1876),
    (1876, 2021, 1641, 1831),
    (1831, 1976, 1596, 1786),
    (1786, 1931, 1551, 1741),
    (1741, 1999, 1619, 1809),
    (1809, 2065, 1685, 1875),
    (1875, 2131, 1751, 1941),
    (1941, 2198, 1818, 2008),
    (2008, 2264, 1884, 2074),
    (2074, 2330, 1950, 2140),
    (2140, 2396, 2016, 2206),
    (2206, 2462, 2082, 2272),
    (2272, 2528, 2148, 2338),
    (2338, 2594, 2214, 2404),
    (2404, 2660, 2280, 2470),
    (2470, 2726, 2346, 2536),
    (2536, 2792, 2412, 2602),
    (2602, 2858, 2478, 2668),
    (2668, 2924, 2544, 2734),
    (2734, 2990, 2610, 2800),
    (2800, 2949, 2569, 2759),
    (2759, 2915, 2535, 2725),
    (2725, 2884, 2504, 2694),
    (2694, 2853, 2473, 2663),
    (2663, 2821, 2441, 2631),
    (2631, 2789, 2409, 2599),
    (2599, 2758, 2378, 2568),
    (2568, 2727, 2347, 2537),
    (2537, 2696, 2316, 2506),
    (2506, 2665, 2285, 2475),
    (2475, 2634, 2254, 2444),
    (2444, 2603, 2223, 2413),
    (2413, 2572, 2192, 2382),
    (2382, 2541, 2161, 2351),
    (2351, 2510, 2130, 2320),
    (2320, 2479, 2099, 2289),
    (2289, 2448, 2068, 2258),
    (2258, 2417, 2037, 2227),
    (2227, 2386, 2006, 2196),
    (2196, 2355, 1975, 2165),
    (2165, 2324, 1944, 2134),
    (2134, 2272, 1892, 2082),
    (2082, 2222, 1842, 2032),
    (2032, 2172, 1792, 1982),
    (1982, 2122, 1742, 1932),
    (1932, 2072, 1692, 1882),
    (1882, 2022, 1642, 1832),
    (1832, 1972, 1592, 1782),
    (1782, 1922, 1542, 1732),
    (1732, 1872, 1492, 1682),
    (1682, 1822, 1442, 1632),
    (1632, 1772, 1392, 1582),
    (1582, 1722, 1342, 1532),
    (1532, 1672, 1292, 1482),
    (1482, 1622, 1242, 1432),
    (1432, 1572, 1192, 1382),
    (1382, 1522, 1142, 1332),
    (1332, 1472, 1092, 1282),
    (1282, 1422, 1042, 1232),
    (1232, 1372, 992, 1182),
    (1182, 1322, 942, 1132),
    (1132, 1272, 892, 1082),
    (1082, 1222, 842, 1032),
    (1032, 1172, 792, 982),
    (982, 1250, 870, 1060),
    (1060, 1327, 947, 1137),
    (1137, 1404, 1024, 1214),
    (1214, 1483, 1103, 1293),
    (1293, 1560, 1180, 1370),
    (1370, 1637, 1257, 1447),
    (1447, 1715, 1335, 1525),
    (1525, 1792, 1412, 1602),
    (1602, 1871, 1491, 1681),
    (1681, 1948, 1568, 1758),
    (1758, 2025, 1645, 1835),
    (1835, 2102, 1722, 1912),
];

fn bars(rows: &[(i64, i64, i64, i64)]) -> Vec<Bar> {
    rows.iter()
        .enumerate()
        .map(|(i, &(open, high, low, close))| Bar {
            source_index: i,
            timestamp: 1_700_000_000 + 60 * i as i64,
            open,
            high,
            low,
            close,
            volume: 1.0,
            untradable: false,
        })
        .collect()
}

/// 确定性锯齿：每腿 3..=40 根、每根漂移 20..=90、K 线全幅 380。200 条 × 160 根里流首段起点越过种子
/// 的前缀有数千个（修前实测越界候选 7,067 个、110 条序列）。
fn zigzag(seed: u64) -> Vec<Bar> {
    let mut state = seed
        .wrapping_mul(6364136223846793005)
        .wrapping_add(1442695040888963407);
    let mut next = |m: u64| {
        state = state
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        (state >> 33) % m
    };
    let (mut mid, mut up, mut left) = (5_000i64, next(2) == 0, 3 + next(38) as usize);
    let mut rows = Vec::with_capacity(160);
    for _ in 0..160 {
        if left == 0 {
            up = !up;
            left = 3 + next(38) as usize;
        }
        left -= 1;
        let step = 20 + next(71) as i64;
        let open = mid;
        mid += if up { step } else { -step };
        rows.push((open, mid.max(open) + 190, mid.min(open) - 190, mid));
    }
    bars(&rows)
}

/// 同一前缀的两种 parser 入口：无游标簿（研究/回放）与 S 写者的 K1 游标簿。
fn both_entries(bars: &[Bar], config: &ThetaConfig) -> [SegmentFacts; 2] {
    let (_, plain) = super::parse_layer_with_inclusion_facts(bars, config);
    let (_, stored, _) = super::parse_layer_with_inclusion_facts_store(
        bars,
        config,
        SecondFoldStore::from_parse_config(&config.parse),
    );
    [plain, stored].map(|f| f.segment_facts.expect("观察模式必有段事实"))
}

fn outside_own_range(c: &SegmentCandidateFact) -> Vec<usize> {
    c.first
        .raw_elements
        .iter()
        .chain(c.second.iter().flat_map(|s| s.raw_elements.iter()))
        .map(|e| e.stroke_idx)
        .filter(|&k| k < c.start_stroke || k > c.observed_through)
        .collect()
}

/// 流首段候选（`candidates[0]`）的起点是否越过扫描种子（`seeds` 末项）。
fn first_start_moved(facts: &SegmentFacts) -> bool {
    match (facts.candidates.first(), facts.seeds.last()) {
        (Some(c), Some(seed)) => c.start_stroke > seed.start_stroke,
        _ => false,
    }
}

#[test]
fn s86_first_segment_members_start_at_its_own_start() {
    let config = ThetaConfig::for_s_structure_writer().unwrap();
    let all = bars(&S86);
    let mut moved = 0;
    for n in 1..=all.len() {
        for facts in both_entries(&all[..n], &config) {
            moved += usize::from(first_start_moved(&facts));
            for c in &facts.candidates {
                assert_eq!(
                    outside_own_range(c),
                    Vec::<usize>::new(),
                    "S86 第 {n} 代：候选 start={} observed_through={} 的特征元素越出本段",
                    c.start_stroke,
                    c.observed_through
                );
            }
        }
    }
    assert_eq!(
        moved, 24,
        "g75–g86 两种入口各 12 个前缀的流首段起点越过种子"
    );
}

#[test]
fn zigzag_candidate_members_start_at_their_own_start() {
    let config = ThetaConfig::for_s_structure_writer().unwrap();
    let (mut moved, mut outside) = (0, Vec::new());
    for series in 0..200u64 {
        let all = zigzag(series);
        for n in 1..=all.len() {
            for facts in both_entries(&all[..n], &config) {
                moved += usize::from(first_start_moved(&facts));
                for c in &facts.candidates {
                    let bad = outside_own_range(c);
                    if !bad.is_empty() && outside.len() < 5 {
                        outside.push((series, n, c.start_stroke, c.observed_through, bad));
                    }
                }
            }
        }
    }
    assert!(
        moved > 1_000,
        "语料须实际覆盖流首段起点越过种子，实测 {moved}"
    );
    assert!(
        outside.is_empty(),
        "候选特征元素越出本段（series, 前缀, start, observed_through, 越界笔）：{outside:?}"
    );
}

struct Parsed {
    layer: super::ParseLayer,
    facts: SegmentFacts,
    store: Option<SecondFoldStore>,
}

fn parsed_both(bars: &[Bar], config: &ThetaConfig) -> [Parsed; 2] {
    let (plain_layer, plain) = super::parse_layer_with_inclusion_facts(bars, config);
    let (stored_layer, stored, store) = super::parse_layer_with_inclusion_facts_store(
        bars,
        config,
        SecondFoldStore::from_parse_config(&config.parse),
    );
    [
        (plain_layer, plain, None),
        (stored_layer, stored, Some(store)),
    ]
    .map(|(layer, facts, store)| Parsed {
        layer,
        facts: facts.segment_facts.expect("观察模式必有段事实"),
        store,
    })
}

fn with_seed_scan_facts<T>(f: impl FnOnce() -> T) -> T {
    super::segment::SEED_SCAN_FACTS.with(|c| c.set(true));
    let out = f();
    super::segment::SEED_SCAN_FACTS.with(|c| c.set(false));
    out
}

/// 重扫只改发布的特征事实：段划分、已确认段的终结（段端、结果、缺口事实、触发笔、终结尝试、破坏事实）
/// 与种子扫描（修复前口径）逐位相同；每个已确认且起点越过种子的流首段都在同一笔复现终结；S 写者
/// 按第二种候选身份查的游标都在本轮簿内。
#[test]
fn rescan_keeps_segments_and_confirmed_terminations() {
    let config = ThetaConfig::for_s_structure_writer().unwrap();
    let corpora: Vec<Vec<Bar>> = std::iter::once(bars(&S86))
        .chain((0..200u64).map(zigzag))
        .collect();
    super::segment::RESCAN_MISMATCHES.with(|c| c.set(0));
    let (mut confirmed_moved, mut pending_moved) = (0, 0);
    for all in &corpora {
        for n in 1..=all.len() {
            let fixed = parsed_both(&all[..n], &config);
            let seed = with_seed_scan_facts(|| parsed_both(&all[..n], &config));
            for (fixed, seed) in fixed.iter().zip(&seed) {
                assert_eq!(
                    fixed.layer.segments, seed.layer.segments,
                    "前缀 {n} 段划分变了"
                );
                assert_eq!(fixed.facts.candidates.len(), seed.facts.candidates.len());
                for (i, (a, b)) in fixed
                    .facts
                    .candidates
                    .iter()
                    .zip(&seed.facts.candidates)
                    .enumerate()
                {
                    let moved = i == 0 && first_start_moved(&seed.facts);
                    if b.end_stroke.is_none() {
                        pending_moved += usize::from(moved);
                        continue;
                    }
                    confirmed_moved += usize::from(moved);
                    assert_eq!(
                        (a.start_stroke, a.end_stroke, a.result, a.trigger_stroke),
                        (b.start_stroke, b.end_stroke, b.result, b.trigger_stroke),
                        "前缀 {n} 第 {i} 个已确认候选的终结变了"
                    );
                    assert_eq!(
                        a.strict, b.strict,
                        "前缀 {n} 第 {i} 个已确认候选的缺口事实变了"
                    );
                    assert_eq!(a.termination_attempts, b.termination_attempts);
                    assert_eq!(
                        a.fact_vector, b.fact_vector,
                        "前缀 {n} 第 {i} 个已确认候选的破坏事实变了"
                    );
                }
                if let Some(store) = &fixed.store {
                    for c in &fixed.facts.candidates {
                        let Some(second) = &c.second else { continue };
                        let seg_dir = fixed.layer.strokes[c.start_stroke].direction;
                        let id = super::second_fold::SecondCandidateId {
                            seg_dir,
                            b_stroke: second.from_stroke - 1,
                            candidate_extreme: second.candidate_extreme,
                        };
                        assert!(
                            store.cursor(&id).is_some(),
                            "前缀 {n}：第二种候选不在本轮游标簿 {id:?}"
                        );
                    }
                }
            }
        }
    }
    assert_eq!(
        super::segment::RESCAN_MISMATCHES.with(|c| c.get()),
        0,
        "重扫复现不了种子扫描的终结"
    );
    assert!(
        confirmed_moved > 0 && pending_moved > 1_000,
        "语料须覆盖两类：已确认 {confirmed_moved}、未确认 {pending_moved}"
    );
    println!("tb1978 起点越过种子的流首段：已确认 {confirmed_moved}，未确认 {pending_moved}");
}

/// 按端点价连成笔，方向由价差定；bar 下标只占位。
fn chain(points: &[i64]) -> Vec<Stroke> {
    points
        .windows(2)
        .enumerate()
        .map(|(i, p)| Stroke {
            direction: if p[1] > p[0] {
                Direction::Up
            } else {
                Direction::Down
            },
            start_index: 4 * i,
            end_index: 4 * i + 4,
            start_price: p[0],
            end_price: p[1],
        })
        .collect()
}

/// PR #1987 正式审查 a2（opus）反例一，前缀 8。种子第 0 笔；主扫描里第 1 笔 [50,400] 先后并进第 3、5 笔，
/// 标准序列只剩两个元素，没有折叠。流首段起点 2 越过种子，从起点重扫得 [80,120]、[150,300]、[130,250]，
/// b 处有缺口且 c 没有封闭，折出第二种候选 (UP, 5, 300)。S 写者拿发布的身份到返回的游标簿查游标
/// （`tb02c::build`），查不到即 IdentityConflict；不在簿里的游标也进不了 checkpoint。前缀 9 的第 8 笔
/// 新高 350 作废该候选，作废态同样要能在簿里查到。
#[test]
fn published_second_candidate_cursor_is_in_the_returned_store() {
    let config = ThetaConfig::for_s_structure_writer().unwrap();
    let strokes = chain(&[100, 400, 50, 120, 80, 300, 150, 250, 130, 350]);
    for n in 3..=strokes.len() {
        let (_, _, facts, store) = divide_segments_with_facts_store(
            &strokes[..n],
            &config.parse,
            SecondFoldStore::from_parse_config(&config.parse),
        );
        for c in &facts.candidates {
            let Some(second) = &c.second else { continue };
            let id = SecondCandidateId {
                seg_dir: strokes[c.start_stroke].direction,
                b_stroke: second.from_stroke - 1,
                candidate_extreme: second.candidate_extreme,
            };
            assert!(
                store.cursor(&id).is_some(),
                "前缀 {n}：候选 start={} 发布的第二种候选不在返回的游标簿：{id:?}",
                c.start_stroke
            );
        }
    }
}

/// 反例二（同一审查）。主扫描把起点之前的第 1 笔 [50,200] 与第 3 笔并成 [80,200]，窗口
/// ([80,200],[150,300],[130,250]) 无缺口，按第一种情况在第 7 笔确认段 [2,4]。从起点重扫 a=[80,120]
/// 有缺口、c 未封闭，走第二种情况：前缀 8 停在 OPEN，前缀 9 第 8 笔新高 350 作废候选，都复现不出终结，
/// 于是退回种子事实（含第 1 笔），S 写者守卫 `candidate_members_inside` 拒写；段已确认、不随前缀变，
/// 此后每一代都拒写。本锁按 §7.1 第 5 条现行口径断言候选成员不早于本段起点；若裁定改判第 5 条，
/// 本锁随写者守卫一起改。
#[test]
fn confirmed_first_segment_publishes_only_its_own_members() {
    let config = ThetaConfig::for_s_structure_writer().unwrap();
    let strokes = chain(&[100, 200, 50, 120, 80, 300, 150, 250, 130, 350]);
    for n in 3..=strokes.len() {
        let prefix = &strokes[..n];
        let (_, _, plain) = divide_segments_with_facts(prefix, &config.parse);
        let (_, _, stored, _) = divide_segments_with_facts_store(
            prefix,
            &config.parse,
            SecondFoldStore::from_parse_config(&config.parse),
        );
        for facts in [plain, stored] {
            for c in &facts.candidates {
                assert_eq!(
                    outside_own_range(c),
                    Vec::<usize>::new(),
                    "前缀 {n}：候选 start={} end={:?} 的特征元素越出本段",
                    c.start_stroke,
                    c.end_stroke
                );
            }
        }
    }
}
