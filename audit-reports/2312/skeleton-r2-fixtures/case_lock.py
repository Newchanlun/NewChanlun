"""B-2 复验的新形状（整条流水线）：被审提交的锁文件嵌套很深、含溢出的浮点、带 BOM、不是对象、值不是字符串。"""
import rf2
r = rf2.repo()
base, files = rf2.lite(r)
for label, lock in (("nest600", b'{"k":' + b"[" * 600 + b"]" * 600 + b"}"),
                    ("nest100000", b'{"k":' + b"[" * 100000 + b"]" * 100000 + b"}"),
                    ("float-overflow", b'{"k": 1e999}'), ("bom", b"\xef\xbb\xbf{}\n"), ("array", b"[]\n"),
                    ("value-types", b'{"a": 1, "b": null, "c": ["x"], "d": {"e": "f"}, "": "empty-key", "-": "dash"}'),
                    ("dup-plain", b'{"a": "x", "a": "x"}'), ("non-utf8", b'{"k": "\xff"}')):
    rf2.run("L-" + label, r, r.commit({**files, "formal_math/statement-lock.json": lock}, base), base, branch="decl/review")
