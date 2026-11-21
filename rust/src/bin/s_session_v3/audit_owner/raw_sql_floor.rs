//! #2009：在 SQLite 编译 SQL 时保护 owner 的写数与 schema 审计输入。

use rusqlite::{ffi, Connection};
use std::ffi::{c_char, c_int, c_void, CStr};

unsafe extern "C" fn floor(
    _ctx: *mut c_void,
    action: c_int,
    first: *const c_char,
    second: *const c_char,
    _db: *const c_char,
    _origin: *const c_char,
) -> c_int {
    if action == ffi::SQLITE_SAVEPOINT {
        return ffi::SQLITE_DENY;
    }
    // SAFETY: SQLite 在回调期间提供以 NUL 结尾的 PRAGMA 名称；空指针不解引用。
    if action == ffi::SQLITE_PRAGMA
        && !second.is_null()
        && (first.is_null()
            || unsafe { CStr::from_ptr(first) }
                .to_bytes()
                .eq_ignore_ascii_case(b"schema_version"))
    {
        return ffi::SQLITE_DENY;
    }
    ffi::SQLITE_OK
}

pub(super) fn installed(connection: Connection) -> Result<Connection, String> {
    // SQLite 令已 prepare 的语句过期；缓存命中也要在执行前重新授权。
    // SAFETY: connection 持有活句柄；回调无状态，不借用任何上下文。
    let rc = unsafe {
        ffi::sqlite3_set_authorizer(connection.handle(), Some(floor), std::ptr::null_mut())
    };
    let result = if rc == ffi::SQLITE_OK {
        Ok(())
    } else {
        Err(super::invalid(format_args!(
            "安装 owner SQL 底线失败：SQLite rc={rc}"
        )))
    };
    #[cfg(all(feature = "s_incremental", unix))]
    let result = crate::h1_close_after_failure(&connection, result, false);
    result.map(|()| connection)
}

#[cfg(test)]
mod tests {
    use super::super::super::prepared::tests::Fixture;
    use super::super::AuditConnection;
    use super::{installed, Connection};
    use rusqlite::{ErrorCode, TransactionBehavior};

    const AUTH: ErrorCode = ErrorCode::AuthorizationForStatementDenied;

    fn guarded() -> Connection {
        installed(Connection::open_in_memory().unwrap()).unwrap()
    }

    #[track_caller]
    fn refused<T>(result: rusqlite::Result<T>, operation: &str) {
        match result {
            Ok(_) => panic!("accepted: {operation}"),
            Err(err) => assert_eq!(err.sqlite_error_code(), Some(AUTH), "{operation}"),
        }
    }

    fn cookie(conn: &Connection, sql: &str) -> i64 {
        conn.query_row(sql, [], |row| row.get(0)).unwrap()
    }

    fn rows(conn: &Connection) -> i64 {
        conn.query_row("SELECT count(*) FROM t", [], |row| row.get(0))
            .unwrap()
    }

    #[test]
    fn savepoint_family_is_refused_at_prepare() {
        let conn = guarded();
        for sql in [
            "SAVEPOINT a",
            "RELEASE a",
            "ROLLBACK TO a",
            "ROLLBACK TRANSACTION TO SAVEPOINT a",
            "RELEASE SAVEPOINT a",
            "savepoint a",
            "/*x*/ SaVePoInT a",
            "ROLLBACK/**/TO a",
        ] {
            refused(conn.prepare(sql), sql);
        }
        assert!(conn.is_autocommit());

        let plain = Connection::open_in_memory().unwrap();
        let err = plain.execute_batch("ROLLBACK TO a").unwrap_err();
        assert_eq!(err.sqlite_error_code(), Some(ErrorCode::Unknown));
        plain.execute_batch("SAVEPOINT a; RELEASE a").unwrap();
    }

    #[test]
    fn batch_stops_at_the_refused_statement() {
        let conn = guarded();
        conn.execute_batch("CREATE TABLE t (x)").unwrap();
        let sql = "INSERT INTO t VALUES (1); SAVEPOINT a; INSERT INTO t VALUES (2)";
        refused(conn.execute_batch(sql), sql);
        assert_eq!(rows(&conn), 1);
    }

    #[test]
    fn refusal_ignores_how_the_text_was_built() {
        macro_rules! sql {
            () => {
                "SAVEPOINT a"
            };
        }
        fn select_sql(alternative: bool) -> &'static str {
            match alternative {
                #[cfg(test)]
                true => "SELECT 1",
                _ => "SAVEPOINT a",
            }
        }
        #[cfg(feature = "s_session")]
        const SESSION_SQL: &str = "SAVEPOINT a";

