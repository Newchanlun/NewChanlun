"""在私有 Git 对象库中区分内容拒绝、不可读对象、只生成钉选三条路径。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import A, B, CHECK, PIN, REV, SRC, box, git, project, run

base = box()
repo = project(base)
old = base / "r3.py"
old.write_bytes(git(SRC, "show", "58627d62b25b5be91081205b82b96907d9a11330:" + CHECK))
truth = git(SRC, "show", REV + ":" + PIN)


def set_entry(path, mode, oid):
    git(repo, "update-index", "--cacheinfo", mode, oid, path)


def move_object(oid):
    source = repo / ".git/objects" / oid[:2] / oid[2:]
    dest = base / oid
    source.rename(dest)
    return source, dest


def report(label, *args):
    p = run(repo, CHECK, *args)
    err = p.stderr.decode()
    print(f"{label}: rc={p.returncode}, RED={err.count('RED ')}, 运行诊断={'无法运行：' in err}")
    for line in err.splitlines():
        if line.startswith("RED "):
            print(line)
    assert b"Traceback" not in p.stderr
    return p


spec = A + "/SPEC.md"
spec_id = git(repo, "rev-parse", "HEAD:" + spec).decode().strip()
lesson = sorted((repo / B).glob("*.md"))[0].relative_to(repo).as_posix()
different = git(repo, "hash-object", "-w", "--stdin", data=b"changed\n").decode().strip()
set_entry(lesson, "100644", different)
git(repo, "commit", "-qm", "changed corpus")
p = report("仅语料不符")
assert p.returncode == 1 and "语料指纹" in p.stderr.decode()
for program in (old, CHECK):
    p = run(repo, program, "--root", repo, "--print-pin")
    assert p.returncode == 0 and p.stdout == truth and not p.stderr
print("语料不符时 R3/R4 --print-pin 均退 0，stdout 均逐字节等于候选 pin")

set_entry(spec, "100644", different)
git(repo, "commit", "-qm", "both comparisons differ")
p = report("两处值不符")
assert p.returncode == 1 and p.stderr.count(b"RED ") == 2

set_entry(spec, "100755", spec_id)
git(repo, "commit", "-qm", "bad mode before changed corpus")
p = report("准入抛 ValueError，语料指纹不符")
assert p.returncode == 1 and p.stderr.count(b"RED ") == 2 and "非普通文件" in p.stderr.decode()
for label, program, want in (("R3", old, 1), ("R4", CHECK, 2)):
    p = run(repo, program, "--root", repo, "--print-pin")
    assert p.returncode == want and not p.stdout and "非普通文件" in p.stderr.decode()
    print(f"准入非法时 {label} --print-pin: rc={p.returncode}, RED={p.stderr.count(b'RED ')}, stdout={p.stdout!r}")

set_entry(lesson, "100755", different)
git(repo, "commit", "-qm", "two bad modes")
p = report("两边都抛 ValueError")
assert p.returncode == 1 and p.stderr.decode().count("非普通文件") == 2
tree = git(repo, "rev-parse", "HEAD:" + B).decode().strip()
src, held = move_object(tree)
p = report("准入先红，随后语料对象不可读")
assert p.returncode == 2 and "RED 非普通文件" in p.stderr.decode() and "无法运行：" in p.stderr.decode()
held.rename(src)

set_entry(spec, "100644", spec_id)
git(repo, "commit", "-qm", "regular admit before invalid corpus")
src, held = move_object(spec_id)
p = report("准入对象先不可读，后方语料模式不符")
assert p.returncode == 2 and b"RED " not in p.stderr and "无法运行：" in p.stderr.decode()
held.rename(src)
p = report("恢复同一对象")
assert p.returncode == 1 and p.stderr.count(b"RED ") == 1 and B.encode() in p.stderr
