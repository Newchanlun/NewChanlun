#!/usr/bin/env python3
"""审阅用夹具生成器：gen.py <批名>。每个变体一个文件，期望写在 EXPECT.tsv。"""
import os, sys, importlib.util
R = "/home/workspace/fm/tmp/review-g1/fx"
def emit(batch, cases):
    root = os.path.join(R, batch)
    rows = []
    seen = set()
    for rel, imports, body, expect in cases:
        assert rel not in seen, rel
        seen.add(rel)
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        head = "module\n\n" + "".join("import %s\n" % i for i in imports)
        if body.startswith("RAW:"):
            text = body[4:]
        else:
            text = head + "\n" + body + "\n"
        with open(p, "w") as f: f.write(text)
        rows.append("%s\t%s" % (rel, ",".join(sorted(expect)) if expect else "GREEN"))
    with open(os.path.join(root, "EXPECT.tsv"), "w") as f: f.write("\n".join(rows) + "\n")
    print(batch, len(cases))
if __name__ == "__main__":
    spec = importlib.util.spec_from_file_location("cases", sys.argv[1])
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    emit(m.BATCH, m.CASES)
