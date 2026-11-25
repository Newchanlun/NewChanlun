"""观察真实子进程的退出状态与输出；断管先关读端，满目标不写满磁盘。"""
from contextlib import ExitStack
import os
from pathlib import Path
import resource
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import A, CHECK, ENV, PIN, REV, SRC, box, git, project, run


def stream(repo, args, stream_name, kind, tmp):
    kw = {}
    with ExitStack() as stack:
        if kind == "断管":
            rd, wr = os.pipe()
            os.close(rd)
            stack.callback(os.close, wr)
            kw[stream_name] = wr
        elif kind == "关闭":
            fd = {"stdout": 1, "stderr": 2}[stream_name]
            kw["preexec_fn"] = lambda: os.close(fd)
        elif kind == "只读":
            kw[stream_name] = stack.enter_context(open(os.devnull, "rb"))
        elif kind in ("满", "短写"):
            f = stack.enter_context(open(tmp / "bounded-output", "wb"))
            kw[stream_name] = f
            size = 0 if kind == "满" else 8
            kw["preexec_fn"] = lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (size, size))
        else:
            assert kind == "普通"
        p = run(repo, CHECK, *args, **kw)
        if kind in ("满", "短写"):
            assert os.fstat(f.fileno()).st_size == size
    return p


def status():
    tmp = box()
    for name, args in (("正常检查", ["--rev", REV]), ("打印钉选", ["--rev", REV, "--print-pin"])):
        for kind in ("关闭", "断管", "只读", "满", "短写"):
            p = stream(SRC, args, "stdout", kind, tmp)
            print(name, "stdout", kind, p.returncode, p.stderr.decode().strip(), flush=True)
            assert p.returncode == 2 and "无法运行：" in p.stderr.decode() and b"Traceback" not in p.stderr
    repo = project(tmp)
    f = repo / A / "SPEC.md"
    f.write_bytes(f.read_bytes() + b"x")
    git(repo, "add", "-u")
    git(repo, "commit", "-qm", "one changed byte")
    for name, root, args, want in (
        ("相符", SRC, ["--rev", REV], 0), ("不符", repo, [], 1), ("坏版本", repo, ["--rev", "nope"], 2)
    ):
        for kind in ("普通", "关闭", "断管", "只读", "满"):
            p = stream(root, args, "stderr", kind, tmp)
            print(name, "stderr", kind, p.returncode, flush=True)
            assert p.returncode == want and (b"GREEN" in (p.stdout or b"")) == (want == 0)
            if kind == "普通":
                assert b"Traceback" not in p.stderr
                if want == 1:
                    assert p.stderr.startswith(b"RED ")
                if want == 2:
                    assert "无法运行" in p.stderr.decode()
    p = stream(repo, [], "stdout", "关闭", tmp)
    assert p.returncode == 1 and p.stderr.startswith(b"RED ")
    print("不符 stdout 关闭", p.returncode)


def locale_cases():
    pin = git(SRC, "cat-file", "blob", REV + ":" + PIN)
    for loc, io, flags in [
        ("C", "", ["-X", "utf8=0"]), ("en_US.US-ASCII", "", []),
        ("en_US.ISO8859-1", "", []), ("zh_CN.GBK", "", []),
        ("en_US.UTF-8", "ascii:strict", []), ("en_US.UTF-8", "latin-1:replace", []),
        ("en_US.UTF-8", "utf-16", []), ("en_US.UTF-8", "not-a-codec", []),
    ]:
        env = dict(ENV, LC_ALL=loc, LANG=loc, PYTHONIOENCODING=io)
        enc = run(SRC, *flags, "-c", "import sys; print(sys.stdout.encoding, sys.flags.utf8_mode)", env=env)
        green = run(SRC, *flags, CHECK, "--rev", REV, env=env)
        raw = run(SRC, *flags, CHECK, "--rev", REV, "--print-pin", env=env)
        invalid = run(SRC, *flags, CHECK, "--rev", "nope", env=env)
        print(loc, io or "(空)", enc.stdout.decode().strip(), "GREEN/pin/坏版本",
              green.returncode, raw.returncode, invalid.returncode, flush=True)
        assert green.returncode == 0 and "身份检查 GREEN" in green.stdout.decode("utf-8") and not green.stderr
        assert raw.returncode == 0 and raw.stdout == pin and not raw.stderr
        assert invalid.returncode == 2 and "无法运行" in invalid.stderr.decode("utf-8")
        assert b"Traceback" not in invalid.stderr and not invalid.stdout


