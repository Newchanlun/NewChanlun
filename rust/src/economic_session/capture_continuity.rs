//! #1375：在 E 单写者接收输入之前留下持久的「此来源可能有缺口」，而不是等写满后再写。
//! 具名的封闭 TestOnly 源从头到 EOF 枚举原件；原收据的读取/重送不依赖源在线。
use super::book::fact_key;
use super::store::{check_epoch, err, immediate, set_meta, Config};
use crate::session_protocol::{nonnegative, required, sha256_hex, strict_json};
use rusqlite::{Connection, OptionalExtension};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

const LEASE: &str = "external_intake_lease/1";
const TAPE: &str = "test_only_capture_tape";
const FORMAT: &str = "test-only-economic-source/1";
const WHO: [&str; 4] = [
    "source_namespace",
    "source_epoch",
    "producer_id",
    "producer_epoch",
];

fn authorized_manifest(manifest: &Value, op: &str) -> bool {
    manifest["authorized_sources"]
        .as_array()
        .is_some_and(|rows| {
            rows.iter().any(|p| {
                p["operations"]
                    .as_array()
                    .is_some_and(|ops| ops.iter().any(|o| o == op))
            })
        })
}

fn relevant(c: &Config) -> bool {
    c.domain == "E"
        && super::finance::enabled(c)
        && authorized_manifest(&c.manifest, "CaptureExternal")
        && (authorized_manifest(&c.manifest, "Reserve")
            || authorized_manifest(&c.manifest, "ReleaseExact"))
}

/// 纯结构校验，不读磁盘原件文件：允许已释放命令后来源离线时仍能打开库、恢复与查询历史收据。
pub(super) fn validate_config(manifest: &Value) -> Result<(), String> {
    let Some(binding) = manifest.get(TAPE) else {
        return Ok(());
    };
    super::voice::exact(binding, &["path", "sha256"])?;
    let path = required(binding, "path")?;
    let sha = required(binding, "sha256")?;
    if sha.len() != 64 || !sha.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f')) {
        return Err("InvalidDomain：TestOnly 来源摘要须为 64 位小写十六进制 SHA-256".into());
    }
    if !Path::new(path).is_absolute()
        || manifest["clock"]["kind"] != "TestOnly"
        || manifest.get("history_simulation_source").is_some()
        || !super::finance::exact_release_selected(manifest)
        || !authorized_manifest(manifest, "CaptureExternal")
        || !(authorized_manifest(manifest, "Reserve")
            || authorized_manifest(manifest, "ReleaseExact"))
    {
        return Err("InvalidDomain：封闭原件源仅属于具名 TestOnly 精确交付域".into());
    }
    Ok(())
}

pub(super) fn initialize(db: &Connection, c: &Config) -> Result<(), String> {
    validate_config(&c.manifest)?;
    if relevant(c) {
        if c.manifest.get(TAPE).is_some() {
            Tape::load(c)?;
        }
        set_meta(db, LEASE, "not-yet-serving")?;
    }
    Ok(())
}

#[derive(Clone, Default)]
pub(crate) struct Intake(Option<Arc<AtomicBool>>);

/// 只有亲自消费 init 的一次性交接且没有中断的 actor 能证明本次本地接纳连续。
/// recover 只换 epoch，不补发交接。即使进程死在 SQLite 返回错误之前，下一任也看得到缺口。
pub(super) fn start(db: &mut Connection, c: &Config, epoch: i64) -> Result<Intake, String> {
    if !relevant(c) {
        return Ok(Intake::default());
    }
    let tx = immediate(db)?;
    check_epoch(&tx, epoch)?;
    let state: Option<String> = tx
        .query_row("SELECT v FROM meta WHERE k=?", [LEASE], |r| r.get(0))
        .optional()
        .map_err(err)?;
    let fresh = match state.as_deref() {
        Some("not-yet-serving") => {
            set_meta(&tx, LEASE, "serving")?;
            epoch == 1
        }
        // 旧库存量没有初次交接，不能把不在场误作连续；不改旧 cut、消息或收据。
        Some("serving") | None => false,
        _ => return Err("StorageUnavailable：外部接纳交接记录损坏".into()),
    };
    tx.commit().map_err(err)?;
    Ok(Intake(Some(Arc::new(AtomicBool::new(!fresh)))))
}

