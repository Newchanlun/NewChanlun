#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R4：独立规格预言机（differential oracle）随机对拍测试。

按 README.md 规则独立计算期望结论，随机生成 120 组 (base, head, branch, approved) 对拍 precheck.py，
核查零误绿、零误红、退出码一致。

用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I fuzz_oracle.py [--precheck PATH]
"""
import argparse
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_PRECHECK = os.path.join(ROOT, "formal_math", "verification", "precheck", "precheck.py")
GENV = {
    "PATH": os.environ.get("PATH", os.defpath),
    "LC_ALL": "C",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "r",
    "GIT_AUTHOR_EMAIL": "r@r",
    "GIT_COMMITTER_NAME": "r",
    "GIT_COMMITTER_EMAIL": "r@r",
    "GIT_AUTHOR_DATE": "@0 +0000",
    "GIT_COMMITTER_DATE": "@0 +0000",
}
RUN_ENV = {"PATH": GENV["PATH"], "LC_ALL": "C.UTF-8"}

ROLE_PREFIXES = {
    "decl": ("formal_math/Chan/Defs/", "formal_math/Chan/Hypotheses/", "formal_math/Chan/Audit/Literal/",
             "formal_math/Chan/Proxy/", "formal_math/ChanChallenge/", "formal_math/sources/",
             "formal_math/blueprint/", "formal_math/statement-lock.json", "formal_math/formalization.yaml",
             "formal_math/garbage-signoffs.yaml", "formal_math/HISTORY.md"),
    "proof": ("formal_math/Chan/Thm/", "formal_math/Chan/Proofs/", "formal_math/Chan/Exec/",
              "formal_math/Chan/Final/", "formal_math/Chan/Final.lean", "formal_math/Chan.lean",
              "formal_math/ChanTest/", "formal_math/ChanDyn/", "formal_math/ChanExplore/",
              "formal_math/ChanExplore.lean"),
    "audit": ("formal_math/Chan/Audit/Math/", "formal_math/Chan/Audit/Separation/",
              "formal_math/Chan/Audit/Cases/", "formal_math/ChanTest/"),
    "infra": ("formal_math/lakefile.toml", "formal_math/lake-manifest.json", "formal_math/lean-toolchain",
              "scripts/fm_env.sh", ".github/workflows/formal-math.yml", "formal_math/.gitignore",
              "formal_math/verification/", "formal_math/README.md"),
}
TRUSTED_FILES = {"formal_math/lakefile.toml", "formal_math/lake-manifest.json", "formal_math/lean-toolchain",
                 "scripts/fm_env.sh", ".github/workflows/formal-math.yml", "formal_math/.gitignore"}
ANCESTORS = {"scripts", ".github", ".github/workflows"}


def git(repo, *args, data=None):
    return subprocess.run(["git", "-C", repo, *args], input=data, env=GENV, capture_output=True, check=True).stdout


def blob(repo, data):
    return git(repo, "hash-object", "-w", "--stdin", data=data).strip()


def mktree(repo, entries):
    return git(repo, "mktree", "-z", "--missing", data=b"".join(b"%s %s %s\t%s\0" % e for e in entries)).strip()


def commit_tree(repo, tree_oid, parents=()):
    args = ["commit-tree", tree_oid.decode(), "-m", "c"]
    for p in parents:
        args += ["-p", p]
    return git(repo, *args).strip().decode()


def build_tree(repo, files):
    spec = {}
    for path, val in files.items():
        node, parts = spec, path.encode().split(b"/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = val

    def rec(d):
        items = []
        for name, val in d.items():
            if isinstance(val, dict):
                items.append((b"040000", b"tree", rec(val), name))
            else:
                mode, content = val
                if mode == b"160000":
                    items.append((b"160000", b"commit", content, name))
                else:
                    items.append((mode, b"blob", blob(repo, content), name))
        return mktree(repo, items)

    return rec(spec)


def is_managed_file(p):
    return p.startswith("formal_math/") or p in ("scripts/fm_env.sh", ".github/workflows/formal-math.yml")


def file_allowed_for_role(p, role):
    return any(p.startswith(r) if r.endswith("/") else p == r for r in ROLE_PREFIXES[role])


def oracle_should_be_green(base_files, head_files, branch, approved):
    m = re.fullmatch(r"(decl|proof|audit|infra)/[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*(?:/[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*)*", branch)
    role = m.group(1) if m else None

    for p, (mode, _) in head_files.items():
        if is_managed_file(p):
            if mode != b"100644":
                return False
            if p == "formal_math/.gitignore":
                return False
            if p.startswith("formal_math/"):
                base_name = p.rsplit("/", 1)[-1].lower()
                if base_name in ("lakefile.toml", "lakefile.lean", "lake-manifest.json", "lean-toolchain", ".lake"):
                    if p not in ("formal_math/lakefile.toml", "formal_math/lake-manifest.json", "formal_math/lean-toolchain",
                                 "formal_math/verification/auditor/lakefile.toml",
                                 "formal_math/verification/auditor/lake-manifest.json",
                                 "formal_math/verification/auditor/lean-toolchain"):
                        return False
        if p in ANCESTORS or p == "formal_math":
            return False

    changed_managed = [p for p in set(base_files) | set(head_files) if is_managed_file(p) and base_files.get(p) != head_files.get(p)]
    if not changed_managed:
        return True
    if role is None:
        return False
    for p in changed_managed:
        if not file_allowed_for_role(p, role):
            return False
    if role == "infra" and not approved:
        if any(p in TRUSTED_FILES or p.startswith("formal_math/verification/") for p in changed_managed):
            return False
    if role != "infra":
        if any(p in TRUSTED_FILES or p.startswith("formal_math/verification/") for p in changed_managed):
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--precheck", default=DEFAULT_PRECHECK)
    ns = ap.parse_args()
    rng = random.Random(23120004)
    tmp = tempfile.mkdtemp(prefix="precheck-r4-fuzz-")
    try:
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        git(repo, "init", "-q")

        pool_paths = [
            "formal_math/Chan/Defs/A.lean",
            "formal_math/Chan/Thm/B.lean",
            "formal_math/Chan/Audit/Math/C.lean",
            "formal_math/ChanTest/T.lean",
            "formal_math/sources/s.md",
            "formal_math/README.md",
            "formal_math/lakefile.toml",
            "formal_math/verification/run_gates.py",
            "formal_math/.gitignore",
            "formal_math/Chan/Thm/lakefile.lean",
            "scripts/fm_env.sh",
            "scripts/other.sh",
            ".github/workflows/formal-math.yml",
            ".github/workflows/ci.yml",
            ".github/README.md",
            "rust/lib.rs",
        ]
        branches = ["main", "", "feature/x", "decl/a", "proof/b", "audit/c", "infra/d"]

        mismatches = 0
        green_cnt = 0
        red_cnt = 0
        for i in range(120):
            base_f = {"rust/lib.rs": (b"100644", b"r0\n")}
            for p in pool_paths:
                if p == "rust/lib.rs":
                    continue
                if rng.random() < 0.45:
                    mode = b"100755" if (rng.random() < 0.05) else b"100644"
                    base_f[p] = (mode, f"b{i}\n".encode())
            head_f = dict(base_f)
            if i % 3 == 0:
                head_f.pop("formal_math/.gitignore", None)
                head_f.pop("formal_math/Chan/Thm/lakefile.lean", None)
                for k in list(head_f):
                    if is_managed_file(k) and head_f[k][0] != b"100644":
                        head_f[k] = (b"100644", head_f[k][1])
                br = rng.choice(branches)
                approved = rng.choice([True, False])
                for up in rng.sample(["scripts/other.sh", ".github/workflows/ci.yml", ".github/README.md", "rust/lib.rs"], rng.randint(1, 3)):
                    if rng.random() < 0.5:
                        head_f[up] = (b"100644", f"u{i}\n".encode())
                    else:
                        head_f.pop(up, None)
                if br.startswith(("decl/", "proof/", "audit/", "infra/")) and rng.random() < 0.6:
                    rname = br.split("/")[0]
                    cand = [p for p in pool_paths if is_managed_file(p) and p not in ("formal_math/.gitignore", "formal_math/Chan/Thm/lakefile.lean") and file_allowed_for_role(p, rname)]
                    if cand:
                        p = rng.choice(cand)
                        if rng.random() < 0.3:
                            head_f.pop(p, None)
                        else:
                            head_f[p] = (b"100644", f"h{i}\n".encode())
            else:
                br = rng.choice(branches)
                approved = rng.choice([True, False])
                for p in rng.sample(pool_paths, rng.randint(1, 4)):
                    act = rng.choice(["mod", "del", "exec", "link", "gitlink"])
                    if act == "del":
                        head_f.pop(p, None)
                    elif act == "mod":
                        head_f[p] = (b"100644", f"m{i}\n".encode())
                    elif act == "exec":
                        head_f[p] = (b"100755", f"e{i}\n".encode())
                    elif act == "link":
                        head_f[p] = (b"120000", b"target")
                    elif act == "gitlink":
                        head_f[p] = (b"160000", b"1" * 40)

            cb = commit_tree(repo, build_tree(repo, base_f))
            ch = commit_tree(repo, build_tree(repo, head_f), [cb])
            argv = ([sys.executable, "-I", ns.precheck]
                    + (["--trusted-change-approved"] if approved else [])
                    + [repo, cb, ch, br])
            proc = subprocess.run(argv, env=RUN_ENV, capture_output=True)
            exp_green = oracle_should_be_green(base_f, head_f, br, approved)
            got_green = (proc.returncode == 0)
            if got_green:
                green_cnt += 1
            else:
                red_cnt += 1
            if got_green != exp_green or proc.returncode not in (0, 1):
                mismatches += 1
                print(f"[MISMATCH #{i}] br={br!r} app={approved} exp_green={exp_green} got_rc={proc.returncode}")
                print(f"  out={proc.stdout.decode('utf-8', 'replace').strip()!r}")
                print(f"  err={proc.stderr.decode('utf-8', 'replace').strip()!r}")
        print(f"FUZZ ORACLE SUMMARY: 120 cases (green={green_cnt}, red={red_cnt}), mismatches={mismatches}")
        return 1 if mismatches else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
