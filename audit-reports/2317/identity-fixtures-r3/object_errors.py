"""在私有投影中区分材料不符与对象库不能读取；不改来源对象库。"""
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import A, B, CHECK, ENV, PIN, SPEC, box, gate, git, project, show


def unavailable(tmp, c, target, label):
    oid = git(c, "rev-parse", "HEAD:" + target).strip().decode()
    obj = c / ".git" / "objects" / oid[:2] / oid[2:]
    held = tmp / oid
    obj.rename(held)
    try:
        show(label, gate(c))
    finally:
        held.rename(obj)


def main():
    tmp = box()
    c = project(tmp)
    good = git(c, "rev-parse", "HEAD").strip().decode()
    if sys.argv[1:] != ["mixed"]:
        p = gate(c, "--print-pin")
        assert p.returncode == 0 and p.stdout == git(c, "cat-file", "blob", "HEAD:" + PIN)
        for target in (PIN, SPEC, B):
            unavailable(tmp, c, target, "不可读对象 " + target)
    git(c, "mv", SPEC, c / "former-spec.md")
    git(c, "commit", "-qm", "missing material")
    unavailable(tmp, c, B, "准入已不符，同时语料对象不可读")
    if sys.argv[1:] == ["mixed"]:
        return
    show("提交确实缺少必需文件", gate(c))
    read, write = os.pipe()
    os.close(read)
    try:
        p = subprocess.run([sys.executable, "-I", CHECK], cwd=c, env=ENV,
                           stdout=subprocess.PIPE, stderr=write)
    finally:
        os.close(write)
    print(f"同一不符，stderr 只有写端: rc={p.returncode}, stdout={p.stdout!r}", flush=True)
    # 给旧的有效提交以当前检出的脚本：不能偷读当前 HEAD。
    show("显式选择旧的正常提交", gate(c, "--rev", good))
    git(c, "mv", A, c / "former-admit")
    git(c, "commit", "-qm", "missing subtree")
    show("提交确实没有受检根", gate(c))


if __name__ == "__main__":
    main()
