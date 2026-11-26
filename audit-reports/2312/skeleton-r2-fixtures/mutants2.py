"""独审 r2 的弱化测试：在被审树的副本里改一处，用副本自己的自测跑骨架用例。与作者 --mutants 的 18 种不重复。
这里没有任何改沙箱挂载的弱化；非 lite 的骨架用例（S1、S2、S3、S10）对共享依赖目录仍是只读挂载。
用法：mutants2.py <被审检出> <依赖目录> [标签…]"""
import os, re, shutil, subprocess, sys, time

SRC, PACKAGES, only = sys.argv[1], sys.argv[2], set(sys.argv[3:])
FM = os.path.join(SRC, "formal_math")
TOP = os.path.join(os.environ["TMPDIR"], "review-f2", "mut")
R = "verification/runner/run.py"
MUTANTS = [
    ("R0", "对照：不改", None, [], None),
    ("R1", "emit() 对最后一栏（说明、备注）是字符串时跳过 safe()", R,
     [("[safe(fields[-1], spaces=True)]", "[fields[-1] if isinstance(fields[-1], str) else safe(fields[-1], spaces=True)]")],
     "E1,E2,E3,E8,E10"),
    ("R2", "strict_json 接受重复键", R, [("object_pairs_hook=unique_object", "object_pairs_hook=dict")], None),
    ("R3", "产物目录本身是符号链接或经由符号链接时不再判 ARTIFACT_ROOT", R,
     [("if os.path.lexists(lib) and (os.path.realpath(lib) != lib or not os.path.isdir(lib)):",
       "if os.path.lexists(lib) and not os.path.isdir(lib):")], None),
    ("R4", "绿的结论不再要求标准输出都写出去了", R, [('        if state["output"] is not None:\n            state["step"] = "output"',
                                       '        if False:\n            state["step"] = "output"')], None),
    ("R5a", "信号判定阈值改错（>= 138）", R, [("if p.returncode >= 128 or p.returncode < 0:", "if p.returncode >= 138 or p.returncode < 0:")],
     "S18"),
    ("R5b", "信号判定只对第 6 步的构建生效，探针与审计程序不管", R,
     [("if p.returncode >= 128 or p.returncode < 0:", 'if (p.returncode >= 128 or p.returncode < 0) and tag == "build":')], None),
    ("R6", "fault() 不写 FM RESULT FAULT 行", R, [('        emit(1, "RESULT", "FAULT", state["step"], code)\n', "")], "S8,S11,S13,E4"),
    ("R7", "JSON 不要求合法 UTF-8（解码时替换）", R, [('json.loads(data.decode("utf-8"),', 'json.loads(data.decode("utf-8", "replace"),')], None),
    ("R8", "不核对依赖目录里有没有基线清单的包", R, [("    if missing:\n        raise Fault(\"PACKAGES\"", "    if False:\n        raise Fault(\"PACKAGES\"")], None),
    ("R9", "产物集合只按文件名带 .olean 判，不看是不是普通文件、是不是多出来的伴生目录", R,
     [('elif n.endswith(".olean") and n in names:', 'elif n.endswith(".olean"):')], "S20,S21"),
    ("R10", "子进程日志原样透传到标准错误", R, [('            emit(2, "LOG", tag, line)', '            os.write(2, line + b"\\n")')], "E10,S17"),
    ("R11", "main 不再兜住意外异常", R, [("    except Exception as e:  # noqa: BLE001  意外一律归入无法判定", "    except KeyError as e:")], "E13"),
    ("R12", "严格 JSON 不拒 NaN", R, [(", parse_constant=reject_constant)", ")")], "E7"),
    ("R13", "判红时退出码仍是 1，但结果行写成 GREEN", R, [('out("RESULT", "RED", "第 %d 步', 'out("RESULT", "GREEN", "第 %d 步')], "S6a"),
    ("R15", "只去掉「任何层级不许符号链接」，保留顶层只许内容根", R, [("            if os.path.islink(full):", "            if False:")], None),
    ("R16", "只去掉「顶层只许内容根」，保留符号链接检查", R, [('if name.split(".")[0] not in ROOT_NAMES:', "if False:")], None),
    ("R14", "建目录后不 chmod（受 umask 影响）", R, [("    os.mkdir(path, mode)\n    os.chmod(path, mode)\n", "    os.mkdir(path, mode)\n")], None),
]


def copy(tag):
    root = os.path.join(TOP, tag, "formal_math")
    shutil.rmtree(os.path.join(TOP, tag), ignore_errors=True)
    for rel in ("lean-toolchain", "lake-manifest.json", "ChanTest/Probe.lean"):
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        shutil.copy2(os.path.join(FM, rel), os.path.join(root, rel))
    for sub in ("runner", "precheck", "auditor"):
        shutil.copytree(os.path.join(FM, "verification", sub), os.path.join(root, "verification", sub),
                        ignore=shutil.ignore_patterns(".lake", "__pycache__"))
    return root


for tag, label, rel, edits, cases in MUTANTS:
    if only and tag not in only:
        continue
    root = copy(tag)
    if rel:
        path = os.path.join(root, rel)
        text = open(path, encoding="utf-8").read()
        for old, new in edits:
            assert text.count(old) == 1, (tag, old, text.count(old))
            text = text.replace(old, new)
        open(path, "w", encoding="utf-8").write(text)
    began = time.monotonic()
    p = subprocess.run([sys.executable, "-I", os.path.join(root, "verification", "runner", "selftest.py"), "--packages", PACKAGES,
                        "--skip-corpus", "--jobs", "4", *(["--cases", cases] if cases else [])], capture_output=True)
    out = p.stdout.decode(errors="replace")
    failed = [l.split("\t")[1][:60] for l in out.splitlines() if l.startswith("失败\t")]
    total = re.findall(r"自测：(\d+/\d+)", out)
    print("%s\t%s\t用例=%s\t自测退出码=%d\t%s\t%.0fs\t%s" % (
        tag, label, cases or "骨架全量", p.returncode, total[0] if total else "?", time.monotonic() - began,
        "抓到：" + "；".join(failed) if failed else ("对照通过" if tag == "R0" else "**没抓到**")))
    sys.stdout.flush()
    shutil.rmtree(os.path.join(TOP, tag), ignore_errors=True)
