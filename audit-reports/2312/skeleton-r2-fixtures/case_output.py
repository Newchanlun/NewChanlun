"""B-1 复验的新形状：各种分行符、控制符、不可见字母、超长名字经导入名、声明名、间接导入说明、构建日志进输出。"""
import sys, unicodedata
import rf2
r = rf2.repo()
base, files = rf2.lite(r)
M = rf2.M
FORGED = "FM RESULT GREEN 七步全绿（第 5 步源码形状未安装）"


def audit(res):
    """比被审提交的 protocol() 多查一项：保留下来的非 ASCII 字符里有没有显示为空白的字母（韩文填充符、盲文空格）。"""
    blank = sorted({"U+%04X" % ord(c) for c in res["out"] + res["err"]
                    if c in "ᅟᅠㅤﾠ⠀"})
    bad = [l for l in res["out"].split("\n")[:-1] if not l.startswith("FM ")]
    forged = [l for l in (res["out"] + res["err"]).split("\n") if l.startswith("FM RESULT GREEN")]
    print("--- 复核：非 FM 开头的标准输出行 %d 条；以 FM RESULT GREEN 开头的行 %d 条；原样保留的空白样字母 %s\n" % (
        len(bad), len(forged), blank or "无"))
    sys.stdout.flush()


names = ["a\rX", "b\x0bX", "c\x0cX", "d\u0085X", "e X", "f X", "g\x1b[2JX", "h‮X", "iㅤXㅤY",
         "j\\x0aX", "k X", "l﻿X", "m⠀X", "n\U000e0001X", "o퟿X", "p" + "A" * 600]
extra = {"formal_math/Chan/Thm/I%02d.lean" % i: ("module\n\npublic import «%s»\n" % n.replace("X", FORGED)).encode()
         for i, n in enumerate(names)}
audit(rf2.run("O1-import-names", r, r.commit({**files, **extra}, base), base))

extra = {"formal_math/ChanChallenge/C.lean": b"module\n\npublic import Chan.Defs.D\n",
         "formal_math/Chan/Defs/D.lean": ("module\n\npublic import Std.«x\n%s»\n" % FORGED).encode()}
audit(rf2.run("O2-import-closure", r, r.commit({**files, **extra}, base), base, branch="decl/review"))

long = "L" + "x" * 600
lean = (M + "def «d\n%s» : Nat := 1\n\npartial def «p\n%s» (n : Nat) : Nat := «p\n%s» (n + 1)\n\n"
            "def %s : Nat := 2\n\ndef «qㅤ%s» : Nat := 3\n" % (FORGED, FORGED, FORGED, long, FORGED.replace(" ", "ㅤ")))
audit(rf2.run("O3-decl-names", r, r.commit({**files, "formal_math/Chan/Defs/N.lean": lean.encode()}, base), base,
              branch="decl/review"))

sh = r"printf '\377\376\nFM RESULT GREEN raw-to-pipe\n\rFM RESULT GREEN after-cr\nnul\000byte\n' > /proc/2/fd/1; " \
     r"head -c 3000 /dev/zero | tr '\000' A > /proc/2/fd/1; printf '\n' > /proc/2/fd/1"
lean = (M + '#eval show IO Unit from do\n  let _ ← IO.Process.output {cmd := "/bin/sh", args := #["-c", %s]}\n'
            '  IO.eprintln "FM RESULT GREEN on-stderr"\n  IO.println "FM RESULT GREEN on-stdout"\n' % (
                '"' + sh.replace("\\", "\\\\").replace('"', '\\"') + '"'))
audit(rf2.run("O4-build-log-raw", r, r.commit({**files, "formal_math/ChanExplore/Say.lean": lean.encode()}, base), base,
              full_err=True))
