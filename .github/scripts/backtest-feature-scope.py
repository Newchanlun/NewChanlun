#!/usr/bin/env python3
"""#1875：backtest_bin 作业能否只跑 theta_v0::nautilus 下的测试。

rust-test-default 已在不带特性的构建里跑过全部库测试。开 backtest_bin（含 nautilus）后，只有
theta_v0/nautilus/ 里按特性门控的条目是新增的；其余同名测试测的是同一份代码，前提是：
  1. nautilus/ 之外提到这两个特性的源码行，只有 `any(test, feature = ...)`（测试构建里本来就成立）
     和 `cfg_attr(not(feature = ...), allow(dead_code ...))`（只是 lint 开关）两种形式；
  2. Cargo.toml 里这两个特性只打开 `dep:` 可选依赖或 nautilus 本身，不连带本仓其他特性。
两条都成立时退出 0（可以只跑 nautilus 测试），否则打印原因并退出 1（跑全部库测试）。
用法：在 rust/ 下运行。
"""
import pathlib
import re
import sys

FEATURE = re.compile(r'feature\s*=\s*"(nautilus|backtest_bin)"')
ANY_TEST = re.compile(r'any\(\s*test\s*,\s*feature\s*=\s*"backtest_bin"\s*\)')
NOT_FEATURE = re.compile(r'^\s*not\(\s*feature\s*=\s*"backtest_bin"\s*\)\s*,\s*$')
# 去掉空白后整块必须是这一种形式：只在不开特性时放宽 dead_code lint。
DEAD_CODE_ATTR = re.compile(r'^not\(feature="backtest_bin"\),allow\(dead_code,reason="[^"]*",?\),?\)\]$')
SCOPED = pathlib.PurePosixPath("src/theta_v0/nautilus")


def source_problems():
    problems = []
    for path in sorted(pathlib.Path("src").rglob("*.rs")):
        rel = pathlib.PurePosixPath(path.as_posix())
        if SCOPED in rel.parents:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            code = line.split("//", 1)[0]
            if not FEATURE.search(code):
                continue
            if ANY_TEST.search(code) and len(FEATURE.findall(code)) == 1:
                continue
            prev = next((l.strip() for l in reversed(lines[:i]) if l.strip()), "")
            if NOT_FEATURE.match(code) and prev == "#[cfg_attr(":
                end = next((j for j in range(i, len(lines)) if ")]" in lines[j]), None)
                block = "" if end is None else re.sub(r"\s+", "", "".join(lines[i:end + 1]))
                if DEAD_CODE_ATTR.match(block):
                    continue
            problems.append(f"{rel}:{i + 1}: {line.strip()}")
    return problems


def cargo_problems():
    text = pathlib.Path("Cargo.toml").read_text(encoding="utf-8")
    problems = []
    for name in ("nautilus", "backtest_bin"):
        m = re.search(rf'^{name}\s*=\s*\[(.*?)\]', text, re.M | re.S)
        if not m:
            problems.append(f"Cargo.toml: feature {name} not found")
            continue
        for item in re.findall(r'"([^"]*)"', m.group(1)):
            if not (item.startswith("dep:") or item == "nautilus"):
                problems.append(f"Cargo.toml: {name} enables {item!r}")
    return problems


def main():
    problems = source_problems() + cargo_problems()
    if problems:
        print("backtest_bin scope: run all lib tests; feature gates outside theta_v0/nautilus:")
        for p in problems:
            print("  " + p)
        return 1
    print("backtest_bin scope: only theta_v0::nautilus tests are feature-specific")
    return 0


if __name__ == "__main__":
    sys.exit(main())
