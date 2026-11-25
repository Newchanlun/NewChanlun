"""工作区判定的三个单元断言；均只用临时的一条普通记录，不构造替代提交。"""
import hashlib
import importlib.util
import os
import tempfile
from pathlib import Path

from sys import path
path.insert(0, str(Path(__file__).resolve().parent))
from fixture_repo import CHECK, tmp_parent

spec = importlib.util.spec_from_file_location("subject", Path.cwd()/CHECK)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)
root = Path(tempfile.mkdtemp(dir=tmp_parent()))
folder = root/"data"
folder.mkdir()
sample = folder/"note"
sample.write_bytes(b"test\n")
sample.chmod(0o644)
record = [(b"data/note", "100644", "blob", hashlib.sha256(sample.read_bytes()).hexdigest())]


def test(label, should_accept):
    actual = subject.disk_problems(str(root), record, "data")
    print(label, "预期", "无差异" if should_accept else "有差异", "实际", actual)
    return (not actual) == should_accept


checks = [test("基线：目录与 100644 文件", True)]
sample.chmod(0o755)
checks.append(test("工作区文件 100755", False))
sample.chmod(0o644)
folder.rename(root/"material")
os.symlink("material", folder, target_is_directory=True)
checks.append(test("工作区根条目 120000", False))
raise SystemExit(int(not all(checks)))
