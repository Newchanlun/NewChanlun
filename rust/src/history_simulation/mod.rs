//! #1381：X 内已知前沿 bar 批模型。
pub(crate) mod intake;
pub mod model;
#[cfg(unix)]
pub mod runtime;
pub mod store;
#[cfg(test)]
pub(crate) mod tests;

mod capacity;
#[cfg(unix)]
mod exact_wire;

/// 只标识已接入精确命令的历史模拟库；无撮合模块的执行骨架仍用 /1。
pub const EXACT_PROFILE_REVISION: &str = "x-execution-profile/2";
