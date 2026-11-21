"""从 Git 源 blob 独立重放，直接按字节比较候选，不依赖作者工作树。"""
import json
from pathlib import Path
import re
import subprocess
import sys

def git(*args):
    return subprocess.check_output(["git", *args])

candidate = sys.argv[1]
folder = Path(__file__).resolve().parent
plan = json.loads((folder / "canonical-plan.json").read_bytes())
edit = json.loads((folder / "canonical-edit.json").read_bytes())
assert plan["edit"] == edit
draft = (folder / "draft.md").read_text()
fences = re.findall(r"(?m)^\x60{3}canonical_edit\s*\n([\s\S]*?)^\x60{3}\s*$", draft)
assert len(fences) == 1 and json.loads(fences[0]) == edit
assert edit["operation"] == "edit"
path = edit["path"]
base = plan["sourceCommit"]
assert git("rev-parse", f"{candidate}^").strip().decode() == base
assert git("diff-tree", "--no-commit-id", "--name-status", "-r", candidate).decode() == f"M\t{path}\n"
original = git("show", f"{base}:{path}")
assert plan["before"].encode() == original
out = original
for step in edit["replacements"]:
    old, new = step["before"].encode(), step["after"].encode()
    assert old and out.count(old) == 1
    out = out.replace(old, new, 1)
assert out.startswith(original) and len(out) > len(original)
assert out == plan["after"].encode() == git("show", f"{candidate}:{path}")
assert git("diff", "--no-color", "--no-ext-diff", base, candidate, "--", path) == (folder / "candidate.diff").read_bytes()
subprocess.run(["git", "diff", "--check", base, candidate], check=True)
print(f"PASS: unique append-only target, exact source and candidate blob, exact candidate diff ({candidate})")
