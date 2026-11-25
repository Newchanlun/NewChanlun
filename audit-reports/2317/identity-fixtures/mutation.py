"""对自测做变异测试：每次只在临时的小仓库中变异一个判断。"""
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_repo import CHECK, G, run, seed, tmp_parent


def main():
    temp = Path(tempfile.mkdtemp(dir=tmp_parent()))
    variants = [
        ("mode", 'if mode != "100644" or typ != "blob":', "if False:",
         {"symlink-same-content", "exec-bit"}),
        ("disk", "if not a.no_worktree:", "if False:",
         {"dirty-table", "dirty-untracked-pycache", "dirty-symlink", "dirty-corpus",
          "dirty-delete", "git-replace-object"}),
        ("fingerprint", "if fp != CORPUS_BASELINE:", "if False:", {"corpus-byte", "corpus-extra-file"}),
    ]
    for label, old, new, expected in variants:
        repo = temp / label
        seed(Path.cwd(), repo)
        script = repo / CHECK
        src = script.read_text()
        assert src.count(old) == 1
        script.write_text(src.replace(old, new))
        p = run(repo, sys.executable, "-I", G+"/selftest_identity.py", check=False)
        lines = p.stdout.decode().splitlines()
        fails = {l.split()[1] for l in lines if l.startswith("FAIL")}
        print(label, p.returncode, sorted(fails), flush=True)
        if p.returncode != 1 or fails != expected:
            raise RuntimeError((lines, p.stderr.decode()))
        for line in lines:
            if line.startswith("FAIL") or line.startswith("身份检查自测"):
                print(line, flush=True)


if __name__ == "__main__":
    main()
