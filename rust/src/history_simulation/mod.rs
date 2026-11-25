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

/// #1407 C3：/3 是静态精确放行合同；/4 是显式 FX/2 动态放行合同。
/// /1 与 /2 历史模拟库仅供只读核查；无撮合模块的执行骨架仍用 /1。
pub const EXACT_PROFILE_REVISION: &str = "x-execution-profile/3";
pub const FX_RELEASE_PROFILE_REVISION: &str = "x-execution-profile/4";
