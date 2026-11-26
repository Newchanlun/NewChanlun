"""B-3 复验的新形状：构建期杀掉的不是 lake 而是别的进程；用别的信号杀 lake；自己以 ≥128 的码退出。"""
import rf2
r = rf2.repo()
base, files = rf2.lite(r)
M = rf2.M


def sh(script):
    return (M + '#eval show IO Unit from do\n  let _ ← IO.Process.output {cmd := "/bin/sh", args := #["-c", "%s"]}\n'
                '  pure ()\n' % script).encode()


for label, script in (("kill-lake-TERM", "kill -TERM 2"), ("kill-lake-SEGV", "kill -SEGV 2"),
                      ("kill-own-lean", "kill -KILL $PPID"), ("kill-sandbox-init", "kill -KILL 1"),
                      ("kill-all", "kill -KILL -1")):
    # N-3 的那一例走真实命令行入口，其余经驱动。
    rf2.run("G-" + label, r, r.commit({**files, "formal_math/ChanExplore/Kill.lean": sh(script)}, base), base,
            warm=label != "kill-own-lean")
# 被审代码让 lean 自己以 137 退出：lake 把它当普通构建失败。
lean = (M + "#eval show IO Unit from do\n  IO.Process.exit 137\n").encode()
rf2.run("G-lean-exit-137", r, r.commit({**files, "formal_math/ChanExplore/Kill.lean": lean}, base), base)
