"""参数、描述符和原始字节的独立进程对照。用法：probe.py cli|io|warning。"""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ADMIT, ENV, PIN, REV, checker, git, python, sandbox

repo = sandbox()
script = checker(repo)
# 只移动私有克隆的 HEAD，不检出文件。检验默认版本时也固定到受审提交。
git(repo, "update-ref", "--no-deref", "HEAD", REV)
pin = git(repo, "show", f"{REV}:{PIN}")
green = b"GATE11 "


def run(*args, cwd=repo, locale="C", **kwargs):
    env = dict(ENV, LC_ALL=locale, LANG=locale)
    return python(cwd, "-X", "utf8=0", script, *args, env=env, **kwargs)


@contextmanager
def broken_pipe():
    rd, wr = os.pipe()
    os.close(rd)
    try:
        yield wr
    finally:
        os.close(wr)


def role(p):
    if p.stdout == pin:
        return "PIN"
    if p.stdout.startswith(green) and b"GREEN" in p.stdout:
        return "GREEN"
    assert p.stdout == b"", p.stdout[:100]
    if "参数无效".encode() in p.stderr:
        return "参数"
    if "无法运行".encode() in p.stderr:
        return "运行"
    if p.stderr.startswith(b"RED "):
        return "RED"
    raise AssertionError(p.stderr)


def cli():
    (repo / "--actual").symlink_to(repo, target_is_directory=True)
    cases = [
        ([], 0, "GREEN"),
        (["--rev", "nope", "--rev", "HEAD"], 0, "GREEN"),
        (["--rev", "HEAD", "--rev", "nope"], 2, "运行"),
        (["--root", "missing", "--root", "."], 0, "GREEN"),
        (["--root", ".", "--root", "missing"], 2, "运行"),
        (["--print-pin", "--print-pin"], 0, "PIN"),
        (["--root", "--actual"], 0, "GREEN"),
        (["--root", "--print-pin"], 2, "运行"),
        (["--rev", "--print-pin"], 2, "运行"),
        (["--root", ""], 0, "GREEN"),
        (["--rev", ""], 2, "运行"),
        (["--rev=X"], 2, "参数"),
        (["--rev=HEAD"], 2, "参数"),
        (["--root=."], 2, "参数"),
        (["--print-pin=x"], 2, "参数"),
        (["--print-pi"], 2, "参数"),
        (["--bogus"], 2, "参数"),
        (["--", "HEAD"], 2, "参数"),
        ([""], 2, "参数"),
        (["--rev"], 2, "参数"),
        (["--root"], 2, "参数"),
        (["--print-pin", "extra"], 2, "参数"),
    ]
    for args, code, want in cases:
        p = run(*args)
        got = role(p)
        print(f"{args!r}: rc={p.returncode} {got}")
        assert (p.returncode, got) == (code, want)
    p = run("--root", "", cwd=repo.parent)
    print(f"仓库外 --root '': rc={p.returncode} {role(p)}")
    assert (p.returncode, role(p)) == (2, "运行")
    # 阴性对照：加一条普通准入记录但不更新钉选，不改任何门禁文件。
    changed = changed_admit(b"r5-extra")
    p = run("--rev", changed)
    aux = run("--print-pin", "--rev", changed)
    print(f"同一变更：普通检查 rc={p.returncode} {role(p)}；打印 rc={aux.returncode} 新路径在清单中={b'r5-extra' in aux.stdout}")
    assert (p.returncode, role(p)) == (1, "RED")
    assert aux.returncode == 0 and b"r5-extra" in aux.stdout and b"GREEN" not in aux.stdout


def changed_admit(name):
    git(repo, "read-tree", REV)
    oid = git(repo, "rev-parse", f"{REV}:{ADMIT}/SPEC.md").strip()
    git(repo, "update-index", "-z", "--index-info",
        data=b"100644 " + oid + b"\t" + ADMIT.encode() + b"/" + name + b"\0")
    tree = git(repo, "write-tree").decode().strip()
    return git(repo, "commit-tree", tree, "-p", REV, "-m", "准入多一项").decode().strip()


