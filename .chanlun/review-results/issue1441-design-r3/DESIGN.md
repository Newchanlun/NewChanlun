## 目标
让 #1441 成本停止求值器第三轮按构造通过「不信调用方」这道门。P0、P1 v1 仍得 `NotEvaluable(UnavailableCost(Slippage))`。行号均指 5a4033fd。

## 换掉的前提
前两轮共用一句前提：调用方递来证据，求值器校验形状。全部反例都从调用方可填的值进来（公开字段、收文本的装载器），没有一条从编进二进制的原件进来。新前提：调用方只给 profile、修订号、级别；政策、证据门、窗表、样本从登记表按 sha256 取出后解析，计数由样本时间戳推导；已签政策、合格波幅、成本读数没有公开构造器。

## 公开 API
```rust
#[cfg(any(test, feature = "s_session", feature = "backtest_bin"))] // sha2 可选（Cargo.toml:41）
pub mod cost_stop;
pub struct CostStopPolicy { /* 私有，无 Deserialize、Clone、Default */ }
impl CostStopPolicy {
  pub fn load(profile: CostStopProfile, revision: NonZeroU32) -> Result<Self, PolicyError>;
  pub fn evaluate(&self, level: u32) -> Result<CostStopOutcome, CostStopError>;
  pub fn record(&self) -> PolicyRef;
  pub fn identity(&self) -> &RecordIdentity;
  pub fn cost_terms(&self) -> (&CostTerm, &CostTerm, &HoldingTerm);
  // theta()->&Fraction、fee()->&SignedFee、domain()->&Domain；evidence_gate_ref、supersedes、authorization 同 :489-504
}
pub struct CostStopOutcome { /* 私有 */ }
impl CostStopOutcome {
  pub fn status(&self) -> CostStopStatus;
  pub fn record(&self) -> PolicyRef;
  pub fn consumed(&self) -> &[RecordIdentity]; // 本次验过摘要的原件
  pub fn cost_gap(&self) -> Option<(CostComponent, CostGap)>;
  pub fn amplitude_gap(&self) -> Option<&AmplitudeGap>;
  pub fn windows(&self) -> &[WindowReading]; // 全为推导值
}
impl EvidenceGate { pub(crate) fn qualify( // evidence_gate.rs
  &self, data: WindowSpan, granularity: &str,
  windows: &[WindowSpan], events: &[(i64, i64)]) -> Result<QualifiedWindows, WindowGap>; }
```
`CostStopProfile`（:13-17）、四态与原因枚举、`CostStopError`（:410-446）沿用。其余公开类型只出不进，字段私有、只有 getter：`RecordIdentity`、`Domain`、`SignedFee`、`Fraction`、`SourceRef`（无 `new`）、`OriginalRef{key,sha256}`、`WindowReading`，以及枚举 `CostTerm{Known(SourceBinding),ProxyLowerBound(SourceBinding),Missing}`、`HoldingTerm`、`SourceBinding{Unbound(SourceRef),Bound(OriginalRef)}`、`CostGap`、`AmplitudeGap`、`WindowGap`。evidence_gate.rs 既有公开项与 backtest/mod.rs:55 再导出不动，`parse_record`（:160-179）仍是唯一解析器。

## 数据形状（以下全部私有）
`cost_stop/registry.rs`
```rust
enum Authority { Registered { reference: &'static str }, AwaitingApproval, #[cfg(test)] TestOnly }
struct Row { kind: OriginalKind, key: &'static str, path: &'static str, bytes: &'static [u8], sha256: &'static str, authority: Authority }
static REGISTERED: &[Row]; // 今天三行
struct Store { rows: &'static [Row], origin: Origin } // Registered | TestOnly
```
`Verified{bytes,identity,authority}` 只由 `Store::fetch(kind,key)` 与 `fetch_bound(kind,&OriginalRef)` 产生：行存在、行类别等于所求类别、`sha256(bytes)` 等于行内摘要，后者另核引用摘要。

`cost_stop/policy.rs`：`CostStopPolicy{store,identity,version,terms}`，`terms` 只由 `parse_terms(Verified)` 产生；`load` 即私有 `load_from(Store::registered(), …)`。解析在 `serde_json::Value` 上手写，不用 serde derive，不复用 `parse_header`（policy_records.rs:174-219 要 `fields` 外壳，`signed_value` :222 私有，与平铺形状不合）。统一读取器 `req(obj, 点分路径)` 把键缺失、`null`、字符串 `"AwaitingPolicy"` 归为 `AwaitingPolicy{路径}`，每层必填键同判，可选键显式写后两种值亦同。类型错、θ<1、分母 0、未知键、空或纯空白引用、id、profile_id、version 与登记行不符为 `Invalid`。成本项的 `source_ref` 字符串得 `Unbound`，`source:{key,sha256}` 得 `Bound`，二者只许其一。装载顺序：取行（无行 `RecordMissing`，摘要不符 `Invalid{content_sha256}`）→ 读字段 → `AwaitingApproval` 行报 `AwaitingPolicy{approval_ref}` → `Registered` 行核 `reference == authorizer_ref`。仅当 Store 与行都是 `Registered` 时 `version` 为 `Signed(n)`，否则 `ResearchOverride`。