def parser():
    tmp = box()
    for kind in ("普通", "关闭", "断管", "只读", "满"):
        p = stream(SRC, ["--no-such-option"], "stderr", kind, tmp)
        print(f"错误选项 / stderr {kind}: rc={p.returncode} stdout={p.stdout!r}", flush=True)
        if kind == "普通":
            assert p.returncode == 2 and b"unrecognized arguments" in p.stderr


def four():
    env = dict(ENV, LC_ALL="C", LANG="C")
    rd, wr = os.pipe()
    os.close(rd)
    try:
        for case, args, sink in (
            ("ascii-locale-green", ["--rev", REV], {}),
            ("ascii-locale-bad-rev", ["--rev", "nope"], {}),
            ("stdout-broken-pipe", ["--rev", REV], {"stdout": wr}),
            ("print-pin-broken-pipe", ["--rev", REV, "--print-pin"], {"stdout": wr}),
        ):
            p = run(SRC, "-X", "utf8=0", CHECK, *args, env=env, **sink)
            if case == "ascii-locale-green":
                cause = "身份检查 GREEN" in p.stdout.decode() and not p.stderr
            elif case == "ascii-locale-bad-rev":
                cause = b"rev-parse" in p.stderr and "无法运行" in p.stderr.decode()
            else:
                cause = b"Broken pipe" in p.stderr and "无法运行" in p.stderr.decode()
            print(f"{case}: rc={p.returncode}, 预期输出原因={cause}")
            assert p.returncode == (0 if case == "ascii-locale-green" else 2) and cause
            assert b"Traceback" not in p.stderr
    finally:
        os.close(wr)


def encoding():
    for loc in ("en_US.UTF-8", "en_US.ISO8859-1", "en_US.US-ASCII"):
        p = run(SRC, CHECK, "--café", env=dict(ENV, LC_ALL=loc))
        print(f"{loc} 错误选项: rc={p.returncode} stderr 尾={p.stderr.splitlines()[-1].split(b': ')[-1]!r}")
    for label, args in (("坏选项", [b"--\xff"]), ("坏版本", ["--rev", b"nope-\xff"]),
                        ("不存在的根", ["--root", b"/no-such-root-\xff"])):
        p = run(SRC, CHECK, *args)
        print(f"原始 ff {label}: rc={p.returncode} stderr 含裸 ff={b'\xff' in p.stderr} 含回溯={b'Traceback' in p.stderr}")
        assert p.returncode == 2 and b"Traceback" not in p.stderr

    repo = project(box())
    name = A.encode() + b"/raw-\xff.md"
    oid = git(repo, "rev-parse", f"HEAD:{A}/SPEC.md").strip()
    git(repo, "update-index", "--add", "--cacheinfo", b"100644," + oid + b"," + name)
    git(repo, "commit", "-qm", "raw byte filename in tree")
    raw = run(repo, CHECK, "--print-pin")
    checked = run(repo, CHECK)
    try:
        raw.stdout.decode("utf-8")
        valid = True
    except UnicodeDecodeError:
        valid = False
    print(f"原始 ff 路径: 普通检查 rc={checked.returncode}; 打印钉选 rc={raw.returncode}; "
          f"含原路径={name + b'\n' in raw.stdout}; 合法 UTF-8={valid}")
    assert checked.returncode == 1 and checked.stderr.startswith(b"RED ")
    assert raw.returncode == 0 and name + b"\n" in raw.stdout and not valid


if __name__ == "__main__":
    {"status": status, "locale": locale_cases, "parser": parser, "encoding": encoding,
     "four": four}[sys.argv[1]]()
