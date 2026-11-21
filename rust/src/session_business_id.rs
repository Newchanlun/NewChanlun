//! 新版 E/B 与 X 冻结清单的非定位业务词法；不用于旧清单或部署映射。

fn file_name(s: &str) -> bool {
    let suffix = s.rsplit_once('.').map(|(_, ext)| ext);
    suffix.is_some_and(|ext| {
        [
            "db", "sqlite", "sqlite3", "sock", "socket", "lock", "wal", "shm", "journal", "json",
            "jsonl", "ndjson", "yaml", "yml", "toml", "csv", "tsv", "parquet", "arrow", "feather",
            "txt", "log", "bin", "exe", "so", "dylib", "dll", "zip", "tar", "gz", "zst",
        ]
        .iter()
        .any(|known| ext.eq_ignore_ascii_case(known))
    }) || ["-wal", "-shm", "-journal"]
        .iter()
        .any(|suffix| s.to_ascii_lowercase().ends_with(suffix))
}

/// 逻辑名允许点分命名；空段/目录点段、位置分隔符及本机数据文件名不可用。
pub(super) fn is_name(s: &str) -> bool {
    !file_name(s)
        && s.split('.').all(|part| {
            part.starts_with(char::is_alphanumeric)
                && part
                    .chars()
                    .all(|c| c.is_alphanumeric() || matches!(c, '-' | '_'))
        })
}

fn checked(ok: bool, field: &str, meaning: &str) -> Result<(), String> {
    if ok {
        Ok(())
    } else {
        Err(format!(
            "InvalidDomain：{field} 须为{meaning}，不得使用部署位置"
        ))
    }
}

pub(super) fn name(s: &str, field: &str) -> Result<(), String> {
    checked(is_name(s), field, "逻辑业务标识")
}

/// 域生产者可用 `E:<id>`、`B:<id>`、`S:<id>`、`X:<id>`；
/// B 的回包另带重和会话两段：`B:<chong_id>:<session_id>`。
pub(super) fn domain_name(s: &str, field: &str) -> Result<(), String> {
    checked(
        match s.split_once(':') {
            None => is_name(s),
            Some(("B", id)) => {
                is_name(id)
                    || id
                        .split_once(':')
                        .is_some_and(|(chong, session)| is_name(chong) && is_name(session))
            }
            Some(("E" | "S" | "X", id)) => is_name(id),
            _ => false,
        },
        field,
        "逻辑域业务标识",
    )
}

pub(super) fn namespace(s: &str, field: &str) -> Result<(), String> {
    checked(
        is_name(s) || s.strip_suffix("/replies").is_some_and(is_name) || s == "s-observe/browser",
        field,
        "逻辑来源命名空间",
    )
}

/// 具名合同或原件允许 `name/1`、`name/v1`，斜杠不是目录层级。
pub(super) fn reference(s: &str, field: &str) -> Result<(), String> {
    let versioned = s.split_once('/').is_some_and(|(id, rev)| {
        let rev = rev.strip_prefix('v').unwrap_or(rev);
        is_name(id) && !rev.is_empty() && rev.bytes().all(|b| b.is_ascii_digit())
    });
    if versioned {
        return Ok(());
    }
    domain_name(s, field)
}

/// 行情源的 ASCII 单码可带指数前缀 `^` 或期货/外汇后缀 `=F`、`=X` 等。
/// BASE/QUOTE 仍要求两侧均为大写 ASCII 资产代码。
pub(super) fn instrument(s: &str, field: &str) -> Result<(), String> {
    let ticker = |s: &str| s.is_ascii() && is_name(s);
    let asset = |s: &str| ticker(s) && !s.bytes().any(|b| b.is_ascii_lowercase());
    let valid = match s.split_once('/') {
        Some((base, quote)) => asset(base) && asset(quote),
        None => match s.strip_prefix('^') {
            Some(index) => ticker(index),
            None => match s.split_once('=') {
                Some((base, suffix)) => {
                    ticker(base)
                        && !suffix.is_empty()
                        && suffix.bytes().all(|b| b.is_ascii_alphanumeric())
                }
                None => ticker(s),
            },
        },
    };
    checked(valid, field, "市场标的或 BASE/QUOTE 交易对")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn economic_session_logical_names_are_not_path_or_reference_grammars() {
        assert!(namespace("test.feed", "source").is_ok());
        assert!(namespace("economic-session/replies", "replies").is_ok());
        assert!(namespace("s-observe/browser", "source").is_ok());
        for producer in [
            "historic",
            "E:sim-p4",
            "B:chong-BTC-L0",
            "B:chong-BTC-L0:tb1406-c8",
            "S:writer",
            "X:sim-p4",
        ] {
            assert!(domain_name(producer, "producer").is_ok(), "{producer}");
        }
        assert!(reference("per-leg-source-attribution/1", "contract").is_ok());
        for local in [
            "/tmp/db",
            "../db",
            "data/db",
            "local/e",
            "db.sqlite",
            r"C:\db",
            "C:db",
            "file://tmp/db",
        ] {
            assert!(name(local, "id").is_err(), "{local}");
            assert!(namespace(local, "source").is_err(), "{local}");
            assert!(domain_name(local, "producer").is_err(), "{local}");
            assert!(reference(local, "contract").is_err(), "{local}");
        }
        for producer in [
            "B:",
            "B::id",
            "B:id:",
            "B:id:..",
            "B:id:/tmp/x",
            "B:id:session.db",
            "B:::id",
            "B:id:session:extra",
            "E:id:session",
            "S:id:session",
            "X:id:session",
        ] {
            assert!(domain_name(producer, "producer").is_err(), "{producer}");
        }
        for ns in ["local/browser", "s-observe/browser/replies", "a/b/replies"] {
            assert!(namespace(ns, "source").is_err(), "{ns}");
        }
    }

    #[test]
    fn economic_session_instruments_keep_market_spelling_and_exclude_local_file_syntax() {
        for value in [
            "BTC",
            "ETH",
            "AAPL",
            "000001.SZ",
            "600519.SH",
            "BRK.B",
            "DX-Y.NYB",
            "^GSPC",
            "^HSI",
            "^STOXX50E",
            "GC=F",
            "CL=F",
            "EURUSD=X",
            "USDJPY=X",
            "BTC/USDT",
            "ETH/USDT",
            "BTC-USDT",
            "BTC-USDT-SWAP",
            "TEST.TICK",
            "alpha",
        ] {
            assert!(instrument(value, "symbol").is_ok(), "{value}");
        }
        for value in [
            "",
            "/BTC",
            "X/USDT/SWAP",
            "./BTC",
            "../BTC",
            "BTC/..",
            "BTC//USDT",
            "BTC/./USDT",
            r"BTC\USDT",
            "file://BTC",
            "C:BTC",
            "e.DB",
            "E.SQLITE3",
            "X/STATE.SOCK",
            "E.DB-WAL",
            "local/e",
            "BTC/USDT.JSONL",
            "^",
            "^^GSPC",
            "^../GSPC",
            "^GSPC..NASDAQ",
            "^GSPC.CSV",
            "^GSPC=X",
            "^GSPC/USDT",
            "=X",
            "GC=",
            "GC==F",
            "GC=F=X",
            "GC=期货",
            "GC=F.db",
            "GC.sqlite=F",
            "GC=F/USDT",
        ] {
            assert!(instrument(value, "symbol").is_err(), "{value}");
        }
    }
}
