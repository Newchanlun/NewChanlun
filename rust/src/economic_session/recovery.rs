//! #1411：域本地具名恢复。沿用已绑定域库、进程锁及 epoch 事务；不管理端点。
use super::store::{
    advance_recovery, audit, cut, err, immediate, latest, open, recovery_epoch, recovery_writer,
    Config,
};
use crate::session_protocol::{canonical_json, positive, required, strict_json};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::{io::Read, path::Path};

const SCHEMA: &str = "economic-recovery/1";
const REQUEST_LIMIT: u64 = 4096;

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Action {
    Recover,
    Query,
    VerifyCurrent,
}

pub(super) struct Request {
    document: Value,
    key: String,
    from: i64,
}

impl Request {
    pub(super) fn load(path: &Path, config: &Config) -> Result<Self, String> {
        let mut raw = Vec::new();
        std::fs::File::open(path)
            .map_err(err)?
            .take(REQUEST_LIMIT + 1)
            .read_to_end(&mut raw)
            .map_err(err)?;
        if raw.len() as u64 > REQUEST_LIMIT {
            return Err("InvalidDomain：恢复请求超过上限".into());
        }
        let document = strict_json(&raw)?;
        if document.as_object().map(|object| object.len()) != Some(8)
            || document["schema_revision"] != SCHEMA
        {
            return Err("InvalidDomain：恢复请求格式未知".into());
        }
        let id = required(&document, "recovery_id")?;
        if id.len() > 96
            || !id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
        {
            return Err("InvalidDomain：恢复身份必须为 1..96 字节的 ASCII 标识".into());
        }
        let key = format!("{SCHEMA}:{id}");
        let from = positive(required(&document, "from_epoch")?, "from_epoch")?;
        for (field, expected) in [
            ("domain_id", &config.domain),
            ("session_id", &config.session),
            ("session_generation", &config.generation),
            ("manifest_hash", &config.manifest_hash),
        ] {
            if required(&document, field)? != expected {
                return Err(format!(
                    "IdentityConflict：恢复请求的 {field} 未绑定当前域配置"
                ));
            }
        }
        if !document["cut"].is_object() {
            return Err("InvalidDomain：恢复请求缺具名 cut".into());
        }
        Ok(Self {
            document,
            key,
            from,
        })
    }

    fn receipt(&self, epoch: i64, ns: &str) -> Value {
        json!({"kind":"NamedRecoveryReceipt", "request":self.document,
            "writer_epoch":epoch.to_string(), "recover_ns":ns})
    }

    fn find(&self, c: &Connection, config: &Config) -> Result<Option<(i64, Value)>, String> {
        let raw: Option<String> = c
            .query_row("SELECT v FROM meta WHERE k=?", [&self.key], |r| r.get(0))
            .optional()
            .map_err(err)?;
        let Some(raw) = raw else { return Ok(None) };
        let recorded = strict_json(raw.as_bytes())?;
        if recorded["request"] != self.document {
            return Err("IdentityConflict：恢复身份已绑定不同请求".into());
        }
        let next = self.from.checked_add(1).ok_or("InvalidDomain：epoch溢出")?;
        let ns: String = c
            .query_row(
                "SELECT at_ns FROM epochs WHERE epoch=? AND phase='recover'",
                [next],
                |r| r.get(0),
            )
            .map_err(err)?;
        let key = &self.document["cut"];
        let seq = crate::session_protocol::nonnegative(required(key, "commit_seq")?, "commit_seq")?;
        let root: String = c
            .query_row("SELECT root FROM commits WHERE seq=?", [seq], |r| r.get(0))
            .map_err(err)?;
        if *key != cut(config, seq, &root) || raw != canonical_json(&self.receipt(next, &ns)) {
            return Err("StorageUnavailable：原恢复收据与持久 epoch/cut 不相符".into());
        }
        Ok(Some((next, recorded)))
    }
}

