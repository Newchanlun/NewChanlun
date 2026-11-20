use std::num::NonZeroU128;

use super::{Fraction, RatePpb};

pub(super) struct CostTotal {
    value: u128,
    proxy: bool,
}
pub(super) struct ZeroTotal {
    proxy: bool,
}
pub(super) struct NonZeroTotal {
    value: NonZeroU128,
    proxy: bool,
}

pub(super) enum SplitTotal {
    Zero(ZeroTotal),
    NonZero(NonZeroTotal),
}

impl CostTotal {
    /// 共同单位为 ppb × fee.denominator。只在正分母分支作比较。
    pub fn new(
        fee: &Fraction,
        slippage: RatePpb,
        latency: RatePpb,
        holding: RatePpb,
        proxy: bool,
    ) -> Self {
        let fee_ppb = u128::from(fee.numerator()) * 1_000_000_000;
        let others = [slippage, latency, holding]
            .iter()
            .map(|rate| u128::from(rate.0))
            .sum::<u128>();
        Self {
            value: fee_ppb + fee_ppb + others * u128::from(fee.denominator().get()),
            proxy,
        }
    }

    pub fn split(self) -> SplitTotal {
        match NonZeroU128::new(self.value) {
            Some(value) => SplitTotal::NonZero(NonZeroTotal {
                value,
                proxy: self.proxy,
            }),
            None => SplitTotal::Zero(ZeroTotal { proxy: self.proxy }),
        }
    }
}

impl ZeroTotal {
    pub fn is_proxy(&self) -> bool {
        self.proxy
    }
}

impl NonZeroTotal {
    pub fn value(&self) -> u128 {
        self.value.get()
    }
    pub fn is_proxy(&self) -> bool {
        self.proxy
    }
}
