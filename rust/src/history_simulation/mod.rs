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

/// 只标识已接入模型绑定精确命令的历史模拟库（#1407 C3）；/1 与 /2 仅保留只读封存批核查，不续写。
/// 无撮合模块的执行骨架仍用 /1。
pub const EXACT_PROFILE_REVISION: &str = "x-execution-profile/3";
