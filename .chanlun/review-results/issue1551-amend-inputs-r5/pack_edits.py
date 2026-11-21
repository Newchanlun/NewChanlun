import difflib
import json
from pathlib import Path
import re
import subprocess
import sys

base = "6ba72e84c55aa6d65b11cc46b7288142f4fce62b"
candidate = sys.argv[1]
out = Path(sys.argv[2])
targets = [
    "docs/adr/0064-at18-whole-graph-acceptance-and-closeout.md",
    ".sandcastle/docs/graph-engineering.md",
]

def git(*args):
    return subprocess.check_output(["git", *args])

def encode(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)

def render(target):
    a, b = (git("show", f"{ref}:{target}").decode() for ref in (base, candidate))
    old, new = a.splitlines(keepends=True), b.splitlines(keepends=True)
    replacements = []
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for group in matcher.get_grouped_opcodes(n=2):
        _, i, _, j, _ = group[0]
        _, _, k, _, l = group[-1]
        before = "".join(old[i:k])
        after = "".join(new[j:l])
        if not before or a.count(before) != 1:
            raise ValueError(f"nonunique anchor: {target}:{i + 1}")
        replacements.append({"before": before, "after": after})
        a = a.replace(before, after, 1)
    if a.encode() != git("show", f"{candidate}:{target}"):
        raise ValueError(f"edit replay does not reconstruct {target}")
    print(f"{target}: {len(replacements)} unique replacements, {len(a.encode())} bytes, equal")
    return {"version": 1, "operation": "edit", "path": target, "replacements": replacements}

actual = git("diff", "--name-only", base, candidate).decode().splitlines()
assert sorted(actual) == sorted(targets), actual
primary, sync = map(render, targets)
contract = {"source_commit": base, "candidate_commit": candidate, "primary": primary, "sync": [sync]}
(out / "canonical_edit.json").write_text(encode(contract) + "\n")
draft = (out / "draft-body.md").read_text().rstrip()
tick = chr(96)
fence = tick * 3
draft += f"\n\n候选提交：{tick}{candidate}{tick}。\n\n"
draft += fence + "canonical_edit\n" + encode(primary) + "\n" + fence + "\n"
(out / "draft.md").write_text(draft)
assert json.loads(re.search(r"(?ms)^" + fence + r"canonical_edit\n(.*?)\n" + fence + "$", draft)[1]) == primary
