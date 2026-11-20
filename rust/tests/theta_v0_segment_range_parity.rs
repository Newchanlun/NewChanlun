//! #1486：以同一份冻结的 CC-013 成员笔，逐整数 tick 对拍 Lean 和生产塔的 L0 区间。

use serde::{Deserialize, Deserializer};
use std::collections::BTreeMap;
use std::str::FromStr;

const BTC: &str =
    include_str!("../../s_session/tests/fixtures/tb02e-real/btc-tail50k-first600.json");
const LEAN: &str = include_str!("fixtures/theta_v0_segment_range_parity.json");

#[derive(Debug, PartialEq, Eq, Deserialize)]
struct Range {
    hi: i64,
    lo: i64,
}

#[derive(Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
enum Direction {
    Up,
    Down,
}

#[derive(Deserialize)]
struct BtcFixture {
    segments: Vec<Record>,
    tower_units: Vec<TowerUnit>,
    discriminating_units: Vec<usize>,
}

#[derive(Deserialize)]
struct TowerUnit {
    dir: Direction,
    #[serde(flatten)]
    range: Range,
}

#[derive(Deserialize)]
struct Record {
    kind: String,
    payload: Payload,
}

#[derive(Deserialize)]
struct Payload {
    data: Segment,
}

#[derive(Deserialize)]
struct Segment {
    result: String,
    construction: Construction,
    stroke_refs: Vec<StrokeRef>,
    geometric_end: Option<GeometricEnd>,
}

#[derive(Deserialize)]
struct Construction {
    #[serde(deserialize_with = "decimal")]
    start_stroke: usize,
    direction: Option<Direction>,
    stroke_indices: Vec<String>,
}

#[derive(Deserialize)]
struct StrokeRef {
    #[serde(deserialize_with = "decimal")]
    stroke_index: usize,
    #[serde(deserialize_with = "decimal")]
    start_price: i64,
    #[serde(deserialize_with = "decimal")]
    end_price: i64,
}

#[derive(Deserialize)]
struct GeometricEnd {
    #[serde(deserialize_with = "decimal")]
    price: i64,
}

#[derive(Deserialize)]
struct LeanFixture {
    schema: String,
    units: Vec<LeanUnit>,
}

#[derive(Deserialize)]
struct LeanUnit {
    start_stroke: usize,
    dir: Direction,
    #[serde(flatten)]
    range: Range,
}

#[test]
fn frozen_l0_ranges_use_member_extremes() {
    let btc: BtcFixture = serde_json::from_str(BTC).unwrap();
    let lean: LeanFixture = serde_json::from_str(LEAN).unwrap();
    assert_eq!(lean.schema, "theta-v0-segment-range-parity/1");

    let mut segments: Vec<_> = btc
        .segments
        .iter()
        .filter(|r| r.kind == "CC-013.segment")
        .map(|r| &r.payload.data)
        .filter(|s| matches!(s.result.as_str(), "CASE_ONE" | "CASE_TWO"))
        .collect();
    segments.sort_by_key(|s| s.construction.start_stroke);
    assert_eq!(segments.len(), 6);
    assert_eq!(segments.len(), btc.tower_units.len());
    assert_eq!(segments.len(), lean.units.len());

    let mut discriminating = Vec::new();
    for (unit, segment) in segments.into_iter().enumerate() {
        let construction = &segment.construction;
        let tower = &btc.tower_units[unit];
        let exported = &lean.units[unit];
        assert_eq!(
            exported.start_stroke, construction.start_stroke,
            "单元 {unit}"
        );
        assert_eq!(
            Some(&exported.dir),
            construction.direction.as_ref(),
            "单元 {unit}"
        );
        assert_eq!(exported.dir, tower.dir, "单元 {unit}");

        let refs: BTreeMap<_, _> = segment
            .stroke_refs
            .iter()
            .map(|r| (r.stroke_index, r))
            .collect();
        assert_eq!(
            refs.len(),
            segment.stroke_refs.len(),
            "单元 {unit} 笔引用重复"
        );
        let indices = construction
            .stroke_indices
            .iter()
            .map(|i| i.parse().unwrap());
        let member_extremes = member_extremes(indices, &refs);
        let start = refs[&construction.start_stroke].start_price;
        let end = segment.geometric_end.as_ref().unwrap().price;
        let geometric_extremes = Range {
            hi: start.max(end),
            lo: start.min(end),
        };

        assert_eq!(
            exported.range, tower.range,
            "单元 {unit}：Lean ≠ 冻结生产塔"
        );
        assert_eq!(
            exported.range, member_extremes,
            "单元 {unit}：Lean ≠ 成员笔"
        );
        if geometric_extremes != member_extremes {
            discriminating.push(unit);
        }
    }
    assert_eq!(btc.discriminating_units, [0, 1, 4, 5]);
    assert_eq!(discriminating, btc.discriminating_units);
}

fn member_extremes(
    indices: impl Iterator<Item = usize>,
    refs: &BTreeMap<usize, &StrokeRef>,
) -> Range {
    let mut prices = indices.flat_map(|i| {
        let stroke = refs[&i];
        [stroke.start_price, stroke.end_price]
    });
    let first = prices.next().expect("完成段无成员笔");
    prices.fold(
        Range {
            hi: first,
            lo: first,
        },
        |range, price| Range {
            hi: range.hi.max(price),
            lo: range.lo.min(price),
        },
    )
}

fn decimal<'de, D, T>(de: D) -> Result<T, D::Error>
where
    D: Deserializer<'de>,
    T: FromStr,
    T::Err: std::fmt::Display,
{
    String::deserialize(de)?
        .parse()
        .map_err(serde::de::Error::custom)
}
