//! #1419 3C effects S1：effects 写记录与内容节点存储（`TxStore`）在 owner 事务上实际执行的
//! SQL 面。
//!
//! `Legacy` 就是现行事务所在的 rusqlite 连接：调用方在 Legacy 分支里逐字保留原 rusqlite 调用，
//! SQL、次序与错误文本不变。`Charged` 是受管 owner 守卫（U5），目前只由全新进程 release 锁消费，
//! cfg 与 `owner_sql` 收费一族一致；Native 一次启用波随生产调用点一起放宽。
//!
//! OwnerTx/OwnerOps 只借用连接；OwnerStatement 拥有短生涯语句，行视图只借当前行。
// 非增量构建没有 effects 消费者（与 `owner_sql` 同一写法）。
#![cfg_attr(not(feature = "s_incremental"), allow(dead_code))]
use rusqlite::types::FromSql;
use rusqlite::types::ValueRef;
use rusqlite::{Connection, Transaction};

/// owner 事务所在连接（借用）。
#[derive(Clone, Copy)]
pub(crate) enum OwnerTx<'a> {
    Legacy(&'a Connection),
    #[cfg(all(test, feature = "s_incremental", unix))]
    Charged(&'a super::owner_sql::ChargedOwnerTxn<'a>),
}

impl<'a> From<&'a Transaction<'_>> for OwnerTx<'a> {
    fn from(tx: &'a Transaction<'_>) -> Self {
        Self::Legacy(tx)
    }
}

impl<'a> From<&'a Connection> for OwnerTx<'a> {
    fn from(conn: &'a Connection) -> Self {
        Self::Legacy(conn)
    }
}

impl OwnerTx<'_> {
    /// 无分配读取事务状态，两个后端沿用同一 SQLite autocommit 判据。
    pub(crate) fn is_autocommit(&self) -> bool {
        match self {
            Self::Legacy(conn) => conn.is_autocommit(),
            #[cfg(all(test, feature = "s_incremental", unix))]
            Self::Charged(txn) => txn.connection().is_autocommit(),
        }
    }

    /// 连接打开以来的累计变更行数。只读连接状态，不执行 SQL、不分配。
    pub(crate) fn total_changes(&self) -> u64 {
        match self {
            Self::Legacy(conn) => conn.total_changes(),
            #[cfg(all(test, feature = "s_incremental", unix))]
            Self::Charged(txn) => txn.connection().total_changes(),
        }
    }
    /// 最近一条完成语句的直接变更行数。只读连接状态，不执行 SQL、不分配。
    #[cfg(feature = "s_incremental")]
    pub(crate) fn changes(&self) -> u64 {
        match self {
            Self::Legacy(conn) => conn.changes(),
            #[cfg(all(test, feature = "s_incremental", unix))]
            Self::Charged(txn) => txn.connection().changes(),
        }
    }
    /// effects 节点 journal 的连接键：rusqlite 连接为句柄地址（原口径），受管连接为不复用的
    /// `ConnectionId`。
    #[cfg(feature = "s_incremental")]
    pub(in crate::v3) fn journal_key(&self) -> super::owner_sql::JournalKey {
        match self {
            // SAFETY: the handle is only compared as an address, never dereferenced.
            Self::Legacy(conn) => {
                super::owner_sql::JournalKey::Handle(unsafe { conn.handle() } as usize)
            }
            #[cfg(all(test, feature = "s_incremental", unix))]
            Self::Charged(txn) => super::owner_sql::JournalKey::Charged(txn.connection().id()),
        }
    }
}

/// 一行的列借用：rusqlite 行，或受管语句当前行的列值。只在取行回调期内有效。
pub(crate) enum OwnerRow<'r> {
    Legacy(&'r rusqlite::Row<'r>),
    #[cfg(all(test, feature = "s_incremental", unix))]
    Charged(&'r [ValueRef<'r>]),
}

