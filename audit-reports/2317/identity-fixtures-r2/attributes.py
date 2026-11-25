"""分别测钉选和数据的检出转换；LFS 只使用夹具的本地对象库。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PIN, SPEC, box, commit, compact, gate, git, summary

def report(c, target, label, previous):
    now = git(c, "cat-file", "blob", "HEAD:" + target)
    print(label, "数据对象未变=", now == previous, "磁盘同对象=", (c / target).read_bytes() == now,
          "status=", git(c, "status", "--porcelain").strip())
    summary("默认", gate(c))
    summary("仅核提交", gate(c, "--no-worktree"))

if __name__ == "__main__":
    d = box()
    c = compact(d)
    rules = c / ".gitattributes"
    base = rules.read_text()
    for i, (label, target, attr) in enumerate((
            ("钉选 CRLF", PIN, "text eol=crlf"),
            ("钉选 UTF-16", PIN, "working-tree-encoding=UTF-16"),
            ("数据 CRLF", SPEC, "text eol=crlf"),
            ("数据 UTF-16", SPEC, "working-tree-encoding=UTF-16"),
            ("数据 filter", SPEC, "filter=r2"),
            ("数据 ident", SPEC, "ident"))):
        before = git(c, "cat-file", "blob", "HEAD:" + target)
        rules.write_text(base + "\n" + target + " " + attr + "\n")
        git(c, "add", "--", ".gitattributes")
        commit(c)
        checkout = d / ("checkout-" + str(i))
        options = []
        if attr == "filter=r2":
            options = ["-c", "filter.r2.clean=sed '1d'", "-c",
                       "filter.r2.smudge=sed '1i\\\nreview-header\n'"]
        git(d, "clone", "-q", "--shared", *options, c, checkout)
        assert ((checkout / target).read_bytes() == before) == (attr == "ident")
        assert not git(checkout, "status", "--porcelain")
        report(checkout, target, label, before)
    # 建立本地仓库自己的 LFS 缓存，避免外部下载。
    before = git(c, "cat-file", "blob", "HEAD:" + SPEC)
    git(c, "lfs", "install", "--local", "--skip-repo")
    git(c, "config", "lfs.storage", str(d / "local-lfs"))
    rules.write_text(base + "\n" + SPEC + " filter=lfs diff=lfs merge=lfs -text\n")
    git(c, "add", "--", ".gitattributes")
    git(c, "add", "--renormalize", "--", SPEC)
    commit(c)
    (c / SPEC).rename(d / "pre-lfs")
    git(c, "checkout-index", "--", SPEC)
    assert git(c, "cat-file", "blob", "HEAD:" + SPEC).startswith(b"version https://git-lfs.github.com/spec/v1\n")
    assert (c / SPEC).read_bytes() == before
    report(c, SPEC, "数据迁移为 LFS 指针", before)