evidence_gate.rs：`WindowSpan{first_bar,last_bar}`，`QualifiedWindow{span, blocks: Vec<Block>}`，`Block{index: i64, events: Vec<usize>}`。计数不存，由 `blocks` 现算。`qualify` 按序检查、报第一处：粒度只认 `1m`（60 秒栅格），`block_unit` 只认 `CalendarMonthUTC`；窗数 ≥ min_windows；各窗 first<last、在全史内、对齐栅格、互不重叠（共享边界 bar 算重叠）；Σ(last−first)·den ≥ 全史·num；事件 entry ≤ exit、对齐栅格、在全史内、按 (entry,exit) 严格递增；事件归入 first ≤ entry 且 exit ≤ last 的窗，块号为 entry 的 UTC 年×12+月；每窗事件数 ≥ min_events、块数 ≥ min_blocks。

`cost_stop/amplitude.rs`：`QualifiedAmplitude{windows: Vec<(QualifiedWindow, RatePpb)>}` 只由 `resolve(store, policy, level)` 产生，八步：① 按 `evidence_gate_ref` 取 EvidenceGate 行交 `parse_record`，标签须等于行键；② 取全部 AmplitudeRun 行，任一行验不过或解析失败得 `RunUnreadable`；按（domain、level、pairing=ROUNDTRIP、门键）匹配，0 份 `NoRun`，多份 `AmbiguousRuns`；③ run 所引门摘要等于①；④ `fetch_bound` 取预登记窗表，其 domain、门、dataset 与 run 相等；⑤ `method(run.method_id)`，非测试构建一个都不认，得 `MethodNotRuled`；⑥ 门签署日末（`signed_day_end` :312-348）≤ run_started_at 且 frozen_at < run_started_at；⑦ `qualify`；⑧ 逐窗把各块全部样本值交方法求下界。任一步失败即 `InsufficientEvidence(Amplitude)`，记 `AmplitudeGap`。

原件 schema（各带 `schema` 键，未知键即拒，没有事件数、块数、置信度、下界字段）：
- `cost-stop/prereg-windows/1`：domain、dataset{id,sha256,first_bar,last_bar}、evidence_gate{key,sha256}、frozen_at、windows[{first_bar,last_bar}]
- `cost-stop/amplitude-run/1`：domain、level、pairing、evidence_gate、prereg{key,sha256}、dataset、method_id、run_started_at、samples[[entry_ts,exit_ts,amplitude_ppb]]

`cost_stop/reading.rs`：`CostReading{component,basis,domain,level,rate}` 只由 `parse(Verified)` 产生，非测试构建不认任何 schema。cfg(test) 另有 `test-only/cost-reading/0`、方法 `test-only/constant-window/0`（窗内样本全等才返回该常数，不预设待裁统计量）和 `Store::test_only`。

## 原件位置与身份
路径均在 rust/src/theta_v0/policy_records/ 下，全部编进二进制。
- P0、P1 v1 政策：cost-stop/{P0,P1-hl-testnet}.v1.json，键 `#1354/cost-stop-policy/<profile_id>@1`。由 cost-stop.json:4-30、:31-57 原值拆出，各加 `id`、`profile_id`；`reference` 为 #1559 评论 6310844461 的 URL；摘要实施时算出。
- 证据门 v1：evidence-gate.json，字节取 `ACTIVE_EVIDENCE_GATE_JSON`，键 `#1677/evidence-gate/v1`，sha256 `ca0f2ecb9c82df6ef2f93cfe00bc646743f3fd87cfa20414432dcd4c3e27d2f7`。
- 预登记窗表、波幅 run：cost-stop-evidence/，键为仓内相对路径，今天零行，`reference` 填非作者独审出处。
- 成本读数：零行，格式归 TB-08。

「已签」即登记行里整文件摘要与批复引用并列。求值不读盘、不读时钟，给定构建下结果只由 (profile, revision, level) 决定。

## 十一条反例
1. R1-H1：`compare` 只收 `QualifiedAmplitude`，八步全过才有它。
2. R1-H2：没有收文本的公开函数，`CostStopPolicy` 无公开构造与 Deserialize。
3. R1-H3：调用方引用整类删除；记录内引用拒空与纯空白，v1 文本引用是 `Unbound`。
4. R2-H1：schema 没有计数字段。同一 UTC 日三个一小时窗每窗只推得出 1 个月块，得 `TooFewBlocks{got:1,need:12}`，4,000,000 与 3,999,999 两例同为 `InsufficientEvidence(Amplitude)`。
5. R2-H2：摘要覆盖整份文件。θ 改 1/1 而登记摘要不变得 `Invalid{content_sha256}`，在测试 Store 重新登记只得 `ResearchOverride`。
6. R2-HIGH 不存在的路径：调用方不再给引用，登记行路径不存在则 `include_bytes!` 编译失败。
7. R2-HIGH 费率簿充当探针：该字节登记成 AmplitudeRun 也过不了解析，得 `RunUnreadable`。
8. R2-HIGH 费率簿充当三项实测：读数只来自政策内 `Bound` 引用所指的 CostReading 原件，再核 component、basis、domain、level；非测试构建一律 `UnavailableCost(该项)`。
9. R2-MED：`req` 把三种待签写法归为 `AwaitingPolicy{路径}`。
10. R2-LOW：政策项状态须等于读数 basis，Proxy 项遇 Measured 读数及其反向都得 `UnavailableCost`，不升不降（#799）。
11. 零合计：见「#2111 唯一落点」。

