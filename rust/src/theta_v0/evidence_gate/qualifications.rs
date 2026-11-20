use std::collections::BTreeMap;

use super::{BlockUnit, EvidenceGate};

/// UTC Unix 秒；首末 bar 都计入，故共享边界 bar 的两窗也相交。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct WindowSpan {
    pub first_bar: i64,
    pub last_bar: i64,
}

impl WindowSpan {
    fn on_grid(ts: i64) -> bool {
        ts.rem_euclid(60) == 0
    }

    fn valid(self) -> bool {
        self.first_bar < self.last_bar
            && Self::on_grid(self.first_bar)
            && Self::on_grid(self.last_bar)
    }

    fn contains_range(self, first: i64, last: i64) -> bool {
        first >= self.first_bar && last <= self.last_bar
    }

    fn duration(self) -> i128 {
        i128::from(self.last_bar) - i128::from(self.first_bar)
    }
}

pub(crate) struct Block {
    pub index: i64,
    pub events: Vec<usize>,
}

pub(crate) struct QualifiedWindow {
    pub span: WindowSpan,
    pub blocks: Vec<Block>,
}

pub(crate) struct QualifiedWindows(pub Vec<QualifiedWindow>);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WindowGap {
    UnsupportedGranularity,
    UnsupportedBlockUnit,
    TooFewWindows { got: usize, need: u32 },
    InvalidHistory,
    InvalidWindow,
    OverlappingWindows,
    InsufficientCoverage,
    InvalidEvent { index: usize },
    UnorderedEvents { index: usize },
    TooFewEvents { got: usize, need: u32 },
    TooFewBlocks { got: usize, need: u32 },
}

impl EvidenceGate {
    /// ADR 0022：窗口资格与数值过线不同；事件与非空时间块从原样本推得。
    pub(crate) fn qualify(
        &self,
        data: WindowSpan,
        granularity: &str,
        windows: &[WindowSpan],
        events: &[(i64, i64)],
    ) -> Result<QualifiedWindows, WindowGap> {
        if granularity != "1m" {
            return Err(WindowGap::UnsupportedGranularity);
        }
        if self.block_unit != BlockUnit::CalendarMonthUTC {
            return Err(WindowGap::UnsupportedBlockUnit);
        }
        if windows.len() < self.min_windows as usize {
            return Err(WindowGap::TooFewWindows {
                got: windows.len(),
                need: self.min_windows,
            });
        }
        if !data.valid() {
            return Err(WindowGap::InvalidHistory);
        }
        let mut spans = windows.to_vec();
        if spans
            .iter()
            .any(|&span| !span.valid() || !data.contains_range(span.first_bar, span.last_bar))
        {
            return Err(WindowGap::InvalidWindow);
        }
        spans.sort_unstable_by_key(|span| span.first_bar);
        if spans
            .windows(2)
            .any(|pair| pair[0].last_bar >= pair[1].first_bar)
        {
            return Err(WindowGap::OverlappingWindows);
        }
        let coverage = spans.iter().map(|span| span.duration()).sum::<i128>();
        let (num, den) = self.min_coverage;
        if coverage * i128::from(den) < data.duration() * i128::from(num) {
            return Err(WindowGap::InsufficientCoverage);
        }

        let mut grouped = vec![BTreeMap::<i64, Vec<usize>>::new(); spans.len()];
        for (index, &(entry, exit)) in events.iter().enumerate() {
            if entry > exit
                || !WindowSpan::on_grid(entry)
                || !WindowSpan::on_grid(exit)
                || !data.contains_range(entry, exit)
            {
                return Err(WindowGap::InvalidEvent { index });
            }
            if index != 0 && events[index - 1] >= (entry, exit) {
                return Err(WindowGap::UnorderedEvents { index });
            }
            let pos = spans.partition_point(|span| span.first_bar <= entry);
            if let Some(window) = pos
                .checked_sub(1)
                .filter(|&i| spans[i].contains_range(entry, exit))
            {
                grouped[window]
                    .entry(utc_month(entry))
                    .or_default()
                    .push(index);
            }
        }
        let mut qualified = Vec::with_capacity(spans.len());
        for (span, blocks) in spans.into_iter().zip(grouped) {
            let n = blocks.values().map(Vec::len).sum::<usize>();
            if n < self.min_events as usize {
                return Err(WindowGap::TooFewEvents {
                    got: n,
                    need: self.min_events,
                });
            }
            if blocks.len() < self.min_blocks as usize {
                return Err(WindowGap::TooFewBlocks {
                    got: blocks.len(),
                    need: self.min_blocks,
                });
            }
            qualified.push(QualifiedWindow {
                span,
                blocks: blocks
                    .into_iter()
                    .map(|(index, events)| Block { index, events })
                    .collect(),
            });
        }
        Ok(QualifiedWindows(qualified))
    }
}

/// 将 UTC Unix 秒换成 Gregorian 年 × 12 + (月 - 1)；向下取整支持纪元前时间。
fn utc_month(ts: i64) -> i64 {
    let day = ts.div_euclid(86_400) + 719_468;
    let era = day.div_euclid(146_097);
    let day_of_era = day.rem_euclid(146_097);
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let march_month = (5 * day_of_year + 2) / 153;
    let month = march_month + if march_month < 10 { 3 } else { -9 };
    let year = era * 400 + year_of_era + i64::from(month <= 2);
    year * 12 + month - 1
}
