#!/usr/bin/env python3
"""设计咨询 #2312 的原型：纯静态预检。输入只有两个提交和分支名，只用 git 底层命令，不碰工作树，
不调用 lake 或 lean。退出码 0 绿、1 红、2 无法判定。"""
import re
import subprocess
import sys

FM = "formal_math/"
# 受信面：门禁与构建配置。内容角色不得改；infra 角色只能改这些。
TRUSTED_FILES = {FM + "lakefile.toml", FM + "lake-manifest.json", FM + "lean-toolchain",
                 FM + "README.md", "scripts/fm_env.sh", ".github/workflows/formal-math.yml"}
TRUSTED_DIRS = (FM + "verification/",)
ROLES = {
    "decl": (FM + "Chan/Defs/", FM + "Chan/Hypotheses/", FM + "Chan/Audit/Literal/", FM + "ChanChallenge/",
             FM + "Chan/Proxy/", FM + "sources/", FM + "blueprint/", FM + "statement-lock.json",
             FM + "formalization.yaml", FM + "garbage-signoffs.yaml", FM + "HISTORY.md"),
    "proof": (FM + "Chan/Thm/", FM + "Chan/Proofs/", FM + "Chan/Exec/", FM + "Chan/Final/", FM + "Chan/Final.lean",
              FM + "Chan.lean", FM + "ChanTest/", FM + "ChanDyn/", FM + "ChanExplore/", FM + "ChanExplore.lean"),
    "audit": (FM + "Chan/Audit/Math/", FM + "Chan/Audit/Separation/", FM + "Chan/Audit/Cases/", FM + "ChanTest/"),
    "infra": tuple(sorted(TRUSTED_FILES)) + TRUSTED_DIRS,
}
# formal_math 顶层只许这些名字；内容根下只许 .lean 普通文件。
TOP = {"Chan", "Chan.lean", "ChanTest", "ChanChallenge", "ChanDyn", "ChanExplore", "ChanExplore.lean",
       "verification", "sources", "blueprint", "lakefile.toml", "lake-manifest.json", "lean-toolchain",
       "README.md", "HISTORY.md", "formalization.yaml", "statement-lock.json", "garbage-signoffs.yaml"}
CONTENT_ROOTS = ("Chan/", "ChanTest/", "ChanChallenge/", "ChanDyn/", "ChanExplore/")
SEGMENT = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
BRANCH = re.compile(r"(decl|proof|audit|infra)/[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*")


def git(repo, *args):
    out = subprocess.run(["git", "-C", repo, "-c", "core.quotePath=false", *args], capture_output=True)
    if out.returncode:
        print(f"PREFLIGHT 无法判定：git {' '.join(args)}: {out.stderr.decode(errors='replace').strip()}", file=sys.stderr)
        sys.exit(2)
    return out.stdout.decode("utf-8", errors="surrogateescape")


def within(path, rules):
    return any(path.startswith(r) if r.endswith("/") else path == r for r in rules)


def trusted(path):
    return path in TRUSTED_FILES or within(path, TRUSTED_DIRS)


def main():
    repo, base, head, branch = sys.argv[1:5]
    approved = "--trust-surface-approved" in sys.argv
    reds = []
    if git(repo, "merge-base", base, head).strip() != git(repo, "rev-parse", base).strip():
        print("PREFLIGHT 无法判定：基线不是被审提交的祖先（分支未追平）", file=sys.stderr)
        return 2
    # 1. 改动集合：提交对提交，带文件模式；不看暂存区与工作树。
    fields = git(repo, "diff-tree", "-r", "-z", "--no-renames", "--raw", base, head).split("\0")
    changes = []
    for meta, path in zip(fields[0::2], fields[1::2]):
        _, new_mode, _, _, status = meta.lstrip(":").split(" ")
        changes.append((path, new_mode, status))
    governed = [c for c in changes if c[0].startswith(FM) or trusted(c[0])]
    match = BRANCH.fullmatch(branch)
    role = match.group(1) if match else None
    if governed and role is None:
        reds.append((".git/HEAD", "BRANCH_ROLE", f"分支 {branch!r} 没有 formal_math 角色，却改了受管路径"))
    # 2. 路径权限；受信面与内容互斥。
    if role:
        for path, mode, status in changes:
            if not within(path, ROLES[role]):
                reds.append((path, "PATH_SCOPE", f"{role} 角色不得改此路径（{status}）"))
        if role == "infra" and not approved and any(trusted(p) for p, _, _ in changes):
            reds.append((".git/HEAD", "TRUST_SURFACE", "改了受信面：须走受信面评审并由维护者放行"))
    # 3. 被审提交整棵树的形状不变式（不只看改动）。
    for line in git(repo, "ls-tree", "-r", "-z", head, "--", FM.rstrip("/")).split("\0"):
        if not line:
            continue
        meta, path = line.split("\t", 1)
        mode, kind, _ = meta.split(" ")
        rel = path[len(FM):]
        if mode not in ("100644", "100755") or kind != "blob":
            reds.append((path, "FILE_MODE", f"只许普通文件，实为 {mode} {kind}"))
            continue
        if rel.startswith("verification/"):
            continue  # 受信面内部（含夹具）只查文件模式
        parts = rel.split("/")
        if parts[0] not in TOP:
            reds.append((path, "TREE_SHAPE", f"formal_math 顶层不许出现 {parts[0]}"))
        elif rel.startswith(CONTENT_ROOTS) or rel in ("Chan.lean", "ChanExplore.lean"):
            stem = parts[-1][:-5] if parts[-1].endswith(".lean") else None
            if stem is None or not all(SEGMENT.fullmatch(s) for s in parts[:-1] + [stem]):
                reds.append((path, "TREE_SHAPE", "内容根下只许模块名合法的 .lean 普通文件"))
    # 4. 内容角色：受信面逐个文件与基线同一 blob（与第 2 步互为冗余，不依赖角色表写对）。
    if role != "infra":
        for path in sorted(TRUSTED_FILES):
            a = subprocess.run(["git", "-C", repo, "rev-parse", "-q", "--verify", f"{base}:{path}"], capture_output=True)
            b = subprocess.run(["git", "-C", repo, "rev-parse", "-q", "--verify", f"{head}:{path}"], capture_output=True)
            if a.stdout != b.stdout:
                reds.append((path, "CONFIG_DRIFT", "受信文件与基线不是同一内容"))
        a = subprocess.run(["git", "-C", repo, "rev-parse", "-q", "--verify", f"{base}:{FM}verification"], capture_output=True)
        b = subprocess.run(["git", "-C", repo, "rev-parse", "-q", "--verify", f"{head}:{FM}verification"], capture_output=True)
        if a.stdout != b.stdout:
            reds.append((FM + "verification", "CONFIG_DRIFT", "门禁目录与基线不是同一棵树"))
    for path, code, detail in sorted(set(reds)):
        print(f"PREFLIGHT RED {path} {code} {detail}")
    return 1 if reds else 0


if __name__ == "__main__":
    sys.exit(main())
