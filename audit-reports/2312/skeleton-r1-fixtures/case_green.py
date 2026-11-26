"""阴性对照：真实命令行入口（不走预编译），证明角色加一个定理。"""
import rf, time
r = rf.repo()
base, files = rf.base_and_files(r)
ok = {"formal_math/Chan/Thm/Ok.lean": b"module\n\npublic section\n\ntheorem ok : 1 + 1 = 2 := rfl\n"}
head = r.commit({**files, **ok}, base)
t = time.time()
rf.run("green", r, head, base, warm=False)
print("elapsed %.1fs base=%s head=%s" % (time.time() - t, base, head))
