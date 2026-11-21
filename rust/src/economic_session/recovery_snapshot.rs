//! X 只从 E 读取主库和 WAL；SQLite 仅在私有快照上复用 E 的介质准入。
use super::store::{err, filesystem, open};
use rusqlite::Connection;
use std::{
    fs::{self, File, Metadata, OpenOptions},
    io::{self, Read},
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
};

#[derive(Debug, PartialEq, Eq)]
struct Stamp {
    device: u64,
    inode: u64,
    len: u64,
    mtime: (i64, i64),
    ctime: (i64, i64),
}

impl From<Metadata> for Stamp {
    fn from(m: Metadata) -> Self {
        Self {
            device: m.dev(),
            inode: m.ino(),
            len: m.len(),
            mtime: (m.mtime(), m.mtime_nsec()),
            ctime: (m.ctime(), m.ctime_nsec()),
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
struct Media {
    db: Stamp,
    wal: Option<Stamp>,
    shm: Option<Stamp>,
    dir: Stamp,
}

struct Paths<'a> {
    db: &'a Path,
    wal: PathBuf,
    shm: PathBuf,
    journal: PathBuf,
    dir: &'a Path,
}

impl<'a> Paths<'a> {
    fn new(db: &'a Path) -> Result<Self, String> {
        let dir = db.parent().ok_or("StorageUnavailable：E 库缺父目录")?;
        Ok(Self {
            db,
            wal: sidecar(db, "-wal"),
            shm: sidecar(db, "-shm"),
            journal: sidecar(db, "-journal"),
            dir,
        })
    }

    fn inspect(&self) -> Result<Media, String> {
        // 目录元信息同时检查两次观察之间短暂出现又消失的 WAL。
        let dir = fs::metadata(self.dir).map_err(err)?;
        if !dir.is_dir() {
            return Err("StorageUnavailable：E 库父路径不是目录".into());
        }
        let db = file_stamp(self.db)?.ok_or("StorageUnavailable：原 E 域库不存在")?;
        let wal = file_stamp(&self.wal)?;
        let shm = file_stamp(&self.shm)?;
        if file_stamp(&self.journal)?.is_some() {
            return Err("StorageUnavailable：E 库存在回滚日志".into());
        }
        Ok(Media {
            db,
            wal,
            shm,
            dir: dir.into(),
        })
    }

    fn unchanged(&self, old: &Media) -> Result<(), String> {
        if self.inspect()? != *old {
            return Err(changed());
        }
        Ok(())
    }
}

fn changed() -> String {
    "StorageUnavailable：E 介质变化，无法确认一致的只读恢复快照".into()
}

fn sidecar(db: &Path, suffix: &str) -> PathBuf {
    let mut name = db.as_os_str().to_owned();
    name.push(suffix);
    name.into()
}

fn file_stamp(path: &Path) -> Result<Option<Stamp>, String> {
    match fs::symlink_metadata(path) {
        Ok(m) if m.is_file() => Ok(Some(m.into())),
        Ok(_) => Err("StorageUnavailable：E 库或其副文件不是普通文件".into()),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(err(e)),
    }
}

fn copy_read_only(source: &Path, dest: &Path, expected: &Stamp) -> Result<(), String> {
    let mut source = File::options()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(source)
        .map_err(err)?;
    if Stamp::from(source.metadata().map_err(err)?) != *expected {
        return Err(changed());
    }
    let mut dest = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(dest)
        .map_err(err)?;
    let copied = io::copy(&mut (&mut source).take(expected.len), &mut dest).map_err(err)?;
    if copied != expected.len || Stamp::from(source.metadata().map_err(err)?) != *expected {
        return Err(changed());
    }
    Ok(())
}

pub(super) fn read<T>(
    db: &Path,
    verify: impl FnOnce(&Connection) -> Result<T, String>,
) -> Result<T, String> {
    filesystem(db)?;
    let paths = Paths::new(db)?;
    let before = paths.inspect()?;
    let temp_root = std::env::temp_dir().canonicalize().map_err(err)?;
    if temp_root.starts_with(paths.dir.canonicalize().map_err(err)?) {
        return Err("StorageUnavailable：X 临时目录不得位于 E 部署目录内".into());
    }
    let temp = tempfile::Builder::new()
        .permissions(fs::Permissions::from_mode(0o700))
        .tempdir_in(temp_root)
        .map_err(err)?;
    let copy = temp.path().join("economic.db");
    copy_read_only(db, &copy, &before.db)?;
    if let Some(wal) = &before.wal {
        copy_read_only(&paths.wal, &sidecar(&copy, "-wal"), wal)?;
    }
    // SHM 不是原证；SQLite 只在私有目录内重建索引和锁。
    paths.unchanged(&before)?;
    let (mut c, _) = open(&copy, true)?;
    c.execute_batch("PRAGMA temp_store=MEMORY;").map_err(err)?;
    let tx = c.transaction().map_err(err)?;
    let result = verify(&tx);
    paths.unchanged(&before)?;
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn active_wal_is_read_in_a_private_snapshot() {
        let space = tempfile::tempdir().unwrap();
        let db = space.path().join("e.db");
        let (writer, _) = open(&db, false).unwrap();
        writer
            .execute_batch(
                "CREATE TABLE proof (epoch INTEGER); INSERT INTO proof VALUES (1);
                 PRAGMA wal_checkpoint(TRUNCATE); UPDATE proof SET epoch=2;",
            )
            .unwrap();
        let paths = Paths::new(&db).unwrap();
        let before = paths.inspect().unwrap();
        assert!(before.wal.as_ref().unwrap().len > 32);
        read(&db, |c| {
            let epoch: i64 = c
                .query_row("SELECT epoch FROM proof", [], |r| r.get(0))
                .unwrap();
            assert_eq!(epoch, 2);
            let copy: String = c
                .query_row(
                    "SELECT file FROM pragma_database_list WHERE name='main'",
                    [],
                    |r| r.get(0),
                )
                .unwrap();
            let copy = Path::new(&copy);
            let mode = |p: &Path| fs::metadata(p).unwrap().mode() & 0o777;
            assert_eq!(mode(copy.parent().unwrap()), 0o700);
            for file in [
                copy.to_owned(),
                sidecar(copy, "-wal"),
                sidecar(copy, "-shm"),
            ] {
                assert_eq!(mode(&file), 0o600, "{}", file.display());
            }
            Ok(())
        })
        .unwrap();
        paths.unchanged(&before).unwrap();
    }

    #[test]
    fn sidecar_free_delete_database_fails_the_same_wal_gate_as_e() {
        let space = tempfile::tempdir().unwrap();
        let db = space.path().join("e.db");
        let writer = Connection::open(&db).unwrap();
        writer
            .execute_batch("CREATE TABLE proof (epoch INTEGER); INSERT INTO proof VALUES (2);")
            .unwrap();
        drop(writer);
        let paths = Paths::new(&db).unwrap();
        let before = paths.inspect().unwrap();
        assert!(before.wal.is_none() && before.shm.is_none());
        assert_eq!(&fs::read(&db).unwrap()[18..20], &[1, 1]);
        let e_error = open(&db, true).unwrap_err();
        assert!(e_error.contains("WAL/FULL/fullfsync"), "{e_error}");
        let x_error = read::<()>(&db, |_| {
            panic!("non-WAL medium reached business verification")
        })
        .unwrap_err();
        assert_eq!(x_error, e_error);
        paths.unchanged(&before).unwrap();
    }

    #[test]
    fn rollback_journal_is_rejected_before_business_verification() {
        let space = tempfile::tempdir().unwrap();
        let db = space.path().join("e.db");
        drop(open(&db, false).unwrap());
        File::create(sidecar(&db, "-journal")).unwrap();
        let error = read::<()>(&db, |_| {
            panic!("unexpected journal reached business verification")
        })
        .unwrap_err();
        assert!(error.contains("E 库存在回滚日志"), "{error}");
    }

    #[test]
    fn wal_appearing_during_read_invalidates_proof() {
        let space = tempfile::tempdir().unwrap();
        let db = space.path().join("e.db");
        let (writer, _) = open(&db, false).unwrap();
        writer
            .execute_batch("CREATE TABLE proof (epoch INTEGER); INSERT INTO proof VALUES (1);")
            .unwrap();
        drop(writer);
        let paths = Paths::new(&db).unwrap();
        assert!(paths.inspect().unwrap().wal.is_none());

        let mut writer = None;
        let result = read(&db, |c| {
            assert_eq!(
                c.query_row("SELECT epoch FROM proof", [], |r| r.get::<_, i64>(0))
                    .unwrap(),
                1
            );
            let (active, _) = open(&db, false).unwrap();
            active.execute("UPDATE proof SET epoch=2", []).unwrap();
            writer = Some(active);
            assert!(paths.inspect().unwrap().wal.is_some());
            Ok(())
        });
        assert_eq!(result.unwrap_err(), changed());
        assert!(writer.is_some());
    }
}
