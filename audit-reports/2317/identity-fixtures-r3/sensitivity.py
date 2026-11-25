"""固定对象输入，每次只替换临时副本中的一个判断，原自测不作修改。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CHECK, SELF, box, project, run

MUTATIONS = [
    ("目录节点", "if dirs != need:", "if False:", {"empty-subtree-corpus", "empty-subtree-admit"}),
    ("Git 模式", 'elif typ == "blob" and mode == "100644":', 'elif typ == "blob":',
     {"exec-bit", "symlink-same-content"}),
    ("指纹比较", "if fp != CORPUS_BASELINE:", "if False:", {"corpus-byte", "corpus-extra-file"}),
    ("钉选比对", "if pin_text(admit) != pinned:", "if False:",
     {"table-byte", "tracked-in-pycache", "extra-tracked", "delete-file", "pin-comment-line"}),
]


def main():
    repo = project(box())
    checker = repo / CHECK
    original = checker.read_text()
    for label, before, after, expected in MUTATIONS:
        assert original.count(before) == 1
        checker.write_text(original.replace(before, after))
        p = run(repo, sys.executable, "-IB", SELF)
        lines = p.stdout.decode().splitlines()
        failed = [line for line in lines if line.startswith("FAIL")]
        print(label, *failed, *lines[-1:], f"自测退出 {p.returncode}", sep="\n", flush=True)
        assert p.returncode == 1 and {line.split()[1] for line in failed} == expected, p.stderr
        assert lines[-1] == f"身份检查自测：17 项，不符 {len(expected)}"
    checker.write_text(original)


if __name__ == "__main__":
    main()