impl OwnerRow<'_> {
    pub(crate) fn text(&self, index: usize) -> rusqlite::Result<&str> {
        let value = match self {
            Self::Legacy(row) => row.get_ref(index)?,
            #[cfg(all(test, feature = "s_incremental", unix))]
            Self::Charged(cells) => cells
                .get(index)
                .copied()
                .ok_or(rusqlite::Error::InvalidColumnIndex(index))?,
        };
        value
            .as_str()
            .map_err(|error| conversion_error(index, value, error))
    }
    /// SQL 文本只在回调内借用，复制前向当前拥有结果域收费。
    pub(crate) fn text_admitted(
        &self,
        index: usize,
        work: Option<&newchan_rust::s_content::capture_allocation::scratch::WorkScope>,
    ) -> Result<crate::v3::business_json::TextValue, newchan_rust::s_content::ContextError> {
        let value = match self {
            Self::Legacy(row) => row.get_ref(index),
            #[cfg(all(test, feature = "s_incremental", unix))]
            Self::Charged(cells) => cells
                .get(index)
                .copied()
                .ok_or(rusqlite::Error::InvalidColumnIndex(index)),
        }
        .map_err(|e| OwnerSqlError::Sqlite(e).context("", work))?;
        let text = value.as_str().map_err(|error| {
            OwnerSqlError::Sqlite(conversion_error(index, value, error)).context("", work)
        })?;
        crate::v3::business_json::TextValue::from_str_admitted_typed(text, None, work)
            .map_err(|e| newchan_rust::s_content::ContextError::from_codec(e, ""))
    }
    /// 按列取值。Legacy 即 `rusqlite::Row::get`；受管行按同一 `FromSql` 转换并按 rusqlite 同一
    /// 映射报错（受管语句不交出列名，类型错误中的列名为空）。
    pub(crate) fn get<T: FromSql>(&self, index: usize) -> rusqlite::Result<T> {
        match self {
            Self::Legacy(row) => row.get(index),
            #[cfg(all(test, feature = "s_incremental", unix))]
            Self::Charged(cells) => {
                let value = cells
                    .get(index)
                    .copied()
                    .ok_or(rusqlite::Error::InvalidColumnIndex(index))?;
                T::column_result(value).map_err(|error| conversion_error(index, value, error))
            }
        }
    }
}

/// `rusqlite::Row::get` 的同一错误映射（rusqlite 0.40.2 `row.rs:288-302`）。
fn conversion_error(
    index: usize,
    value: ValueRef<'_>,
    error: rusqlite::types::FromSqlError,
) -> rusqlite::Error {
    use rusqlite::types::FromSqlError;
    match error {
        FromSqlError::InvalidType => {
            rusqlite::Error::InvalidColumnType(index, String::new(), value.data_type())
        }
        FromSqlError::OutOfRange(n) => rusqlite::Error::IntegralValueOutOfRange(index, n),
        FromSqlError::Utf8Error(error) => rusqlite::Error::Utf8Error(index, error),
        FromSqlError::Other(error) => {
            rusqlite::Error::FromSqlConversionFailure(index, value.data_type(), error)
        }
        error => {
            rusqlite::Error::FromSqlConversionFailure(index, value.data_type(), Box::new(error))
        }
    }
}

/// #1419 A1：短生涯操作面；受管变体只在 binding.run 回调内构造。
pub(crate) enum OwnerOps<'a> {
    Legacy(&'a Connection),
    #[cfg(all(test, feature = "s_incremental", unix))]
    Charged(&'a newchan_rust::s_content::capture_allocation::sqlite_parent::SqlOps<'a>),
}

