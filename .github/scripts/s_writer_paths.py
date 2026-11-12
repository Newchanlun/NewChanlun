#!/usr/bin/env python3
"""#1855：判定改动文件里哪些属于 S 写者路径（ci.yml `changes` 的 s_writer，决定四条 W2 冷锁是否随 PR 跑）。

用法：s_writer_paths.py <改动文件清单> [仓根]
  清单每行一个仓内路径；打印其中属于 S 写者路径的行，没有就什么也不打印。

S 写者路径由两部分组成：
1. 静态集合：rust/ 下除去 S 写者不引用的部分，再加锁读取的 s_session 目录、Rust 作业 setup action、
   cargo 遥测包装脚本（及它调用的 EACCES 重试脚本）和冷锁 workflow。不引用的部分：其它 bin（s_structure_session 只经 #[path] 引入
   s_session_v2/、s_session_v3/）、六个库模块（从 bin 的 newchan_rust:: 与库内 crate::/super:: 引用求闭包，
   2026-11-09 实算）、rust/tests 下 fixtures 以外的文件。新增的库模块默认算在内。
2. 派生集合：扫描静态集合内的 Rust 源码，取 `#[path = ".."]`、`include_str!/include_bytes!("..")` 和
   字符串字面量（覆盖经 env!("CARGO_MANIFEST_DIR") 拼出的路径）所指的仓内文件。字面量依次按所在文件目录、
   rust/、仓根、s_session/ 解析，解析到被跟踪文件即计入。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

WRITER_BIN = re.compile(r"^rust/src/bin/(s_structure_session\.rs$|s_session_v2/|s_session_v3/)")
OTHER_BIN = re.compile(r"^rust/src/bin/")
UNREFERENCED_LIB = re.compile(
    r"^rust/src/(bi_zhongshu_bsp|c_segment_verify|diagnostic_fill|economic_session|lav_seal|"
    r"segment_tangency_tests)(\.rs$|/)"
)
RUST_TESTS = re.compile(r"^rust/tests/")
RUST_TEST_FIXTURES = re.compile(r"^rust/tests/fixtures/")
STATIC = re.compile(
    r"^(rust/|s_session/(catalog|profiles|contracts|tests|inputs)/|\.github/actions/rust-job-setup/|"
    r"\.github/scripts/(run-cargo-with-telemetry|cargo-eacces-retry)\.sh$|\.github/workflows/w2-cold-locks\.yml$)"
)
LITERAL = re.compile(r'"((?:[^"\\\n]|\\.)*)"')


def static_hit(path: str) -> bool:
    if WRITER_BIN.match(path):
        return True
    if OTHER_BIN.match(path) or UNREFERENCED_LIB.match(path):
        return False
    if RUST_TESTS.match(path) and not RUST_TEST_FIXTURES.match(path):
        return False
    return bool(STATIC.match(path))


def tracked_files(root: Path) -> set[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    return {p for p in out.decode().split("\0") if p}


def derived_paths(root: Path, tracked: set[str]) -> dict[str, str]:
    """{被引用的仓内文件: 第一处引用它的 S 写者源码}，只含 rust/src 以外的文件。"""
    found: dict[str, str] = {}
    for source in sorted(p for p in tracked if p.startswith("rust/") and p.endswith(".rs") and static_hit(p)):
        text = (root / source).read_text(encoding="utf-8", errors="replace")
        base = os.path.dirname(source)
        for literal in LITERAL.findall(text):
            if "/" not in literal or " " in literal or literal.startswith(("http:", "https:", "//")):
                continue
            for candidate in (os.path.join(base, literal), os.path.join("rust", literal), literal,
                              os.path.join("s_session", literal)):
                candidate = os.path.normpath(candidate)
                if candidate in tracked:
                    if not candidate.startswith("rust/src/"):
                        found.setdefault(candidate, source)
                    break
    return found


def s_writer_files(changed: list[str], root: Path) -> list[str]:
    derived = derived_paths(root, tracked_files(root))
    return [p for p in changed if static_hit(p) or p in derived]


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 64
    root = Path(argv[2]) if len(argv) == 3 else Path.cwd()
    changed = [line for line in Path(argv[1]).read_text(encoding="utf-8").splitlines() if line]
    for path in s_writer_files(changed, root):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
