"""只在固定输入的临时投影上做一阶变异，判定原自测是否恰好抓住预期回归。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CHECK, PIN, SELF, box, compact, run

CASES = [
    ("目录节点", "if dirs != need:", "if False:",
     {"empty-subtree-corpus", "empty-subtree-admit"}),
    ("执行位", "if st.st_mode & 0o111:", "if False:", {"dirty-exec-bit"}),
    ("逐级目录", 'for part in prefix.split("/"):', "for part in ():",
     {"dirty-root-symlink", "dirty-parent-symlink"}),
    ("钉选来源", 'git(root, "cat-file", "blob", rev + ":" + PIN_PATH)',
     'open(os.path.join(root, PIN_PATH), "rb").read()', {"pin-checked-out-crlf"}),
]

if __name__ == "__main__":
    c = compact(box())
    p = c / CHECK
    original = p.read_text()
    for label, before, after, expected in CASES:
        assert original.count(before) == 1
        try:
            p.write_text(original.replace(before, after))
            r = run(c, sys.executable, "-IB", SELF)
        finally:
            p.write_text(original)
        lines = r.stdout.decode().splitlines()
        failed = [line for line in lines if line.startswith("FAIL")]
        print(label, "自测退出码", r.returncode, *failed, *lines[-1:], sep="\n", flush=True)
        assert r.returncode == 1 and {line.split()[1] for line in failed} == expected
        assert lines[-1] == f"身份检查自测：24 项，不符 {len(expected)}"
