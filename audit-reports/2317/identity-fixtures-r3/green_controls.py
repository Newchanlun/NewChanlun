"""查看原自测四个应绿样本的提交和磁盘状态，区分真对照和空操作。"""
import os
from pathlib import Path
import runpy
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import A, PIN, SELF, SPEC, box, gate, git, project, show

T = A + "/candidate/tier1_candidate.jsonl"


def main():
    tmp = box()
    base = project(tmp)
    cases = runpy.run_path(str(base / SELF))
    for name, build in (("noise", "m_wt_noise"), ("eol", "m_eol"),
                        ("replace", "m_replace"), ("synced", "m_synced")):
        c = tmp / name
        git(tmp, "clone", "-q", "--shared", base, c)
        if name == "synced":
            old = git(c, "rev-parse", "HEAD").decode().strip()
        cases[build](str(c))
        if name == "noise":
            assert (c / T).read_bytes() != git(c, "cat-file", "blob", "HEAD:" + T)
            assert stat.S_IMODE((c / SPEC).stat().st_mode) == 0o755 and (c / A / ".DS_Store").is_file()
            assert git(c, "rev-parse", "HEAD") == git(base, "rev-parse", "HEAD")
            print("noise: HEAD 不变；表字节、模式、未跟踪条目均实际改变")
        elif name == "eol":
            assert b"\r\n" in (c / PIN).read_bytes() and b"\r\n" not in git(c, "cat-file", "blob", "HEAD:" + PIN)
            assert git(c, "diff", "--name-only", "HEAD^", "HEAD").splitlines() == [b".gitattributes"]
            print("eol: 只提交根属性；磁盘钉选 CRLF、提交钉选 LF")
        elif name == "replace":
            raw = git(c, "--no-replace-objects", "cat-file", "blob", "HEAD:" + T)
            seen = git(c, "cat-file", "blob", "HEAD:" + T)
            assert raw != seen and seen == (c / T).read_bytes()
            print("replace: 普通 git 和磁盘均见替换字节，关闭替换后见原对象")
        else:
            cases["commit"](str(c))
            assert set(git(c, "diff", "--name-only", old, "HEAD").splitlines()) == {os.fsencode(T), os.fsencode(PIN)}
            p = gate(c, "--rev", "HEAD^")
            assert p.returncode == 1 and "与钉选" in p.stderr.decode()
            print("synced: 只改表的父提交退 1；两步总差异仅表和钉选")
            assert gate(c, "--rev", old).returncode == 0
        result = gate(c)
        show(name, result)
        assert result.returncode == 0 and b"GREEN" in result.stdout


if __name__ == "__main__":
    main()
