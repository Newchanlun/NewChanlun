//! #1978（`xianduan.md` §7.1 第 5／9 条，#1978 修订裁定 2026-11-08）：流首段的终结按本段自己从起点开始的
//! 特征序列判，起点之前的笔一律不参与（`067:16`／`:18`、`071:18`／`:28`、`078:24`／`:26`）。
//!
//! 第 5 条的每个起点取值点（种子，及其后每根刷新段方向反向极值的同向笔）各开一条扫描。以起点 p 起的段
//! 只能终于下一个取值点之前：段端 e 越过它时，按第 5 条在 e 处取到的起点已不是 p。各起点之间按第 9 条
//! 发布：最早一个未出局的起点已确认 ⟹ 发布它，其后的起点作废；它未定 ⟹ 封住，较晚起点上已确认的段
//! 也不发布。出局只会单调推进，发布后的段不随前缀改写。全量主循环与增量续扫共用本扫描（#804）。

use super::super::feature_seq::stroke_high_low;
use super::super::second_fold::SecondFoldStore;
use super::*;

/// 一个候选起点在当前前缀上的状态（§7.1 第 9 条）。只有 `Open → Confirmed` 与 `Open → Out` 两种转移。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum StartState {
    /// 下一个起点尚未出现，或其上还有 b 早于下一个起点的候选未定。
    Open,
    /// 可接受的终结已过段端门：段 = `[start, hit.k − 1]`，在光标 `at` 处确认。
    Confirmed { hit: TriggerHit, at: usize },
    /// 出局：光标已到下一个起点，且其上 b 早于它的候选都已作废或被跳过；此后不会再有可接受的候选。
    Out { at: usize },
}

/// 第 5 条的一个起点取值点及从它起的特征序列扫描。
pub(super) struct FirstStart {
    pub(super) start: usize,
    /// 下一个起点取值点；以本起点起的段只能终于它之前。
    next: Option<usize>,
    pub(super) feat: FeatureSeqState,
    state: StartState,
    pub(super) attempts: Vec<SegmentEndCheck>,
    pub(super) invalid_from: Option<usize>,
}

impl FirstStart {
    fn new(start: usize, dir: Direction, config: &ParseConfig, observe: bool) -> Self {
        let mut feat = FeatureSeqState::new(
            dir,
            ExtendMode::Strict,
            config.tail_window,
            config.second_seq_scan_window,
            config.tangency,
        );
        if observe {
            feat.observe();
        }
        FirstStart {
            start,
            next: None,
            feat,
            state: StartState::Open,
            attempts: Vec::new(),
            invalid_from: None,
        }
    }

    fn is_open(&self) -> bool {
        self.state == StartState::Open
    }

    /// 第 9 条「出局」：光标已到下一个起点 h，且最早的未定候选（若有）不早于 h。候选按序判定，其前的
    /// 候选都已作废或被跳过；b ≥ h 的候选段端 ≥ h，本起点不可接受，不计。
    fn exhausted(&self, cursor: usize) -> bool {
        self.next
            .is_some_and(|h| cursor >= h && self.feat.undecided_candidate().is_none_or(|b| b > h))
    }
}

/// 流首段扫描的结果。
pub(super) struct FirstSegment {
    /// 发布的流首段：终结命中（段 = `[deciding.start, hit.k − 1]`）与确认光标；`None` = 本前缀未发布。
    pub(super) published: Option<(TriggerHit, usize)>,
    /// 发布事实的来源：发布的起点；未发布时为最早一个未出局的起点（第 9 条封住处）。
    pub(super) deciding: FirstStart,
    /// 未发布，且较晚的起点上已有确认的段在等待（第 9 条封住）。
    pub(super) sealed: bool,
    /// 发布或等待所依据的判定可能随输入末笔改写（增量层 unsealed，#88／#1420 同一规则）。
    pub(super) unsealed: bool,
    /// 发布所依据的扫描中，尾窗挤掉过可准入候选的最早起点（#1604 C-04）。
    pub(super) tail_truncated_from: Option<usize>,
    /// 首个段端门失败 `(起点, 段端, 命中)`（§7.1 第 6 条）。按第 5 条取起点时首段门恒过，
    /// 只在 TestOnly 起点退回种子时可达。
    pub(super) invalid: Option<(usize, usize, TriggerHit)>,
    pub(super) store: Option<SecondFoldStore>,
}