impl Intake {
    pub(super) fn failed(&self, reason: &str) {
        // 已授权且原件可解码。明确的身份/输入拒绝不算日志故障；存储、超时、来源不可核等
        // 不确定结果则先关闸，含 COMMIT 返回未知。已提交事实仍由原收据认回。
        if !reason.starts_with("IdentityConflict")
            && !reason.starts_with("InvalidDomain")
            && !reason.starts_with("SchemaUnsupported")
            && !reason.starts_with("StaleWriter")
        {
            if let Some(gap) = &self.0 {
                gap.store(true, Ordering::Relaxed);
            }
        }
    }

    pub(super) fn check_new_risk(&self, c: &Config, image: &Value, at: &str) -> Result<(), String> {
        let gap = self.0.as_ref().is_some_and(|g| g.load(Ordering::Relaxed));
        if c.manifest.get(TAPE).is_none() {
            return if gap {
                Err(
                    "MissingDependency：E 外部接纳存在未核来源缺口，须由绑定来源证明完整结束界"
                        .into(),
                )
            } else {
                Ok(())
            };
        }
        let tape = Tape::load(c)?;
        let now = nonnegative(at, "commit_ns")?;
        let facts = image["recorded"]
            .as_array()
            .ok_or("StorageUnavailable：缺 Recorded")?;
        let pending = image["pending"]
            .as_array()
            .ok_or("StorageUnavailable：缺 Pending")?;
        let retained: Vec<Value> = image["finance"]["responsibilities"]
            .as_array()
            .ok_or("MissingDependency：缺 E 已持久责任集合")?
            .iter()
            .filter_map(|r| r["source"]["covered_facts"].as_array())
            .flatten()
            .cloned()
            .collect();
        for (key, item) in &tape.items {
            // 正常时间只读至本次提交；不确定窗口不猜故障时点，保守核完整有限源。
            if !gap && item.emitted_ns > now {
                continue;
            }
            let r = facts
                .iter()
                .find(|r| r["fact_key"] == key.as_str())
                .ok_or_else(|| format!("MissingDependency：TestOnly 来源未补录 {key}"))?;
            item.verify(r, &tape.source)?;
            if let Some(p) = pending.iter().find(|p| p["fact_key"] == key.as_str()) {
                // 先复用既有完整责任界判据，保证未覆盖项仍以「责任界」明确拒绝。
                super::finance::covered_pending(image, &retained, p)?;
                if gap {
                    // 缺口恢复期间不得仅凭补录放行：仍为 Pending 的事实须先经正式核清清除。
                    return Err(format!(
                        "MissingDependency：缺口补录事实 {key} 仍为 Pending，须先经正式核清"
                    ));
                }
            }
        }
        if gap {
            for p in pending {
                super::finance::covered_pending(image, &retained, p)?;
                let key = required(p, "fact_key")?;
                return Err(format!(
                    "MissingDependency：缺口恢复前事实 {key} 仍为 Pending，须先经正式核清"
                ));
            }
        }
        Ok(())
    }
}

struct Original {
    raw: Arc<str>,
    pointer: String,
    token: String,
    emitted_ns: i64,
}
impl Original {
    fn verify(&self, r: &Value, source: &Value) -> Result<(), String> {
        if r["raw_utf8"].as_str() != Some(self.raw.as_ref())
            || r["json_pointer"] != self.pointer
            || r["token"] != self.token
            || r["source_producer"]["producer_id"] != source["producer_id"]
            || r["source_producer"]["producer_epoch"] != source["producer_epoch"]
            || r["origin_message"]["source_namespace"] != source["source_namespace"]
            || r["origin_message"]["source_epoch"] != source["source_epoch"]
        {
            return Err(
                "IdentityConflict：原件、指针、token 或来源身份不等于冻结 TestOnly 来源".into(),
            );
        }
        Ok(())
    }
}