def io():
    bad = run("--bogus")
    with broken_pipe() as pipe, open(os.devnull, "rb") as ro:
        for name, fd in [("正常", None), ("断管", pipe), ("只读", ro)]:
            p = bad if fd is None else run("--bogus", stderr=fd)
            print(f"坏选项 / stderr {name}: rc={p.returncode} stdout={p.stdout!r}")
            assert p.returncode == 2 and p.stdout == b""
        for args in [(), ("--print-pin",)]:
            p = run(*args, locale="C.UTF-8", stdout=pipe)
            print(f"{args} / stdout 断管: rc={p.returncode} {p.stderr.decode().strip()}")
            assert p.returncode == 2 and b"Broken pipe" in p.stderr
    for loc in ("C", "C.UTF-8"):
        p = python(repo, "-X", "utf8=0", "-c", "import sys;print(sys.stdout.encoding)", env=dict(ENV, LC_ALL=loc, LANG=loc))
        print(f"{loc} / stdout 文本编码={p.stdout.decode().strip()}")
    g = run()
    print(f"ASCII 正例: rc={g.returncode} {g.stdout.decode().strip()}")
    assert g.returncode == 0 and "身份检查 GREEN" in g.stdout.decode()
    for args, reason in [(("--rev", "nope"), b"rev-parse"), (("--bogus",), "参数无效".encode()),
                         (("--print-pi",), "参数无效".encode()), (("--rev",), "参数无效".encode())]:
        p = run(*args)
        print(f"{args}: rc={p.returncode} {p.stderr.decode().strip().splitlines()[-1]}")
        assert p.returncode == 2 and reason in p.stderr and p.stdout == b""
    for loc in ("en_US.UTF-8", "en_US.ISO8859-1"):
        # macOS 以 UTF-8 解码 argv，与标准流的 locale 编码分开。
        p = run("--café".encode("utf-8"), locale=loc)
        print(f"{loc} 坏选项: rc={p.returncode} UTF-8诊断={p.stderr.decode().strip()}")
        assert p.returncode == 2 and p.stderr.decode().endswith("--café\n")
    p = run("--root", b"r5-missing-\xff")
    raw_git = subprocess.run(["git", "-C", b"r5-missing-\xff", "rev-parse", "--verify", "HEAD^{commit}"],
                             cwd=repo, env=dict(ENV, LC_ALL="C"), capture_output=True)
    assert raw_git.returncode and b"\xff" in raw_git.stderr
    assert p.returncode == 2 and p.stderr.startswith(raw_git.stderr)
    assert b"\\udcff" in p.stderr[len(raw_git.stderr):]
    print("坏根：rc=2；Git 诊断逐字节相同且含裸 ff；检查器自己的诊断转义该字节")
    rev = changed_admit(b"r5-\xff")
    red, raw = run("--rev", rev), run("--print-pin", "--rev", rev)
    assert red.returncode == 1 and red.stderr.decode().startswith("RED ")
    assert raw.returncode == 0 and b"/r5-\xff\n" in raw.stdout
    print("原始文件名：普通检查 rc=1，UTF-8 RED；打印 rc=0，钉选含裸 ff")


def warning():
    # 合法的分支和标签指向同一对象：触发 Git 警告，不改变选中的提交。
    ref = "r5-same"
    git(repo, "config", "core.warnAmbiguousRefs", "true")
    git(repo, "branch", ref, REV)
    git(repo, "tag", ref, REV)
    with broken_pipe() as pipe:
        for label, rev, fd in [("警告可写", ref, subprocess.PIPE),
                               ("警告断管", ref, pipe), ("完整提交号、同一断管", REV, pipe)]:
            p = run("--rev", rev, stderr=fd)
            print(f"{label}: rc={p.returncode} GREEN={b'GREEN' in p.stdout}")
            if p.stderr:
                print(p.stderr.decode().strip())
        args = ["git", "rev-parse", "--verify", ref + "^{commit}"]
        p = subprocess.run(args, cwd=repo, env=dict(ENV, LC_ALL="C"), stderr=pipe,
                           stdout=subprocess.PIPE)
        print(f"直接调用 git / 警告断管: rc={p.returncode}")


if __name__ == "__main__":
    {"cli": cli, "io": io, "warning": warning}[sys.argv[1]]()
