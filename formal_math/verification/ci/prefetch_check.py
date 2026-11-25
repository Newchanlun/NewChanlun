#!/usr/bin/env python3
"""联网取依赖之前的边界检查（#2315 CI 草稿）。

取依赖这一步（`lake exe cache get`）有网络，也会让 Lake 读 PR 里的 `lakefile.toml`、克隆其中
`require` 的仓库并加载被克隆仓库的配置。所以在任何 `lake` 命令之前先确认：

1. 门 1（钉选）：工具链与 manifest 的九个包、来源都等于 `pins.json`。直接调用 #2312 的 `gate1`。
2. 门 2 的 lakefile 白名单部分（不构建）：调用 #2312 的 `lakefile_whitelist`，含「不许 lakefile.lean」。
3. 本脚本补的一条：`lakefile.toml` 的每个 `require` 必须是 manifest 里的直接依赖，git 地址与
   `inputRev` 一致；manifest 的 `packagesDir`、`lakeDir` 必须是默认值。门 1 只看 manifest，
   不看 lakefile；PR 若在 lakefile 里加一个 manifest 没有的 `require`，取依赖时 Lake 会去克隆它。

退出码：0 通过，1 红，2 无法判定。只读文件，不运行 Lake。
"""
import argparse
import json
import sys
import tomllib
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    root = parser.parse_args().repo_root.resolve()
    sys.path.insert(0, str(root / "formal_math/verification"))
    import run_gates  # noqa: E402  #2312 的门禁实现，只调用、不修改

    fm = root / "formal_math"
    try:
        failed = run_gates.gate1(root) != 0
    except run_gates.Undetermined as exc:
        print(f"PREFETCH: 门 1 无法判定：{exc}", file=sys.stderr)
        return 2
    try:
        package = tomllib.loads((fm / "lakefile.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"PREFETCH RED formal_math/lakefile.toml:1 LAKEFILE_KEY 无法解析：{exc}")
        return 1
    failed |= bool(run_gates.lakefile_whitelist(root, package))

    manifest = json.loads((fm / "lake-manifest.json").read_text())
    for key, want in (("packagesDir", ".lake/packages"), ("lakeDir", ".lake")):
        if manifest.get(key, want) != want:
            print(f"PREFETCH RED formal_math/lake-manifest.json:{key} MANIFEST_DIR 须为 {want}")
            failed = True
    direct = {p["name"]: p for p in manifest.get("packages", []) if not p.get("inherited")}
    for req in package.get("require", []):
        name = req.get("name") if isinstance(req, dict) else None
        entry = direct.get(name)
        if entry is None:
            print(f"PREFETCH RED formal_math/lakefile.toml:{name} REQUIRE_UNPINNED manifest 里没有这个直接依赖")
            failed = True
            continue
        if req.get("git") != entry.get("url") or req.get("rev") != entry.get("inputRev"):
            print(f"PREFETCH RED formal_math/lakefile.toml:{name} REQUIRE_UNPINNED "
                  f"git/rev 须等于 manifest 的 {entry.get('url')} @ {entry.get('inputRev')}")
            failed = True
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