/// 这里的 EOF 是来源本身的定义域：新 Capture 也只接受该文件的成员。不能把任意
/// adapter 的一次导出、单个批的 QueryBatch 或请求人的「全部送完」传成这类来源。
struct Tape {
    source: Value,
    items: BTreeMap<String, Original>,
}
impl Tape {
    fn load(c: &Config) -> Result<Self, String> {
        validate_config(&c.manifest)?;
        let binding = &c.manifest[TAPE];
        let path = required(binding, "path")?;
        let raw = super::finance::original_raw(path, "只读 TestOnly 原件源")?;
        if sha256_hex(raw.as_bytes()) != required(binding, "sha256")? {
            return Err("MissingDependency：冻结的 TestOnly 来源内容不可核".into());
        }
        let tape = strict_json(raw.as_bytes())?;
        super::voice::exact(
            &tape,
            &[
                "format",
                "session_id",
                "session_generation",
                "source",
                "documents",
            ],
        )?;
        if tape["format"] != FORMAT
            || tape["session_id"] != c.session
            || tape["session_generation"] != c.generation
        {
            return Err("IdentityConflict：TestOnly 来源版本/会话/化身不符".into());
        }
        let source = &tape["source"];
        super::voice::exact(source, &WHO)?;
        let mut captures = c.manifest["authorized_sources"]
            .as_array()
            .ok_or("InvalidDomain：缺来源")?
            .iter()
            .filter(|p| {
                p["operations"]
                    .as_array()
                    .is_some_and(|ops| ops.iter().any(|o| o == "CaptureExternal"))
            })
            .peekable();
        if captures.peek().is_none() || !captures.all(|p| WHO.iter().all(|k| p[k] == source[k])) {
            return Err("InvalidDomain：TestOnly 封闭源须覆盖全部获准外部接纳主体".into());
        }
        let rules = c.book_rules()?;
        let mut items = BTreeMap::new();
        let mut tokens = BTreeSet::new();
        let mut previous = 0;
        for doc in tape["documents"]
            .as_array()
            .ok_or("InvalidDomain：TestOnly 来源缺原件序列")?
        {
            super::voice::exact(doc, &["emitted_ns", "raw_utf8", "tokens"])?;
            let emitted_ns = nonnegative(required(doc, "emitted_ns")?, "emitted_ns")?;
            if emitted_ns < previous {
                return Err("InvalidDomain：TestOnly 来源发出顺序倒退".into());
            }
            previous = emitted_ns;
            let raw: Arc<str> = required(doc, "raw_utf8")?.into();
            let envelope = strict_json(raw.as_bytes())?;
            if envelope["format"]
                != "neutral TestOnly economic raw originals; not production transport wire"
            {
                return Err("SchemaUnsupported：封闭源只接受中性 TestOnly 经济原件".into());
            }
            let events = envelope["events"]
                .as_array()
                .filter(|es| !es.is_empty())
                .ok_or("InvalidDomain：原件无事件")?;
            let ids = doc["tokens"]
                .as_array()
                .filter(|ts| ts.len() == events.len())
                .ok_or("InvalidDomain：原件须逐事件绑定 token")?;
            for (index, (event, id)) in events.iter().zip(ids).enumerate() {
                let token = id
                    .as_str()
                    .filter(|t| !t.is_empty())
                    .ok_or("InvalidDomain：token 为空")?
                    .to_owned();
                let pointer = format!("/events/{index}");
                super::book::decode(&raw, &pointer, rules)?;
                if ["source_namespace", "source_epoch"]
                    .iter()
                    .any(|k| event["source"][k] != source[k])
                    || !tokens.insert(token.clone())
                {
                    return Err("IdentityConflict：来源错绑或重复 token".into());
                }
                let item = Original {
                    raw: raw.clone(),
                    pointer,
                    token,
                    emitted_ns,
                };
                if items.insert(fact_key(event)?, item).is_some() {
                    return Err("IdentityConflict：TestOnly 原件身份重复".into());
                }
            }
        }
        Ok(Tape {
            source: source.clone(),
            items,
        })
    }
}