/// §7.1 第 5 条的起点取值点：同向笔 `j` 的起点在段方向反向上严格比现任起点 `best` 更极端（并列取先者）。
fn refreshes_start(strokes: &[Stroke], best: usize, j: usize, dir: Direction) -> bool {
    #[cfg(test)]
    if FIRST_START_AT_SEED.with(|c| c.get()) {
        return false;
    }
    match dir {
        Direction::Up => strokes[j].start_price < strokes[best].start_price,
        Direction::Down => strokes[j].start_price > strokes[best].start_price,
    }
}

/// 自种子 `seed` 扫流首段。所有起点共用 S 层游标簿 `store`：同一第二种候选在不同起点上身份相同，
/// 共用一个游标，预算不重复计；折叠过的游标都留在返回的簿里（随 checkpoint 带出）。
pub(super) fn scan(
    strokes: &[Stroke],
    seed: usize,
    config: &ParseConfig,
    observe: bool,
    mut store: Option<SecondFoldStore>,
) -> FirstSegment {
    let t = config.tangency;
    let min_seg = config.seg_min_strokes as usize;
    let dir = strokes[seed].direction;
    let mut starts = vec![FirstStart::new(seed, dir, config, observe)];
    let mut invalid = None;
    let mut published = None;
    for cursor in seed..strokes.len() {
        let sk = &strokes[cursor];
        let (h, l) = stroke_high_low(sk);
        if sk.direction == dir {
            let newest = starts.last_mut().expect("种子起点恒在");
            if newest.is_open() && refreshes_start(strokes, newest.start, cursor, dir) {
                newest.next = Some(cursor);
                starts.push(FirstStart::new(cursor, dir, config, observe));
            }
            for s in starts.iter_mut().filter(|s| s.is_open()) {
                s.feat.note_trend_stroke(cursor, h, l);
            }
        } else {
            let mut confirmed = None;
            for (i, s) in starts.iter_mut().enumerate().filter(|(_, s)| s.is_open()) {
                s.feat.append(cursor, h, l, strokes);
                s.feat.set_second_store(store.take());
                let trig = s.feat.scan_trigger(strokes);
                store = s.feat.take_second_store();
                let Some(hit) = trig else { continue };
                let end = hit.k - 1;
                if s.next.is_some_and(|next| end >= next) {
                    // 段端处的起点已不是本起点；其前的候选都已判过、无一可接受。
                    s.state = StartState::Out { at: cursor };
                    continue;
                }
                if observe {
                    s.attempts.push(SegmentEndCheck {
                        end_stroke: end,
                        trigger_stroke: hit.through_stroke.max(cursor),
                        minimum_count_met: end - s.start >= min_seg.saturating_sub(1),
                        construction: construction(strokes, s.start, end + 1, t),
                    });
                }
                match end_gate(strokes, s.start, end, min_seg, t) {
                    EndGate::Emit => {
                        s.state = StartState::Confirmed { hit, at: cursor };
                        confirmed = Some(i);
                        break;
                    }
                    gate => {
                        if gate == EndGate::Invalid {
                            s.invalid_from.get_or_insert(s.start);
                            invalid.get_or_insert((s.start, end, hit));
                        }
                        s.feat.skip_trigger(hit.k);
                    }
                }
            }
            // 较晚的起点只在已确认者出局后才可能发布，而已确认者不会出局。
            if let Some(i) = confirmed {
                starts.truncate(i + 1);
            }
        }
        for s in starts
            .iter_mut()
            .filter(|s| s.is_open() && s.exhausted(cursor))
        {
            s.state = StartState::Out { at: cursor };
        }
        let live = starts
            .iter()
            .find(|s| !matches!(s.state, StartState::Out { .. }))
            .expect("最新起点没有下一个起点，不会出局");
        if let StartState::Confirmed { hit, at } = live.state {
            published = Some((hit, at));
            break;
        }
    }
    let first = starts
        .iter()
        .position(|s| !matches!(s.state, StartState::Out { .. }))
        .expect("最新起点没有下一个起点，不会出局");
    let used = &starts[..=first];
    let last_out = used[..first]
        .iter()
        .filter_map(|s| match s.state {
            StartState::Out { at } => Some(at),
            _ => None,
        })
        .max();
    let unsealed = used.iter().any(|s| s.feat.skipped_secondkind())
        || (published.is_some() && last_out.is_some_and(|at| at + 1 >= strokes.len()));
    let tail_truncated_from = used
        .iter()
        .filter(|s| s.feat.tail_truncated())
        .map(|s| s.start)
        .min();
    let sealed = published.is_none()
        && starts
            .last()
            .is_some_and(|s| matches!(s.state, StartState::Confirmed { .. }));
    let deciding = starts.into_iter().nth(first).expect("上句已定位");
    FirstSegment {
        published,
        deciding,
        sealed,
        unsealed,
        tail_truncated_from,
        invalid,
        store,
    }
}
