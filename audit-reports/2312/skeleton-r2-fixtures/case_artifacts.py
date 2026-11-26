"""产物集合核对（第 6 步）的边界：名字带点的 .olean、伴生文件、只可进入不可列出的目录、合法构建的产物清单。"""
import os, stat
import rf2
r = rf2.repo()
base, files = rf2.lite(r)
M = rf2.M
ok = {"formal_math/Chan/Thm/Ok.lean": (M + "theorem ok : 1 + 1 = 2 := rfl\n").encode()}
L = ".lake/build/lib/lean"


def plant(*lines):
    body = "".join("  %s\n" % l for l in lines)
    return {"formal_math/ChanExplore/Plant.lean": (M + "#eval show IO Unit from do\n" + body).encode()}


def sh(script):
    return 'let _ ← IO.Process.output {cmd := "/bin/sh", args := #["-c", "%s"]}' % script


res = rf2.run("A0-legit-listing", r, r.commit({**files, **ok}, base), base)
lib = os.path.join(res["work"], "audited", L)
exts, tops = {}, sorted(os.listdir(lib))
for d, _, names in os.walk(lib):
    for n in names:
        ext = n[n.index("."):]
        exts[ext] = exts.get(ext, 0) + 1
print("合法构建的产物目录：顶层 %s；各后缀文件数 %s" % (tops, dict(sorted(exts.items()))))
lake = os.path.join(res["work"], "audited", ".lake")
print(".lake 顶层 %s；.lake/build 顶层 %s\n" % (sorted(os.listdir(lake)), sorted(os.listdir(os.path.join(lake, "build")))))

cases = [
    ("A1-dotted-name", [sh("cp %s/Chan/Thm/Ok.olean %s/Chan/Thm.Ok.olean; cp %s/Chan/Thm/Ok.olean %s/Chan.Thm.Ok.olean" % (L, L, L, L))]),
    ("A2-companions", ['IO.FS.writeFile "%s/Chan/Ghost.olean.private" ""' % L, 'IO.FS.writeFile "%s/Chan/Ghost.olean.server" ""' % L,
                       'IO.FS.writeFile "%s/Chan/Ghost.ilean" ""' % L, 'IO.FS.createDirAll "%s/Chan/Dir.olean"' % L,
                       'IO.FS.writeFile "%s/Chan/Ghost.OLEAN" ""' % L]),
    ("A3-unlistable-dir", [sh("mkdir %s/Chan/Hidden && cp %s/Chan/Thm/Ok.olean %s/Chan/Hidden/Ghost.olean && "
                              "ln -s /etc/hostname %s/Chan/Hidden/Link.olean && chmod 111 %s/Chan/Hidden" % (L, L, L, L, L))]),
    ("A4-dotted-top-dir", ['IO.FS.createDirAll "%s/Chan.Evil"' % L, 'IO.FS.writeFile "%s/Chan.Evil/X.olean" ""' % L]),
    ("A5-fifo-and-dir", [sh("mkfifo %s/Chan/Pipe.olean" % L)]),
    ("A6-outside-lib", ['IO.FS.createDirAll ".lake/build/lib/extra/Init"', 'IO.FS.writeFile ".lake/build/lib/extra/Init/Fake.olean" ""',
                        'IO.FS.writeFile ".lake/lakefile.olean" "x"', 'IO.FS.writeFile ".lake/lake-manifest.json" "x"',
                        sh("ln -s /etc/hostname .lake/link; mkdir -p .lake/build/bin; cp /bin/true .lake/build/bin/fm_audit")]),
    ("A8-lib-is-symlink", [sh("mv %s .lake/build/lib/real && ln -s real %s" % (L, L))]),
    ("A9-deep-symlink-only", [sh("ln -s Ok.olean %s/Chan/Thm/Alias.ilean; ln -s ../Thm %s/Chan/Thm/LinkDir" % (L, L))]),
    ("A7-top-olean-root", ['IO.FS.writeFile "%s/ChanDyn.olean" ""' % L, 'IO.FS.writeFile "%s/chan.olean" ""' % L]),
]
for name, lines in cases:
    res = rf2.run(name, r, r.commit({**files, **ok, **plant(*lines)}, base), base)
    lib = os.path.join(res["work"], "audited", L)
    hidden = os.path.join(lib, "Chan", "Hidden")
    if os.path.isdir(hidden):
        os.chmod(hidden, 0o755)
        print("（事后改回可列）Hidden 里有：%s\n" % sorted(os.listdir(hidden)))
