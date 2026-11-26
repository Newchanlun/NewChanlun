#!/usr/bin/env python3
"""r3：artifact_reds() 的单元矩阵——在磁盘上造各种 .lake 形状，直接调用被审的形状表判定。
不跑 lean、lake。用法：python3 -I case_shape_unit.py <run.py> <工作根>"""
import importlib.util, os, shutil, stat, sys
spec = importlib.util.spec_from_file_location("fm_run", sys.argv[1])
run = importlib.util.module_from_spec(spec); spec.loader.exec_module(run)
ROOT = os.path.join(sys.argv[2], "shape-unit")
MODULES = ["Chan", "Chan.Smoke", "ChanTest.Probe"]


def build_legal(lake):
    """按形状表造一份「合法的完整构建」。"""
    mods = [m.split(".") for m in MODULES]
    os.makedirs(os.path.join(lake, "packages"))
    for m in mods:
        for base, sufs in (("build/lib/lean", run.LIB_SUFFIXES), ("build/ir", run.IR_SUFFIXES)):
            d = os.path.join(lake, base, *m[:-1])
            os.makedirs(d, exist_ok=True)
            for s in sufs:
                p = os.path.join(d, m[-1] + s)
                open(p, "wb").write(b"x")
                os.chmod(p, 0o644)
    for n in ("1", "5"):
        d = os.path.join(lake, "config", n)
        os.makedirs(d)
        for f in ("lakefile.olean", "lakefile.olean.trace"):
            open(os.path.join(d, f), "wb").write(b"x")


def case(name, mutate, expect=None):
    lake = os.path.join(ROOT, name.replace("/", "_").replace(" ", "_"))
    if os.path.lexists(lake):
        os.system("chmod -R u+rwX '%s'" % lake)
        shutil.rmtree(lake)
    os.makedirs(lake)
    build_legal(lake)
    note = mutate(lake) or ""
    ctx = run.Run(); ctx.modules = list(MODULES)
    reds = run.artifact_reds(ctx, lake)
    pairs = sorted((c, p.replace("formal_math/.lake/", "")) for c, p, _ in reds)
    ok = "" if expect is None else ("✓" if sorted(expect) == pairs else "✗ 期望 %s" % sorted(expect))
    print("%-44s %-2s %s %s" % (name, ok, pairs or "无红", note))
    os.system("chmod -R u+rwX '%s'" % lake)
    shutil.rmtree(lake, ignore_errors=True)


L = "build/lib/lean"
print("=== 合法构建（应无红）与目录项计数")


def count(lake):
    n = sum(len(d) + len(f) for _, d, f in os.walk(lake))
    return "目录项 %d 个（3 模块：13+3 后缀、12 目录、config 4 文件）" % n


case("合法的完整构建", count, [])
print("\n=== 文件模式（Q2 弱化没被自测抓到的那一处）")
case("合法 .olean 带执行位 0755", lambda k: os.chmod(os.path.join(k, L, "Chan/Smoke.olean"), 0o755),
     [("ARTIFACT_FORM", L + "/Chan/Smoke.olean"), ("NO_ARTIFACT", "x")] and
     [("ARTIFACT_FORM", L + "/Chan/Smoke.olean")] + [("NO_ARTIFACT", "")] if False else None)
