//! X 不让 SQLite 接触 E 的 WAL/SHM。只在无副文件且介质不变时直接读取 E。
use super::store::{checked_sqlite_version, err, filesystem, open};
use rusqlite::{Connection, OpenFlags};
use std::{
    ffi::OsStr,
    fs::{self, File, Metadata},
    io::{self, Read},
    os::unix::fs::MetadataExt,
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
    dir: &'a Path,
}

impl<'a> Paths<'a> {
    fn new(db: &'a Path) -> Result<Self, String> {
        let dir = db.parent().ok_or("StorageUnavailable：E 库缺父目录")?;
        Ok(Self {
            db,
            wal: sidecar(db, "-wal"),
            shm: sidecar(db, "-shm"),
            dir,
        })
    }

    fn inspect(&self) -> Result<Media, String> {
        // 目录元信息同时检查两次观察之间短暂出现又消失的 WAL。
        let dir = fs::metadata(self.dir).map_err(err)?.into();
        let db = file_stamp(self.db)?.ok_or("StorageUnavailable：原 E 域库不存在")?;
        let wal = file_stamp(&self.wal)?;
        let shm = file_stamp(&self.shm)?;
        Ok(Media { db, wal, shm, dir })
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
    use std::os::unix::fs::OpenOptionsExt;
    let mut source = File::options()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(source)
        .map_err(err)?;
    if Stamp::from(source.metadata().map_err(err)?) != *expected {
        return Err(changed());
    }
    let mut dest = File::create_new(dest).map_err(err)?;
    let copied = io::copy(&mut (&mut source).take(expected.len), &mut dest).map_err(err)?;
    if copied != expected.len || Stamp::from(source.metadata().map_err(err)?) != *expected {
        return Err(changed());
    }
    Ok(())
}

fn immutable_uri(path: &Path) -> String {
    use std::fmt::Write;
    let mut uri = String::from("file:");
    for &byte in OsStr::as_encoded_bytes(path.as_os_str()) {
        if byte.is_ascii_alphanumeric() || b"-._~".contains(&byte) {
            uri.push(char::from(byte));
        } else {
            write!(uri, "%{byte:02X}").expect("write to String");
        }
    }
    uri.push_str("?mode=ro&immutable=1");
    uri
}

pub(super) fn read<T>(
    db: &Path,
    verify: impl FnOnce(&Connection) -> Result<T, String>,
) -> Result<T, String> {
    filesystem(db)?;
    let paths = Paths::new(db)?;
    let before = paths.inspect()?;
    let result = if before.wal.is_none() && before.shm.is_none() {
        checked_sqlite_version()?;
        let c = Connection::open_with_flags(
            immutable_uri(db),
            OpenFlags::SQLITE_OPEN_URI | OpenFlags::SQLITE_OPEN_READ_ONLY,
        )
        .map_err(err)?;
        c.execute_batch("PRAGMA temp_store=MEMORY;").map_err(err)?;
        paths.unchanged(&before)?;
        verify(&c)
    } else {
        // SHM 是索引与锁，不是原证；由 SQLite 在 X 的目录依据复制的 WAL 重建。
        let temp_root = std::env::temp_dir().canonicalize().map_err(err)?;
        if temp_root.starts_with(paths.dir.canonicalize().map_err(err)?) {
            return Err("StorageUnavailable：X 临时目录不得位于 E 部署目录内".into());
        }
        let temp = tempfile::tempdir_in(temp_root).map_err(err)?;
        let copy = temp.path().join("economic.db");
        copy_read_only(db, &copy, &before.db)?;
        if let Some(wal) = &before.wal {
            copy_read_only(&paths.wal, &sidecar(&copy, "-wal"), wal)?;
        }
        paths.unchanged(&before)?;
        let (mut c, _) = open(&copy, true)?;
        c.execute_batch("PRAGMA temp_store=MEMORY;").map_err(err)?;
        let tx = c.transaction().map_err(err)?;
        verify(&tx)
    };
    paths.unchanged(&before)?;
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wal_appearing_during_immutable_read_invalidates_proof() {
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