## 结果语义与单调性
`decide(theta, costs, amplitude: impl FnOnce() -> AmplitudeFacts)` 是纯函数。成本按滑点、延迟、持有依次解析，第一处不可得即 `NotEvaluable`；`level < start_level` 时持有计 0。合计算术 :543-547、比较 :566-581、（proxy, 全窗过线）四格都不变。level 只用于持有起始级别比较和 run 匹配（#804）。可测性质：① `Enabled` 或 `Disabled` 蕴含成本全部解析、合计非零、八步全过；② 资格对事件单调：追加不使合格变不合格，删除不使不合格变合格；③ 追加过线窗救不回 `Disabled`；④ 实测成本上调不使 `Disabled` 变 `Enabled`；⑤ 含代理项不出 `Enabled`；⑥ 追加其他分层或类别的登记行，结果不变。

## #2111 唯一落点
`mod total` 独占 `CostTotal::split() -> Zero(ZeroTotal) | NonZero(NonZeroTotal)`，`compare` 只收 `NonZeroTotal`，`ZeroTotal` 只交给 `zero_total::settle(zero, amplitude)`。现行函数体：实测零直接 `Err(ZeroMeasuredCostAwaitingRuling2111)`，不调 `amplitude`；代理零调 `amplitude`，不足给 `Amplitude`，否则 `UpperBoundOnly`（:549-564 已过审）。裁定落地只改这个函数体的返回值和调用 `amplitude` 的位置；若裁为记录层拒绝，改 `parse_terms` 并删该分支。

## 从第二轮删除
policy_records.rs:78-88 及其 cost_stop 测试（`COST_STOP_ID` 留）；cost-stop.json；cost_stop.rs 的 `CostStopRecords` 与 serde 报错文本匹配 :19-105、全部 `Deserialize` derive :114-243、`SourceRef::new` 与 `EmptySourceRef` :133-164、`CostEvidence` 至 `AmplitudeEvidence` 六个公开类型 :249-303、`admits` :350-408、`CostSource::resolve` :585-604。

## 测试
单元测试在 cost_stop/tests.rs。除登记表测试外都经测试 Store 的字节走 `evaluate`，不直接构造内部值。
- 保留：`p0_p1_v1_not_evaluable_on_slippage`、`v1_matches_adr_0044`、`threshold_table`（P0 手算盘 5,200,000 上下各 1 ppb、P1 费率、一窗不过线、代理四格、持有起始级别）、`level_is_only_an_input`、`zero_measured_total_is_not_ruled`、`proxy_zero_total_unchanged`
- 签署：`registry_rows_verify_and_parse`（含无 `test-only/` 标识、run 分层不重复）、`tampered_bytes_fail_digest`、`reregistered_copy_is_not_signed`、`awaiting_spellings_are_one_state`
- 证据窗：`same_day_hour_windows_are_insufficient`、`reported_counts_are_rejected`、`blocks_equal_distinct_utc_months`、`qualification_monotone_in_events`、`window_rules`、`header_and_timing_rules`、`zero_or_many_runs_are_insufficient`、`unknown_method_is_not_ruled`
- 来源：`fee_schedule_is_neither_run_nor_reading`、`unbound_v1_refs_never_resolve`、`proxy_term_rejects_measured_reading`（含反向）、`unrelated_rows_change_nothing`

另加 rust/tests/cost_stop_public_surface.rs（`#![cfg(feature = "s_session")]`，并入 ci.yml:600 那步），只用公开面装载与求值。编译负例照 .github/scripts/check-compile-negatives-1394.sh 加 `issue1441_cost_stop_refusal` 一块，放 rust/src/bin/s_session_v3/cost_stop_refusal.rs，Cargo.toml:61 同步。

## 现在交付与等待
本轮交付内核与三行登记。非测试构建今天到不了 `Enabled`、`Disabled`，成本侧止于 `UnavailableCost`，波幅侧止于 `NoRun`。等待：波幅下界方法裁定后在 `method` 加一个分支和独立 oracle；#1441 探针片让 p907 落两份原件并登记；TB-08（#1367）定读数 schema 并出带 `Bound` 引用的新签署版本；#2111 改 `settle`。

## 不在范围
不改 v1 签署值，不往 v1 记录补摘要；不裁 #2111；不加真实阈值或方法参数；不按请求时刻选版本、不核 `valid_through`（TB-07 #1366）；不改 `parse_evidence_gate`；不接会话服务。
