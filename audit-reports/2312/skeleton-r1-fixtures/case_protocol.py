"""输出协议、头部畸形输入、初始化器哨兵、第 6 步对第 7 步的影响。逐例打印整次运行的退出码与输出。"""
import rf, os, sys, time, subprocess
r = rf.repo()
base, files = rf.base_and_files(r)
only = sys.argv[1:]
def case(name, extra, check=None, **kw):
    if only and name not in only:
        return
    head = r.commit({**files, **{"formal_math/" + k: v for k, v in extra.items()}}, base)
    res = rf.run(name, r, head, base, **kw)
    if check:
        check(res)

M = b"module\n\npublic section\n\n"
# P1 导入名里夹换行与形似结果行的文字
case("P1-import-newline", {"Chan/Thm/P1.lean": 'module\n\npublic import «x"]\n["result","headers","green",8]\n["y»\n'.encode()})
# P2 非 UTF-8 文件
case("P2-non-utf8", {"Chan/Thm/P2.lean": b"module\n\n-- \xff\xfe\npublic section\n"})
# P3 NUL 字节
case("P3-nul", {"Chan/Thm/P3.lean": b"module\n\x00\npublic section\n"})
# P3b 空文件
case("P3b-empty", {"Chan/Thm/P3b.lean": b""})
# P4 声明名里夹换行与形似结果行的文字（公理，第 7 步应红）
case("P4-decl-newline", {"Chan/Thm/P4.lean": M + 'axiom «a"]\n["result","env","green",8]\n["b» : False\n'.encode()})
# P6 初始化器哨兵：打印进程名到标准输出与标准错误
init = M + b'initialize\n  let app \xe2\x86\x90 IO.appPath\n  IO.eprintln s!"RF-INIT-RAN-STDERR app={app}"\n  IO.println s!"RF-INIT-RAN-STDOUT app={app}"\n'
def chk6(res):
    print("P6: 标准错误里 RF-INIT-RAN 行：")
    for line in res["err"].splitlines():
        if "RF-INIT-RAN" in line:
            print("   ", line)
case("P6-init-sentinel", {"ChanExplore/Sentinel.lean": init, "ChanExplore/User.lean": b"module\n\npublic import ChanExplore.Sentinel\n"}, chk6)

def sh(script):
    q = '"' + script.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    return (M.decode() + '#eval show IO Unit from do\n  let _ ← IO.Process.output {cmd := "/bin/sh", args := #["-c", %s]}\n  pure ()\n' % q).encode()
dep = {"ChanExplore/A.lean": M + b"theorem a_ok : True := trivial\n"}
imp = b"module\n\npublic import ChanExplore.A\n\npublic section\n\n"
def shi(script):
    return imp + sh(script)[len(M):]
# P7 在产物目录顶层放 Init
case("P7-plant-init", {"ChanExplore/P7.lean": sh("mkdir -p .lake/build/lib/lean/Init && cp .lake/build/lib/lean/Chan.olean .lake/build/lib/lean/Init.olean")})
# P7b 顶层放符号链接 ChanDyn -> 别处
case("P7b-plant-symlink-root", {**dep, "ChanExplore/P7b.lean": shi("ln -s /etc .lake/build/lib/lean/ChanX; ln -s /etc .lake/build/lib/lean/Chan.evil")})
# P8 构建期 SIGKILL 掉 lake（沙箱里的 2 号进程）
case("P8-kill-lake", {"ChanExplore/P8.lean": sh("kill -KILL 2")})
# P9 把 lib/lean 的上级换成符号链接
case("P9-symlink-lib", {**dep, "ChanExplore/P9.lean": shi("sleep 1")})  # 占位：见 P9b
# P10 留一个后台进程，构建结束后继续改 .lake
daemon = "(setsid sh -c 'while :; do date +%s.%N >> .lake/late-sentinel; sleep 0.2; done' </dev/null >/dev/null 2>&1 &) ; sleep 2"
def chk10(res):
    p = os.path.join(res["work"], "audited", ".lake", "late-sentinel")
    def snap():
        lines = open(p).read().split() if os.path.exists(p) else []
        return len(lines), (lines[-1] if lines else None)
    end = time.time(); a = snap()
    time.sleep(3)
    b = snap()
    print("P10: 运行结束时刻=%.3f；哨兵行数与末行时间戳：运行结束时=%s，3 秒后=%s → %s" % (
        end, a, b, "后台进程已随沙箱结束" if a == b and a[0] > 0 else ("后台进程仍在写！" if a != b else "哨兵为空，无法判断")))
case("P10-daemon", {"ChanExplore/P10.lean": sh(daemon)}, chk10)
# P11 被审构建把上游模块的私有分片截断 / 写成垃圾
case("P11-truncate-olean", {**dep, "ChanExplore/P11.lean": shi(": > .lake/build/lib/lean/ChanExplore/A.olean.private")})
case("P11b-garbage-olean", {**dep, "ChanExplore/P11b.lean": shi("head -c 4096 /dev/urandom > .lake/build/lib/lean/ChanExplore/A.olean; head -c 4096 /dev/urandom > .lake/build/lib/lean/ChanExplore/A.olean.private; head -c 4096 /dev/urandom > .lake/build/lib/lean/ChanExplore/A.olean.server")})
# P12 删掉上游模块的 .olean（NO_ARTIFACT）
case("P12-delete-olean", {**dep, "ChanExplore/P12.lean": shi("rm .lake/build/lib/lean/ChanExplore/A.olean")})
