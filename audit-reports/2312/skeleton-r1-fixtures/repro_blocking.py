"""阻断缺陷的逐字复现（真实命令行入口 python3 -I run.py，不走预编译审计程序）。
B-1 标准输出注入见 case_inject.py；这里复现 B-2（被审提交的锁文件键里放孤立代理项 → 未捕获回溯、退 1）
与 B-3（第 6 步 lake 被 SIGKILL → 说明写退 2，实际 BUILD_WFAIL 退 1）。"""
import rf
r = rf.repo()
base, files = rf.base_and_files(r)
M = "module\n\npublic section\n\n"
h = r.commit({**files, "formal_math/statement-lock.json": b'{"\\ud800": "x"}\n'}, base)
rf.run("B2-lock-lone-surrogate-key", r, h, base, branch="decl/review", warm=False)
h = r.commit({**files, "formal_math/statement-lock.json": b'{"\\ud800": "x", "\\ud800": "y"}\n'}, base)
rf.run("B2-lock-dup-surrogate-key", r, h, base, branch="decl/review", warm=False)
kill = M + '#eval show IO Unit from do\n  let _ ← IO.Process.output {cmd := "/bin/sh", args := #["-c", "kill -KILL 2"]}\n  pure ()\n'
h = r.commit({**files, "formal_math/ChanExplore/Kill.lean": kill.encode()}, base)
rf.run("B3-kill-lake", r, h, base, warm=False)
