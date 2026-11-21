import os
import pathlib
import signal
import sqlite3
import subprocess
import sys
import tempfile

if len(sys.argv) == 3:
    conn = sqlite3.connect(sys.argv[1])
    if sys.argv[2] == "named":
        assert conn.execute("pragma locking_mode=exclusive").fetchone() == ("exclusive",)
    assert conn.execute("pragma journal_mode").fetchone() == ("wal",)
    conn.execute("pragma synchronous=full")
    conn.execute("pragma wal_autocheckpoint=0")
    if sys.argv[2] in ("writer", "named"):
        conn.execute("insert into entries values (2,'committed in WAL')")
        conn.commit()
        conn.execute("insert into entries values (3,'uncommitted')")
    else:
        conn.execute("begin")
        assert conn.execute("select count(*) from entries").fetchone() == (2,)
    print("ready", flush=True)
    signal.pause()

def child(path, role):
    p = subprocess.Popen([sys.executable, __file__, str(path), role], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "ready"
    return p

def rows(c):
    return c.execute("select * from entries order by id").fetchall()

def files(db):
    return {s: p.stat().st_size for s in ("", "-wal", "-shm") if (p := db.with_name(db.name + s)).exists()}

def connect(db, exclusive):
    conn = sqlite3.connect(f"file:{db}?mode=rw", uri=True, timeout=0)
    if exclusive:
        assert conn.execute("pragma locking_mode=exclusive").fetchone() == ("exclusive",)
    try:
        conn.execute("pragma synchronous=full")
    except Exception:
        conn.close()
        raise
    return conn

print(f"kernel={os.uname().sysname} sqlite={sqlite3.sqlite_version}")
for exclusive, live_reader in ((True, False), (True, True), (False, False)):
    with tempfile.TemporaryDirectory() as work:
        db = pathlib.Path(work, "s.db")
        print(subprocess.check_output(["stat", "-f", "-c", "%T", work], text=True).strip())
        c = sqlite3.connect(db)
        assert c.execute("pragma journal_mode=wal").fetchone() == ("wal",)
        c.execute("create table entries(id primary key, payload)")
        c.execute("insert into entries values (1,'baseline')")
        c.commit()
        c.close()
        child_writer = child(db, "writer")
        reader = child(db, "reader") if live_reader else None
        child_writer.kill()
        assert child_writer.wait() == -signal.SIGKILL
        print(f"exclusive={exclusive} reader={live_reader} residue={files(db)}")
        assert files(db)["-wal"] > 0 and files(db)["-shm"] > 0
        if reader:
            before = {s: db.with_name(db.name + s).read_bytes() for s in files(db)}
            c = None
            try:
                c = connect(db, exclusive)
                rows(c)
            except sqlite3.OperationalError as e:
                assert e.sqlite_errorcode == sqlite3.SQLITE_BUSY
                print("live reader: SQLITE_BUSY before checkpoint")
            else:
                raise AssertionError("live reader was not blocked")
            finally:
                if c:
                    c.close()
            assert before == {s: db.with_name(db.name + s).read_bytes() for s in files(db)}
            reader.kill()
            assert reader.wait() == -signal.SIGKILL
        c = connect(db, exclusive)
        assert rows(c) == [(1, "baseline"), (2, "committed in WAL")]
        checked = c.execute("pragma main.wal_checkpoint(truncate)").fetchone()
        print(f"checkpoint={checked} before_close={files(db)}")
        assert checked == (0, 0, 0)
        c.close()
        print(f"after_close={files(db)}")
        assert ("-shm" in files(db)) == exclusive and "-wal" not in files(db)
        c = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        assert rows(c) == [(1, "baseline"), (2, "committed in WAL")]
        c.close()
        print("exact committed rows retained; uncommitted row absent")

with tempfile.TemporaryDirectory() as work:
    db = pathlib.Path(work, "s.db")
    c = sqlite3.connect(db)
    assert c.execute("pragma journal_mode=wal").fetchone() == ("wal",)
    c.execute("create table entries(id primary key, payload)")
    c.execute("insert into entries values (1,'baseline')")
    c.commit()
    c.close()
    assert files(db) == {"": 12288}
    p = child(db, "named")
    p.kill()
    assert p.wait() == -signal.SIGKILL
    print(f"named txn loss after commit: {files(db)}")
    assert "-shm" not in files(db) and files(db)["-wal"] > 0
    c = connect(db, True)
    assert rows(c) == [(1, "baseline"), (2, "committed in WAL")]
    c.close()
    print("using exclusive before first WAL access on no-SHM source did not create SHM")
