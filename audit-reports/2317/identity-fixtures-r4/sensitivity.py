"""投影同一提交；自测文件不改，每次从原检查器只撤一个判断或更换输出实现。"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CHECK, ENV, SELF, box, project, run

MUTATIONS = [
    ("目录", "if dirs != need:", "if False:", {"empty-subtree-admit", "empty-subtree-corpus"}),
    ("模式", 'elif typ == "blob" and mode == "100644":', 'elif typ == "blob":', {"exec-bit", "symlink-same-content"}),
    ("指纹", "if fp != CORPUS_BASELINE:", "if False:", {"corpus-byte", "corpus-extra-file"}),
    ("钉选", "if pin_text(admit) != pinned:", "if False:",
     {"pin-comment-line", "table-byte", "extra-tracked", "tracked-in-pycache", "delete-file"}),
]

repo = project(box())
checker = repo / CHECK
original = checker.read_text()
start = original.index("    if isinstance(data, str):", original.index("def emit("))
end = original.index("\n\ndef note(", start)
# 保持 bytes 的成功路径逐字节相同；只改回 R3 使用的 Python 文本/缓冲二层。
buffered = '''    if isinstance(data, str):
        print(data, file=sys.stdout if fd == 1 else sys.stderr)
    else:
        sys.stdout.buffer.write(data)

'''
MUTATIONS.append(("print/缓冲", original[start:end], buffered, None))
for label, old, new, expected in MUTATIONS:
    if sys.argv[1:] == ["output"] and expected is not None:
        continue
    assert original.count(old) == 1
    checker.write_text(original.replace(old, new))
    p = run(repo, SELF)
    lines = p.stdout.decode().splitlines()
    failed = [line for line in lines if line.startswith("FAIL")]
    print(label, *failed, *lines[-1:], f"自测退出 {p.returncode}", sep="\n", flush=True)
    assert p.returncode == 1 and failed, (p.stdout, p.stderr)
    actual = {line.split()[1] for line in failed}
    if expected is None:
        assert {"ascii-locale-green", "print-pin-broken-pipe"} <= actual
        for loc in ("C", "en_US.UTF-8"):
            rd, wr = os.pipe()
            os.close(rd)
            try:
                probe = run(repo, "-X", "utf8=0", CHECK, env=dict(ENV, LC_ALL=loc), stdout=wr)
            finally:
                os.close(wr)
            print(f"文本弱化 / {loc} / GREEN 断管: rc={probe.returncode}, stderr={probe.stderr!r}")
            if loc == "C":
                assert probe.returncode == 2 and b"can't encode" in probe.stderr
            else:
                assert probe.returncode == 120 and b"BrokenPipeError" in probe.stderr
    else:
        assert actual == expected
    assert lines[-1] == f"身份检查自测：21 项，不符 {len(failed)}"
