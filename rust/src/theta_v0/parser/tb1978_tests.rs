//! #1978：流首段的起点按 xianduan §7.1 第 5 条越过扫描种子时，候选发布的特征事实只能来自本段起点之后
//! （起点之前的笔是未分段前缀）。S 写者按 `[start_stroke, observed_through]` 投影 CC-012 `stroke_refs`、
//! 按 `raw_elements` 投影 CC-055 `member_of`；事实越界即发布自相矛盾的两条事实（S86 第 75 代被来源核拒收）。
use super::super::config::ThetaConfig;
use super::super::types::Bar;
use super::second_fold::SecondFoldStore;
use super::segment::{SegmentCandidateFact, SegmentFacts};

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
