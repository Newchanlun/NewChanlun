#!/usr/bin/env python3
"""在任意检出上复跑 FM-09 复核脚本，不改动原脚本字节。

原脚本 tmp/lib.py 把语料目录写死为 SafeCode 的绝对路径。本包装器在运行前
把 lib.BLOG 指到当前检出的 docs/chanlun/text/blog，再原样执行目标脚本。

用法（在仓库根目录）：
  python3 -I fm09-register/run_on_checkout.py verify_final.py
  python3 -I fm09-register/run_on_checkout.py verify_report.py fm09-register/FM-09-原典登记册.md
  python3 -I fm09-register/run_on_checkout.py verify_report.py --allow-free fm09-register/FM-09-附录1-全量台账.md fm09-register/FM-09-附录2-四清单分类索引.md
"""
import os, runpy, sys

here = os.path.dirname(os.path.abspath(__file__))
tmp = os.path.join(here, "tmp")
blog = os.path.join(os.path.dirname(here), "docs", "chanlun", "text", "blog")
if not os.path.isdir(blog):
    sys.exit("找不到语料目录: " + blog)
sys.path.insert(0, tmp)
import lib

lib.BLOG = blog
script = os.path.join(tmp, sys.argv[1])
sys.argv = [script] + [os.path.abspath(a) if os.path.exists(a) else a for a in sys.argv[2:]]
runpy.run_path(script, run_name="__main__")