        let mut conn = guarded();
        let formatted = format!("{kw} a", kw = "Savepoint");
        let bytes = String::from_utf8(b"SAVEPOINT a".to_vec()).unwrap();
        for sql in [
            concat!("SAVE", "POINT a"),
            &formatted,
            &bytes,
            "\x53AVEPOINT a",
            sql!(),
            select_sql(false),
            SESSION_SQL,
        ] {
            refused(conn.prepare(sql), sql);
        }
        refused(conn.savepoint(), "Connection::savepoint");
        refused(
            conn.pragma_update(None, "schema_version", 7),
            "unqualified pragma_update",
        );
        refused(
            conn.pragma_update(Some("main"), "schema_version", 7),
            "main pragma_update",
        );
    }

    #[test]
    fn schema_version_write_is_refused_in_every_spelling() {
        let conn = guarded();
        let before = cookie(&conn, "PRAGMA main.schema_version");
        for sql in [
            "PRAGMA schema_version=7",
            "PRAGMA main.schema_version = 7",
            "PRAGMA temp.schema_version=7",
            "PRAGMA SCHEMA_VERSION=7",
            "PRAGMA \"schema_version\"=7",
            "PRAGMA schema_version(7)",
            "PRAGMA schema_version=-1",
        ] {
            refused(conn.prepare(sql), sql);
        }
        assert_eq!(cookie(&conn, "PRAGMA main.schema_version"), before);
    }

    #[test]
    fn reads_and_other_pragmas_are_untouched() {
        let mut conn = guarded();
        let plain = Connection::open_in_memory().unwrap();
        for c in [&conn, &plain] {
            c.execute_batch("CREATE TABLE t (x)").unwrap();
        }
        assert_eq!(
            cookie(&conn, "PRAGMA schema_version"),
            cookie(&plain, "PRAGMA schema_version")
        );
        conn.execute_batch("PRAGMA user_version=7").unwrap();
        assert_eq!(cookie(&conn, "PRAGMA user_version"), 7);
        conn.execute_batch("PRAGMA schema_versionx=1").unwrap();
        conn.execute_batch("PRAGMA xschema_version=1").unwrap();
        conn.execute_batch("BEGIN IMMEDIATE; INSERT INTO t VALUES (1); COMMIT")
            .unwrap();
        conn.execute_batch("BEGIN; INSERT INTO t VALUES (2); ROLLBACK")
            .unwrap();
        assert_eq!(rows(&conn), 1);
        conn.transaction().unwrap().commit().unwrap();
    }

    #[test]
    fn d2_replay_cannot_restore_cookie() {
        let mut conn = guarded();
        conn.execute_batch("CREATE TABLE t (x)").unwrap();
        let tx = conn.transaction().unwrap();
        let before = cookie(&tx, "PRAGMA main.schema_version");
        tx.execute_batch("DROP TABLE t; CREATE TABLE t (x)")
            .unwrap();
        let sql = format!("PRAGMA main.schema_version={before}");
        refused(tx.execute_batch(&sql), &sql);
        assert_ne!(cookie(&tx, "PRAGMA main.schema_version"), before);
    }

    #[test]
    fn d1_replay_cannot_undo_rows() {
        let mut conn = guarded();
        conn.execute_batch("CREATE TABLE t (x)").unwrap();
        let tx = conn.transaction().unwrap();
        let before = rows(&tx);
        let changes = tx.total_changes();
        refused(tx.execute_batch("SAVEPOINT s"), "SAVEPOINT s");
        tx.execute("INSERT INTO t VALUES (1)", []).unwrap();
        refused(tx.execute_batch("ROLLBACK TO s"), "ROLLBACK TO s");
        assert_eq!(rows(&tx), before + 1);
        assert_eq!(tx.total_changes(), changes + 1);
    }

    #[test]
    fn statement_cached_before_install_is_refused_after() {
        let conn = Connection::open_in_memory().unwrap();
        let sql = "SAVEPOINT a";
        drop(conn.prepare_cached(sql).unwrap());
        let conn = installed(conn).unwrap();
        let mut cached = conn.prepare_cached(sql).unwrap();
        refused(cached.execute([]), sql);
        assert!(conn.is_autocommit());
    }

    #[test]
    fn owner_opened_by_path_is_born_refusing() {
        let mut fixture = Fixture::new();
        let (envelope, token) = fixture.accept_begin(1, ("a", 0, 6, 12, 3, 7), 1);
        fixture.publish(&envelope, &token).unwrap();

        let owner = AuditConnection::open(&fixture.db_path()).unwrap();
        refused(owner.execute_batch("SAVEPOINT a"), "SAVEPOINT a");
        let active = owner.begin(TransactionBehavior::Deferred).unwrap();
        for sql in ["ROLLBACK TO a", "PRAGMA main.schema_version=1"] {
            refused(active.tx().execute_batch(sql), sql);
        }
        active.read_end().unwrap();
        owner
            .begin(TransactionBehavior::Deferred)
            .unwrap()
            .read_end()
            .unwrap();
        refused(owner.execute_batch("SAVEPOINT a"), "SAVEPOINT a");
    }

    #[cfg(all(feature = "s_incremental", unix))]
    #[test]
    fn h1_rebuilt_owner_is_born_refusing() {
        let mut output = None;
        AuditConnection::initialize_rebuilt_owner(
            Connection::open_in_memory().unwrap(),
            &mut output,
        )
        .unwrap();
        let owner = output.unwrap();
        refused(owner.execute_batch("SAVEPOINT a"), "SAVEPOINT a");
    }
}
