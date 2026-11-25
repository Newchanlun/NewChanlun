"""每次只改私有副本中的一处实现；不符必须落在预期的用例上。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ADMIT, BLOG, CHECK, ENV, PIN, REV, SELF, git, python, sandbox

repo = sandbox()
paths = [ADMIT, BLOG, CHECK, SELF, PIN, ".gitattributes"]
git(repo, "config", "core.autocrlf", "false")
git(repo, "restore", "--source=" + REV, "--staged", "--worktree", "--", *paths)
tree = git(repo, "write-tree").decode().strip()
projection = git(repo, "commit-tree", tree, "-m", "审查投影").decode().strip()
git(repo, "update-ref", "HEAD", projection)
assert git(repo, "ls-tree", "HEAD", *paths) == git(repo, "ls-tree", REV, *paths)
check, selftest = repo / CHECK, repo / SELF
original = check.read_text(encoding="utf-8")
text_output = '''    if isinstance(data, str):
        print(data, file=sys.stdout if fd == 1 else sys.stderr)
    else:
        sys.stdout.buffer.write(data)
'''
start = original.index("    if isinstance(data, str):", original.index("def emit("))
end = original.index("\n\ndef note(", start)
cases = [
    ("原样", None, None, set()),
    ("目录", "if dirs != need:", "if False:", {"empty-subtree-corpus", "empty-subtree-admit"}),
    ("模式", 'elif typ == "blob" and mode == "100644":', 'elif typ == "blob":',
     {"exec-bit", "symlink-same-content"}),
    ("指纹", "if fp != CORPUS_BASELINE:", "if False:", {"corpus-byte", "corpus-extra-file"}),
    ("钉选", "if pin_text(admit) != pinned:", "if False:",
     {"table-byte", "tracked-in-pycache", "extra-tracked", "delete-file", "pin-comment-line"}),
    ("检查器退回文本和缓冲输出", original[start:end], text_output,
     {"ascii-locale-green", "stdout-broken-pipe", "print-pin-broken-pipe"}),
]
for name, old, new, expected in cases:
    if old is not None:
        assert original.count(old) == 1
        check.write_text(original.replace(old, new), encoding="utf-8")
    result = python(repo, SELF)
    lines = result.stdout.decode().splitlines()
    failed = {line.split()[1] for line in lines if line.startswith("FAIL ")}
    summary = lines[-1] if lines else "(无输出)"
    print(f"{name}：rc={result.returncode}；{summary}；{' '.join(sorted(failed))}", flush=True)
    assert (result.returncode, failed) == (int(bool(expected)), expected), (lines, result.stderr)
    assert summary == f"身份检查自测：24 项，不符 {len(expected)}"

# 区分两种 print 回退：此处恢复检查器，只动自测自己的 say。
check.write_text(original, encoding="utf-8")
source = selftest.read_text(encoding="utf-8")
start, end = source.index("def say(text):"), source.index("def sh(")
selftest.write_text(source[:start] + "def say(text):\n    print(text)\n\n\n" + source[end:], encoding="utf-8")
result = python(repo, "-X", "utf8=0", SELF, env=dict(ENV, LC_ALL="C", LANG="C"))
print(f"仅自测改回 print：rc={result.returncode}；{result.stderr.decode().splitlines()[-1]}", flush=True)
assert result.returncode == 1 and b"UnicodeEncodeError" in result.stderr
assert b"pin-checked-out-crlf" in result.stdout and b"24 " not in result.stdout