/// 调用方持有与 init/serve/recover 相同的域锁；核对和换代在同一事务。
pub(super) fn run(config: &Config, request: &Request, action: Action) -> Result<Value, String> {
    if !config.db.is_file() {
        return Err("StorageUnavailable：具名恢复要求已存在的域库".into());
    }
    let mut c = if action == Action::Recover {
        recovery_writer(config)?.0
    } else {
        open(&config.db, true)?.0
    };
    let tx = if action == Action::Recover {
        immediate(&mut c)?
    } else {
        c.transaction().map_err(err)?
    };
    audit(&tx, config)?;
    let epoch = recovery_epoch(&tx)?;
    if let Some((next, original)) = request.find(&tx, config)? {
        return if action == Action::VerifyCurrent && next != epoch {
            Err("StaleWriter：原恢复收据不能授权当前写者".into())
        } else {
            Ok(original)
        };
    }
    if action != Action::Recover {
        return Err("MissingDependency：具名恢复收据不存在".into());
    }
    if epoch != request.from {
        return Err("StaleWriter：具名恢复前代与当前持久代不符".into());
    }
    let (seq, h, _, _) = latest(&tx)?;
    if request.document["cut"] != cut(config, seq, &h) {
        return Err("IdentityConflict：恢复请求必须绑定当前持久 cut".into());
    }
    let (next, ns, _) = advance_recovery(&tx, config, epoch)?;
    let original = request.receipt(next, &ns);
    // 借用已存在的 meta 名字空间，不改变旧库 DDL，不把恢复收据混作业务消息。
    tx.execute(
        "INSERT INTO meta(k,v)VALUES(?,?)",
        params![request.key, canonical_json(&original)],
    )
    .map_err(err)?;
    tx.commit().map_err(err)?;
    Ok(original)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::economic_session::{
        store::{init, recover},
        tb03c_book_tests::Space,
    };

    #[test]
    fn original_receipt_survives_lost_response_without_authorizing_a_later_epoch() {
        let space = Space::new("named-recovery");
        let db = space.0.join("e.db");
        let manifest = space.0.join("manifest.json");
        std::fs::write(&manifest, canonical_json(&json!({
            "schema_revision":"economic-manifest/1","session_id":"named-recovery","session_generation":"1",
            "book_revision":"tb03c-book/1",
            "e":{"db":db,"socket":space.0.join("e.sock")},
            "chongs":[{"chong_id":"one","symbol":"TEST","operation_level":"1","fixed_q":"10",
                "db":space.0.join("b.db"),"socket":space.0.join("b.sock")}],
            "authorized_sources":[{"source_namespace":"fixture","source_epoch":"1","producer_id":"fixture","producer_epoch":"1","operations":["ReadView"]}],
            "resources":{"max_frame_bytes":"1048576","read_timeout_ms":"1000","write_timeout_ms":"1000",
                "response_timeout_ms":"3000","queue_capacity":"2","max_connections":"2"},
            "clock":{"kind":"TestOnly","plan":{"init_ns":"1","recover_ns":["10","20"],"messages":{}}}
        }))).unwrap();
        let config = Config::load(&manifest, &db, None).unwrap();
        let init = init(&config).unwrap();
        let path = space.0.join("request.json");
        let mut request = json!({
            "schema_revision":SCHEMA,"recovery_id":"one","from_epoch":"1","domain_id":"E",
            "session_id":config.session,"session_generation":config.generation,"manifest_hash":config.manifest_hash,
            "cut":init["cut"]
        });
        let write_request = |value: &Value| std::fs::write(&path, canonical_json(value)).unwrap();
        let run_request = |action| run(&config, &Request::load(&path, &config)?, action);
        write_request(&request);
        assert!(run_request(Action::Query)
            .unwrap_err()
            .contains("MissingDependency"));
        // 不消费初次返回值，后续各调用重新打开库。
        run_request(Action::Recover).unwrap();
        let original = run_request(Action::Query).unwrap();
        assert_eq!(original["writer_epoch"], "2");
        assert_eq!(run_request(Action::Recover).unwrap(), original);
        assert_eq!(run_request(Action::VerifyCurrent).unwrap(), original);

        request["from_epoch"] = json!("2");
        write_request(&request);
        assert!(run_request(Action::Recover)
            .unwrap_err()
            .contains("IdentityConflict"));
        request["from_epoch"] = json!("1");
        write_request(&request);
        assert_eq!(recover(&config).unwrap()["writer_epoch"], "3");
        assert_eq!(run_request(Action::Query).unwrap(), original);
        assert!(run_request(Action::VerifyCurrent)
            .unwrap_err()
            .contains("StaleWriter"));
    }
}
