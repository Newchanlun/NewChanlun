"""#2078：让新 E 读取封存 /1 原件，X 不得以任何 profile 续写原库。"""
import json
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from simulation_capture_repair import exercise


def archived_capture(x_bin, e_bin, directory, canonical, digest, *, originals=None):
    """CI 重建发布头的全库 SQL 转储；独审可传入同次实跑的 x.sqlite 与两张原回执。"""
    frozen = Path(__file__).parent / "fixtures" / "issue2078" if originals is None else originals
    x_db = directory / "x.sqlite"
    if originals is None:
        with sqlite3.connect(x_db) as db:
            db.executescript((frozen / "x-profile-1.sql").read_text())
    else:
        shutil.copyfile(frozen / "x.sqlite", x_db)
    receipt, other = (json.loads((frozen / name).read_bytes()) for name in
                      ("query-batch-b1.json", "query-batch-b1-alternate.json"))
    with sqlite3.connect(x_db.as_uri() + "?mode=ro", uri=True) as db:
        source = json.loads(db.execute("SELECT v FROM x_sim_meta WHERE k='authority_profile'").fetchone()[0])
        assert db.execute("SELECT value FROM x_meta WHERE key='profile_revision'").fetchone() == ("x-execution-profile/1",)
        assert db.execute("SELECT v FROM x_sim_meta WHERE k='exact_profile_revision'").fetchone() is None
        assert db.execute("SELECT result FROM x_sim_batches WHERE id='b1'").fetchone() == (canonical(receipt),)

    # 不在只读取证的源文件上运行写进程。两种 profile 都须在 epoch 或业务内容变更前拒绝。
    write_copy = directory / "refuse-write.sqlite"
    with sqlite3.connect(x_db.as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(write_copy) as dst:
        src.backup(dst)
        before = list(dst.iterdump())
    for version in ("x-execution-profile/1", "x-execution-profile/2"):
        profile = directory / "writer.json"
        profile.write_text(canonical(dict(profile_revision=version, mode="simulation", history_simulation=source,
                                          credential_scope=dict(env="UNUSED_SIMULATION_CREDENTIAL"))))
        attempt = subprocess.run([x_bin, "serve", "--db", write_copy, "--profile", profile, "--writer-epoch", "2"],
                                 capture_output=True, timeout=5)
        assert attempt.returncode != 0 and b"VersionUnsupported" in attempt.stderr, attempt
        with sqlite3.connect(write_copy.as_uri() + "?mode=ro", uri=True) as db:
            assert list(db.iterdump()) == before
        print(f"{version} → 封存 /1 非空库：{attempt.stderr.decode().strip()}")

    before_bytes = x_db.read_bytes()
    with tempfile.TemporaryDirectory(prefix="c2-") as sock_dir:
        exercise(e_bin, directory, Path(sock_dir) / "e", x_db, source, receipt, None, other,
                 canonical, digest, archived_v1=True)
    assert x_db.read_bytes() == before_bytes
    with sqlite3.connect(x_db.as_uri() + "?mode=ro", uri=True) as db:
        assert list(db.iterdump()) == before
    print("PASS #2078 /1：固定批补录后原 X 文件和全表内容不变")
