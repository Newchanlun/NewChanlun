"""复查两项原约定的必红样本；链接目标放在两处受审目录以外。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_repo import A, CHECK, G, first, gate, git, seed, tmp_parent

tmp = Path(tempfile.mkdtemp(dir=tmp_parent()))
for label, reason in (("link", "非普通文件：120000"), ("pycache", "与钉选")):
    repo = tmp/label
    seed(Path.cwd(), repo)
    baseline = git(repo, "rev-parse", "HEAD").strip()
    if label == "link":
        original = repo/A/"SPEC.md"
        target = repo/"review-copy"
        original.rename(target)
        original.symlink_to(os.path.relpath(target, original.parent))
        assert original.read_bytes() == git(repo, "show", "HEAD:"+A+"/SPEC.md")
    else:
        folder = repo/A/"__pycache__"
        folder.mkdir()
        (folder/"errata.jsonl").write_text("{}\n")
    git(repo, "add", "-f", "-A", ".")
    git(repo, "commit", "-qm", label)
    assert not git(repo, "diff", baseline, "HEAD", "--", G)
    p = gate(repo/CHECK, repo)
    print(label, p.returncode, first(p))
    assert p.returncode == 1 and reason in first(p)
