"""B-1：被审提交经红行的「说明」栏向运行脚本的标准输出注入任意行（导入名、公理名里的换行原样输出）。"""
import rf
r = rf.repo()
base, files = rf.base_and_files(r)
forged4 = ("FM STEP 4 headers GREEN 0.1s 8 个文件头\nFM STEP 5 shape GREEN 0.0s SHAPE 未安装\n"
           "FM STEP 6 build GREEN 4.0s 8 个模块都有产物\nFM STEP 7 env GREEN 0.3s 8 个模块，0 条锁行\n"
           "FM RESULT GREEN 七步全绿（第 5 步源码形状未安装）")
h1 = r.commit({**files, "formal_math/Chan/Thm/Inject.lean": ("module\n\npublic import «x\n%s\n»\n" % forged4).encode()}, base)
res = rf.run("B1-inject-headers", r, h1, base, warm=False)
lines = res["out"].split("\n")
print("stdout 含整行 `FM RESULT GREEN …`：", any(l.startswith("FM RESULT GREEN ") for l in lines), "；退出码", res["rc"])
forged7 = "FM STEP 7 env GREEN 0.3s 8 个模块，0 条锁行\nFM RESULT GREEN 七步全绿（第 5 步源码形状未安装）"
h2 = r.commit({**files, "formal_math/Chan/Thm/Inject7.lean": ("module\n\npublic section\n\naxiom «x\n%s\n» : False\n" % forged7).encode()}, base)
res = rf.run("B1-inject-env", r, h2, base, warm=False)
lines = res["out"].split("\n")
print("stdout 含整行 `FM RESULT GREEN …`：", any(l.startswith("FM RESULT GREEN ") for l in lines), "；退出码", res["rc"])