case("合法 .olean 带 setuid 4644", lambda k: os.chmod(os.path.join(k, L, "Chan/Smoke.olean"), 0o4644))
case("合法 .olean 属主不可读 0244", lambda k: os.chmod(os.path.join(k, L, "Chan/Smoke.olean"), 0o244))
case("合法 .trace 带执行位", lambda k: os.chmod(os.path.join(k, L, "Chan/Smoke.trace"), 0o744))
case("合法 .olean 模式 0400（只读，应放行）", lambda k: os.chmod(os.path.join(k, L, "Chan/Smoke.olean"), 0o400), [])
case("合法 .olean 模式 0600（应放行）", lambda k: os.chmod(os.path.join(k, L, "Chan/Smoke.olean"), 0o600), [])
print("\n=== 目录模式")
case("内容目录 0111（可进不可列）", lambda k: os.chmod(os.path.join(k, L, "Chan"), 0o111))
case("内容目录 0500（不可写）", lambda k: os.chmod(os.path.join(k, L, "Chan"), 0o500))
case("内容目录带 setgid 2755", lambda k: os.chmod(os.path.join(k, L, "Chan"), 0o2755))
case("内容目录带 sticky 1755", lambda k: os.chmod(os.path.join(k, L, "Chan"), 0o1755))
case("内容目录 0755（应放行）", lambda k: os.chmod(os.path.join(k, L, "Chan"), 0o755), [])
case("内容目录 0700（应放行）", lambda k: os.chmod(os.path.join(k, L, "Chan"), 0o700), [])
print("\n=== 名字与类型")
case("顶层放 Init/", lambda k: os.makedirs(os.path.join(k, L, "Init")))
case("顶层放 Init.olean 文件", lambda k: open(os.path.join(k, L, "Init.olean"), "w").close())
case("没有源码的模块 Chan/Ghost.olean", lambda k: open(os.path.join(k, L, "Chan/Ghost.olean"), "w").close())
case("名字带多余点 Chan/Smoke.x.olean", lambda k: open(os.path.join(k, L, "Chan/Smoke.x.olean"), "w").close())
case("隐藏名 Chan/.Smoke.olean", lambda k: open(os.path.join(k, L, "Chan/.Smoke.olean"), "w").close())
case("只差大小写 Chan/smoke.olean", lambda k: open(os.path.join(k, L, "Chan/smoke.olean"), "w").close())
case("西里尔同形名 Chan/Smokе.olean", lambda k: open(os.path.join(k, L, "Chan/Smokе.olean"), "w").close())
case("非 UTF-8 名字", lambda k: open(os.path.join(k.encode(), (L + "/Chan/A\xff.olean").encode("utf-8", "surrogateescape")), "w").close())
case("名为 X.olean 的目录", lambda k: os.makedirs(os.path.join(k, L, "Chan/Dir.olean")))
case("符号链接（指向表内合法名）", lambda k: os.symlink("Smoke.olean", os.path.join(k, L, "Chan/Smoke.ilean.x")) or
     os.symlink("/etc/hostname", os.path.join(k, L, "Chan/Smoke.olean.server.hash2")))
case("把合法 .olean 换成符号链接", lambda k: (os.remove(os.path.join(k, L, "Chan/Smoke.olean")),
                                     os.symlink("/etc/hostname", os.path.join(k, L, "Chan/Smoke.olean"))) and None)
case("命名管道占用合法名", lambda k: (os.remove(os.path.join(k, L, "Chan/Smoke.trace")),
                              os.mkfifo(os.path.join(k, L, "Chan/Smoke.trace"))) and None)
case("把 build/lib/lean 换成符号链接", lambda k: (shutil.move(os.path.join(k, "build/lib/lean"), os.path.join(k, "build/lib/real")),
                                        os.symlink("real", os.path.join(k, "build/lib/lean"))) and None)
case(".lake 顶层多一个文件", lambda k: open(os.path.join(k, "stray"), "w").close())
case(".lake/build/bin/x", lambda k: (os.makedirs(os.path.join(k, "build/bin")),
                                     open(os.path.join(k, "build/bin/x"), "w").close()) and None)
case("依赖挂载点下有东西", lambda k: open(os.path.join(k, "packages/x"), "w").close())
case("config/<非数字>", lambda k: os.makedirs(os.path.join(k, "config/abc")))
case("config/9/other.olean", lambda k: (os.makedirs(os.path.join(k, "config/9")),
                                        open(os.path.join(k, "config/9/other.olean"), "w").close()) and None)
case("config/007（应放行）", lambda k: (os.makedirs(os.path.join(k, "config/007")),
                                   open(os.path.join(k, "config/007/lakefile.olean"), "w").close()) and None, [])
case("缺一个模块的 .olean", lambda k: os.remove(os.path.join(k, L, "Chan/Smoke.olean")))
case("缺一个模块的 .trace（应放行）", lambda k: os.remove(os.path.join(k, L, "Chan/Smoke.trace")), [])
case("缺整个 ir 目录（应放行）", lambda k: shutil.rmtree(os.path.join(k, "build/ir")), [])
case("缺 packages 目录（应放行）", lambda k: os.rmdir(os.path.join(k, "packages")), [])
case("硬链接到表内另一个合法名", lambda k: (os.remove(os.path.join(k, L, "Chan/Smoke.trace")),
                                  os.link(os.path.join(k, L, "Chan/Smoke.olean"), os.path.join(k, L, "Chan/Smoke.trace"))) and None, [])
case("3 GB 稀疏的合法 .olean", lambda k: os.truncate(os.path.join(k, L, "Chan/Smoke.olean"), 3 << 30) or
     "（稀疏，形状表不查大小与内容）", [])
case("内容被换成别的模块的产物", lambda k: shutil.copy(os.path.join(k, L, "Chan.olean"),
                                            os.path.join(k, L, "Chan/Smoke.olean")) and None, [])
