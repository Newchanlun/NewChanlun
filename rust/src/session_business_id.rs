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

/// 域生产者等可用 `E:<id>`、`B:<id>`、`S:<id>`、`X:<id>`，并非通用 URI。
pub(super) fn domain_name(s: &str, field: &str) -> Result<(), String> {
    checked(
        is_name(s)
            || s.split_once(':')
                .is_some_and(|(domain, id)| matches!(domain, "E" | "B" | "S" | "X") && is_name(id)),
        field,
        "逻辑域业务标识",
    )
}

pub(super) fn namespace(s: &str, field: &str) -> Result<(), String> {
    checked(
        is_name(s) || s.strip_suffix("/replies").is_some_and(is_name),
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

/// 交易所标的允许点分代码、连字符及一条斜杠的 BASE/QUOTE；
/// 交易对的两侧都是大写 ASCII 资产代码，不接收通用位置串。
pub(super) fn instrument(s: &str, field: &str) -> Result<(), String> {
    let asset = |s: &str| is_name(s) && s.bytes().all(|b| b.is_ascii() && !b.is_ascii_lowercase());
    let valid = match s.split_once('/') {
        Some((base, quote)) => asset(base) && asset(quote),
        None => s.is_ascii() && is_name(s),
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
        assert!(domain_name("X:historical", "producer").is_ok());
        assert!(reference("per-leg-source-attribution/1", "contract").is_ok());
        for local in [
            "/tmp/db",
            "../db",
            "data/db",
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
        ] {
            assert!(instrument(value, "symbol").is_err(), "{value}");
        }
    }
}
