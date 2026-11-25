"""以真实的子进程退出码核对输出失败；管道在启动子进程前已关掉读端。"""
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CHECK, ENV, REV, SRC


def main():
    args = [sys.executable, "-I", str(SRC / CHECK), "--root", str(SRC), "--rev", REV]
    cases = ("green", "print-pin", "no-stdout", "ascii-green", "bad-rev")
    for label in sys.argv[1:] or cases:
        assert label in cases
        cmd = list(args)
        env = ENV
        if label == "bad-rev":
            cmd[-1] = "r3-nonexistent-commit"
        if label == "print-pin":
            cmd.append("--print-pin")
        if label == "ascii-green":
            env = dict(ENV, LC_ALL="en_US.US-ASCII")
        read, write = os.pipe()
        os.close(read)
        try:
            p = subprocess.run(cmd, env=env, stderr=subprocess.PIPE,
                               stdout=write if label in ("green", "print-pin") else subprocess.PIPE,
                               preexec_fn=(lambda: os.close(1)) if label == "no-stdout" else None)
        finally:
            os.close(write)
        print(f"{label}: rc={p.returncode}", flush=True)
        if p.stderr:
            print(p.stderr.decode(errors="backslashreplace").rstrip(), flush=True)


if __name__ == "__main__":
    main()