pub(crate) enum OwnerStatement<'a> {
    Legacy(rusqlite::Statement<'a>),
    #[cfg(all(test, feature = "s_incremental", unix))]
    Charged(newchan_rust::s_content::capture_allocation::sqlite_parent::GatedStatement<'a>),
}

#[derive(Debug)]
pub(crate) enum OwnerSqlError {
    Sqlite(rusqlite::Error),
    #[cfg(all(test, feature = "s_incremental", unix))]
    Charged(newchan_rust::s_content::capture_allocation::sqlite_parent::SqlGate),
}
impl OwnerSqlError {
    pub(crate) fn context(
        self,
        prefix: &str,
        work: Option<&newchan_rust::s_content::capture_allocation::scratch::WorkScope>,
    ) -> newchan_rust::s_content::ContextError {
        #[cfg(all(test, feature = "s_incremental", unix))]
        if let (
            Self::Charged(
                newchan_rust::s_content::capture_allocation::sqlite_parent::SqlGate::Refused(
                    failure,
                ),
            ),
            Some(work),
        ) = (&self, work)
        {
            return newchan_rust::s_content::ContextError::from_codec(
                work.reject(*failure),
                prefix,
            );
        }
        let _ = work;
        let message = match self {
            Self::Sqlite(error) => error.to_string(),
            #[cfg(all(test, feature = "s_incremental", unix))]
            Self::Charged(error) => format!("受管SQLite拒绝：{error:?}"),
        };
        newchan_rust::s_content::ContextError::from(format!("{prefix}{message}"))
    }
    fn missing() -> Self {
        Self::Sqlite(rusqlite::Error::QueryReturnedNoRows)
    }
}

impl OwnerTx<'_> {
    pub(crate) fn with_ops<R>(
        self,
        work: Option<&newchan_rust::s_content::capture_allocation::scratch::WorkScope>,
        f: impl FnOnce(OwnerOps<'_>) -> Result<R, newchan_rust::s_content::ContextError>,
    ) -> Result<R, newchan_rust::s_content::ContextError> {
        let _ = work;
        match self {
            Self::Legacy(conn) => f(OwnerOps::Legacy(conn)),
            #[cfg(all(test, feature = "s_incremental", unix))]
            Self::Charged(tx) => {
                let Some(scope) = work else {
                    return Err(
                        "prototype_audit_allocation_incomplete：受管操作缺拥有结果域".into(),
                    );
                };
                scope
                    .check_current()
                    .map_err(|e| newchan_rust::s_content::ContextError::from_codec(e, ""))?;
                if !tx.binding().serves_work(scope) {
                    return Err(OwnerSqlError::Charged(newchan_rust::s_content::capture_allocation::sqlite_parent::SqlGate::WrongParent).context("", work));
                }
                tx.run(|ops| Ok(f(OwnerOps::Charged(ops))))
                    .map_err(|error| OwnerSqlError::Charged(error).context("", work))?
            }
        }
    }
}

impl OwnerOps<'_> {
    pub(crate) fn prepare(&self, sql: &str) -> Result<OwnerStatement<'_>, OwnerSqlError> {
        match self {
            Self::Legacy(conn) => conn
                .prepare(sql)
                .map(OwnerStatement::Legacy)
                .map_err(OwnerSqlError::Sqlite),
            #[cfg(all(test, feature = "s_incremental", unix))]
            Self::Charged(ops) => ops
                .prepare(sql)
                .map(OwnerStatement::Charged)
                .map_err(OwnerSqlError::Charged),
        }
    }
    pub(crate) fn execute<const N: usize>(
        &self,
        sql: &str,
        params: [&dyn rusqlite::ToSql; N],
    ) -> Result<usize, OwnerSqlError> {
        self.prepare(sql)?.execute(params)
    }
    pub(crate) fn query_optional<T, const N: usize>(
        &self,
        sql: &str,
        params: [&dyn rusqlite::ToSql; N],
        f: impl FnOnce(OwnerRow<'_>) -> rusqlite::Result<T>,
    ) -> Result<Option<T>, OwnerSqlError> {
        self.prepare(sql)?.query_optional(params, f)
    }
    pub(crate) fn query_row<T, const N: usize>(
        &self,
        sql: &str,
        params: [&dyn rusqlite::ToSql; N],
        f: impl FnOnce(OwnerRow<'_>) -> rusqlite::Result<T>,
    ) -> Result<T, OwnerSqlError> {
        self.query_optional(sql, params, f)?
            .ok_or_else(OwnerSqlError::missing)
    }
}
impl OwnerStatement<'_> {
    pub(crate) fn execute<const N: usize>(
        &mut self,
        params: [&dyn rusqlite::ToSql; N],
    ) -> Result<usize, OwnerSqlError> {
        match self {
            Self::Legacy(stmt) => stmt
                .execute(params.as_slice())
                .map_err(OwnerSqlError::Sqlite),
            #[cfg(all(test, feature = "s_incremental", unix))]
            Self::Charged(stmt) => stmt.execute(params).map_err(OwnerSqlError::Charged),
        }
    }
    pub(crate) fn query_optional<T, const N: usize>(
        &mut self,
        params: [&dyn rusqlite::ToSql; N],
        f: impl FnOnce(OwnerRow<'_>) -> rusqlite::Result<T>,
    ) -> Result<Option<T>, OwnerSqlError> {
        match self {
            Self::Legacy(stmt) => {
                use rusqlite::OptionalExtension;
                stmt.query_row(params.as_slice(), |row| f(OwnerRow::Legacy(row)))
                    .optional()
                    .map_err(OwnerSqlError::Sqlite)
            }
            #[cfg(all(test, feature = "s_incremental", unix))]
            Self::Charged(stmt) => {
                let mut f = Some(f);
                let mut result = None;
                stmt.for_each_cells(params, |cells| {
                    result = Some(f.take().expect("首行回调只消费一次")(
                        OwnerRow::Charged(cells),
                    ));
                    std::ops::ControlFlow::Break(())
                })
                .map_err(OwnerSqlError::Charged)?;
                result.transpose().map_err(OwnerSqlError::Sqlite)
            }
        }
    }
    pub(crate) fn query_row<T, const N: usize>(
        &mut self,
        params: [&dyn rusqlite::ToSql; N],
        f: impl FnOnce(OwnerRow<'_>) -> rusqlite::Result<T>,
    ) -> Result<T, OwnerSqlError> {
        self.query_optional(params, f)?
            .ok_or_else(OwnerSqlError::missing)
    }
}