pub(super) fn verify_member(c: &Config, r: &Value) -> Result<(), String> {
    if c.manifest.get(TAPE).is_some() {
        let tape = Tape::load(c)?;
        let item = tape
            .items
            .get(required(r, "fact_key")?)
            .ok_or("IdentityConflict：事实不在冻结 TestOnly 来源")?;
        item.verify(r, &tape.source)?;
        if nonnegative(required(r, "received_ns")?, "received_ns")? < item.emitted_ns {
            return Err("InvalidDomain：TestOnly 原件尚未发出".into());
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::economic_session::book::hash;
    use crate::session_protocol::canonical_json;
    use serde_json::json;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering as SeqOrdering};

    struct TempDir(PathBuf);
    impl TempDir {
        fn new(label: &str) -> Self {
            static COUNTER: AtomicU64 = AtomicU64::new(0);
            let n = COUNTER.fetch_add(1, SeqOrdering::Relaxed);
            let dir = std::env::temp_dir().join(format!(
                "nc-capture-continuity-{label}-{}-{n}",
                std::process::id()
            ));
            let _ = std::fs::remove_dir_all(&dir);
            std::fs::create_dir_all(&dir).unwrap();
            Self(dir)
        }
    }
    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn test_source() -> Value {
        json!({
            "source_namespace": "test",
            "source_epoch": "one",
            "producer_id": "unit",
            "producer_epoch": "1"
        })
    }

    fn make_raw_doc(ext_id: &str, cursor: &str) -> String {
        canonical_json(&json!({
            "format": "neutral TestOnly economic raw originals; not production transport wire",
            "units": {
                "numeric_encoding": "exact_decimal_integer_text",
                "quantity": {"unit": "shares", "quantum": "1"},
                "money": {"currency": "TEST-CASH", "unit": "cents", "quantum": "1"}
            },
            "events": [{
                "event": "observed_existing_book",
                "allocation_id": format!("alloc-{ext_id}"),
                "family_id": "family-alpha",
                "book_identity": {
                    "chong_id": "alpha",
                    "symbol": "alpha",
                    "op_level": "1",
                    "fixed_q": "1",
                    "side": "long"
                },
                "stable_point": {"profile": "TestOnly", "seq": "1", "source_ref": "sp"},
                "source": {
                    "source_namespace": "test",
                    "source_epoch": "one",
                    "external_fact_id": ext_id,
                    "source_cursor": cursor,
                    "received_time": "2026-01-01T00:00:00Z",
                    "source_event_time": null,
                    "claimed_origin": "test-only-unit"
                },
                "observed_existing_book": {
                    "units": "1",
                    "Pi": "0",
                    "A": "0",
                    "W": "0",
                    "witness_refs": {"units": "u", "Pi": "p", "A": "a", "W": "w"}
                },
                "known_cost_components": []
            }],
            "evidence_index": {
                "fragments": {
                    "sp": [{"json_pointer": "/events/0/stable_point"}],
                    "u": [{"json_pointer": "/events/0/observed_existing_book/units"}],
                    "p": [{"json_pointer": "/events/0/observed_existing_book/Pi"}],
                    "a": [{"json_pointer": "/events/0/observed_existing_book/A"}],
                    "w": [{"json_pointer": "/events/0/observed_existing_book/W"}]
                }
            }
        }))
    }

    fn make_record(raw_utf8: &str, token: &str, emitted_ns: &str) -> Value {
        let doc = strict_json(raw_utf8.as_bytes()).unwrap();
        let event = doc["events"][0].clone();
        let raw_hash = sha256_hex(raw_utf8.as_bytes());
        let fact_hash = hash(&json!({
            "raw_sha256": raw_hash,
            "json_pointer": "/events/0",
            "event": event,
            "units": doc["units"]
        }));
        json!({
            "fact_key": fact_key(&event).unwrap(),
            "fact_hash": fact_hash,
            "raw_sha256": raw_hash,
            "raw_utf8": raw_utf8,
            "json_pointer": "/events/0",
            "event": event,
            "token": token,
            "target_domain": "B:alpha",
            "received_ns": emitted_ns,
            "source_producer": {"producer_id": "unit", "producer_epoch": "1"},
            "origin_message": {
                "source_namespace": "test",
                "source_epoch": "one",
                "message_id": format!("msg-{token}"),
                "payload_hash": "0".repeat(64)
            }
        })
    }

    fn make_config(tape_binding: Option<Value>) -> Config {
        let mut manifest = json!({
            "schema_revision": "economic-manifest/1",
            "session_id": "sess-1",
            "session_generation": "1",
            "book_revision": "tb03c-book/1",
            "clock": {"kind": "TestOnly", "plan": {"init_ns": "1", "recover_ns": ["1000"], "messages": {}}},
            "finance": {"schema_revision": "tb03b-finance/5"},
            "authorized_sources": [{
                "source_namespace": "test",
                "source_epoch": "one",
                "producer_id": "unit",
                "producer_epoch": "1",
                "operations": ["CaptureExternal", "ResolveEvidence", "Reserve", "ReleaseExact"]
            }]
        });
        if let Some(binding) = tape_binding {
            manifest[TAPE] = binding;
        }
        Config {
            intake: Intake::default(),
            manifest_hash: hash(&manifest),
            manifest,
            db: PathBuf::from("/tmp/unused.db"),
            domain: "E".into(),
            session: "sess-1".into(),
            generation: "1".into(),
            producer: "E:sess-1".into(),
            socket: PathBuf::from("/tmp/unused.sock"),
        }
    }

    fn write_tape(dir: &Path, documents: Value) -> Value {
        let tape = json!({
            "format": FORMAT,
            "session_id": "sess-1",
            "session_generation": "1",
            "source": test_source(),
            "documents": documents
        });
        let raw = canonical_json(&tape);
        let path = dir.join("tape.json");
        std::fs::write(&path, raw.as_bytes()).unwrap();
        json!({"path": path.to_str().unwrap(), "sha256": sha256_hex(raw.as_bytes())})
    }

    fn setup_meta_db() -> Connection {
        let c = Connection::open_in_memory().unwrap();
        c.execute_batch("CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);")
            .unwrap();
        set_meta(&c, "writer_epoch", "1").unwrap();
        c
    }

    #[test]
    fn pre_armed_lease_marks_restart_and_same_epoch_reopen_as_gap() {
        let cfg = make_config(None);
        let mut db = setup_meta_db();
        initialize(&db, &cfg).unwrap();

        let first = start(&mut db, &cfg, 1).unwrap();
        assert!(!first.0.as_ref().unwrap().load(Ordering::Relaxed));

        // 即使未换代即重开 serve，预武装租约已是 serving，仍按缺口封闸。
        let reopen_same_epoch = start(&mut db, &cfg, 1).unwrap();
        assert!(reopen_same_epoch
            .0
            .as_ref()
            .unwrap()
            .load(Ordering::Relaxed));

        // 换代至 epoch 2 后同样按缺口封闸。
        set_meta(&db, "writer_epoch", "2").unwrap();
        let next_epoch = start(&mut db, &cfg, 2).unwrap();
        assert!(next_epoch.0.as_ref().unwrap().load(Ordering::Relaxed));

        // 即使手工篡改 meta 回 not-yet-serving，epoch != 1 仍不放行。
        set_meta(&db, LEASE, "not-yet-serving").unwrap();
        let forged = start(&mut db, &cfg, 2).unwrap();
        assert!(forged.0.as_ref().unwrap().load(Ordering::Relaxed));

        // 无租约记录的旧库保守视为缺口。
        db.execute("DELETE FROM meta WHERE k=?", [LEASE]).unwrap();
        let legacy = start(&mut db, &cfg, 2).unwrap();
        assert!(legacy.0.as_ref().unwrap().load(Ordering::Relaxed));

        // 损坏租约值明确以 StorageUnavailable 拒绝。
        set_meta(&db, LEASE, "corrupted").unwrap();
        let err = start(&mut db, &cfg, 2).err().unwrap();
        assert!(err.starts_with("StorageUnavailable"), "{err}");
    }

    #[test]
    fn failed_classifies_input_rejections_vs_fault_uncertainties() {
        let intake = Intake(Some(Arc::new(AtomicBool::new(false))));
        for benign in [
            "IdentityConflict：重复",
            "InvalidDomain：非法",
            "SchemaUnsupported：版本",
            "StaleWriter：陈旧",
        ] {
            intake.failed(benign);
            assert!(
                !intake.0.as_ref().unwrap().load(Ordering::Relaxed),
                "{benign} should not trip gap"
            );
        }
        for fault in [
            "StorageUnavailable：database or disk is full",
            "MissingDependency：来源不可读",
            "DeliveryUnknown：提交结果未知",
            "Incomplete：超时",
        ] {
            let guard = Intake(Some(Arc::new(AtomicBool::new(false))));
            guard.failed(fault);
            assert!(
                guard.0.as_ref().unwrap().load(Ordering::Relaxed),
                "{fault} must trip gap"
            );
        }
    }

    #[test]
    fn tape_gap_blocks_missing_same_cursor_and_unresolved_pending_until_cleared() {
        let dir = TempDir::new("gap-clear");
        let raw_fill = make_raw_doc("fill-1", "2");
        let raw_fee = make_raw_doc("fee-1", "2");
        let binding = write_tape(
            &dir.0,
            json!([
                {"emitted_ns": "179", "raw_utf8": raw_fill, "tokens": ["tok-fill"]},
                {"emitted_ns": "179", "raw_utf8": raw_fee, "tokens": ["tok-fee"]}
            ]),
        );
        let cfg = make_config(Some(binding));
        let rec_fill = make_record(&raw_fill, "tok-fill", "179");
        let rec_fee = make_record(&raw_fee, "tok-fee", "179");
        let covered_entry = |r: &Value| {
            json!({
                "fact_key": r["fact_key"],
                "fact_hash": r["fact_hash"],
                "token": r["token"]
            })
        };
        let pending_entry = |r: &Value| {
            json!({
                "fact_key": r["fact_key"],
                "token": r["token"],
                "target_domain": "B:alpha",
                "status": "Pending",
                "reason": {"kind": "Unresolved"},
                "scope": "B:alpha"
            })
        };
        let base_image = |recorded: Value, pending: Value, covered: Value| {
            json!({
                "recorded": recorded,
                "pending": pending,
                "finance": {
                    "responsibilities": [{
                        "responsibility_id": "existing20",
                        "amount": "20",
                        "source": {"covered_facts": covered}
                    }]
                }
            })
        };

        // 故障前（gap=false），早于 emitted_ns 的新风险不要求尚未发出的未来原件。
        let healthy = Intake(Some(Arc::new(AtomicBool::new(false))));
        healthy
            .check_new_risk(&cfg, &base_image(json!([]), json!([]), json!([])), "92")
            .unwrap();

        // 故障后（gap=true），即使时间早或已补同 cursor 第一笔，漏同 cursor 第二笔仍拒。
        let gapped = Intake(Some(Arc::new(AtomicBool::new(true))));
        let err_missing = gapped
            .check_new_risk(
                &cfg,
                &base_image(
                    json!([rec_fill.clone()]),
                    json!([pending_entry(&rec_fill)]),
                    json!([covered_entry(&rec_fill), covered_entry(&rec_fee)]),
                ),
                "1202",
            )
            .unwrap_err();
        assert!(err_missing.contains("未补录"), "{err_missing}");

        // 两笔全补但未覆盖责任界，仍以「责任界」拒绝。
        let err_uncovered = gapped
            .check_new_risk(
                &cfg,
                &base_image(
                    json!([rec_fill.clone(), rec_fee.clone()]),
                    json!([pending_entry(&rec_fill), pending_entry(&rec_fee)]),
                    json!([covered_entry(&rec_fill)]),
                ),
                "1202",
            )
            .unwrap_err();
        assert!(err_uncovered.contains("责任界"), "{err_uncovered}");

        // 两笔全补且均在责任界内，但仍为 Pending（尚未 ResolveEvidence），缺口恢复仍拒。
        let err_still_pending = gapped
            .check_new_risk(
                &cfg,
                &base_image(
                    json!([rec_fill.clone(), rec_fee.clone()]),
                    json!([pending_entry(&rec_fill), pending_entry(&rec_fee)]),
                    json!([covered_entry(&rec_fill), covered_entry(&rec_fee)]),
                ),
                "1202",
            )
            .unwrap_err();
        assert!(err_still_pending.contains("Pending"), "{err_still_pending}");

        // 两笔全补且均已核清（Pending 已清除），允许真实新风险。
        gapped
            .check_new_risk(
                &cfg,
                &base_image(
                    json!([rec_fill.clone(), rec_fee.clone()]),
                    json!([]),
                    json!([covered_entry(&rec_fill), covered_entry(&rec_fee)]),
                ),
                "1202",
            )
            .unwrap();

        // 原件来源身份被篡改时，check_new_risk 拒绝。
        let mut bad_producer = rec_fee.clone();
        bad_producer["source_producer"]["producer_epoch"] = json!("999");
        let err_producer = gapped
            .check_new_risk(
                &cfg,
                &base_image(json!([rec_fill, bad_producer]), json!([]), json!([])),
                "1202",
            )
            .unwrap_err();
        assert!(err_producer.contains("IdentityConflict"), "{err_producer}");
    }

    #[test]
    fn validate_config_and_empty_tape_boundaries() {
        let dir = TempDir::new("config-empty");
        let empty_binding = write_tape(&dir.0, json!([]));
        let cfg = make_config(Some(empty_binding.clone()));
        validate_config(&cfg.manifest).unwrap();

        // 空区间权威源可以证明无缺失原件。
        let gapped = Intake(Some(Arc::new(AtomicBool::new(true))));
        gapped
            .check_new_risk(
                &cfg,
                &json!({"recorded": [], "pending": [], "finance": {"responsibilities": []}}),
                "1202",
            )
            .unwrap();

        // 相对路径、非 TestOnly、含 history_simulation_source 或坏 sha256 均在 Config 校验阶段拒绝。
        let mut rel = cfg.manifest.clone();
        rel[TAPE]["path"] = json!("relative/tape.json");
        assert!(validate_config(&rel).unwrap_err().contains("InvalidDomain"));

        let mut bad_sha = cfg.manifest.clone();
        bad_sha[TAPE]["sha256"] = json!("not-a-sha");
        assert!(validate_config(&bad_sha)
            .unwrap_err()
            .contains("InvalidDomain"));

        let mut sys = cfg.manifest.clone();
        sys["clock"]["kind"] = json!("System");
        assert!(validate_config(&sys).unwrap_err().contains("InvalidDomain"));

        let mut sim = cfg.manifest.clone();
        sim["history_simulation_source"] = json!({});
        assert!(validate_config(&sim).unwrap_err().contains("InvalidDomain"));
    }
}
