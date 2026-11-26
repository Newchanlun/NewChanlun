"""strict_json() 的边界矩阵：以模块方式载入被审 run.py（python3 -I），直接调用。不调用 lean、lake。"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location("fm_run", sys.argv[1])
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)
cases = [
    ("空对象", b"{}"), ("重复键", b'{"a":1,"a":1}'), ("嵌套对象里的重复键", b'{"k":{"a":1,"a":2}}'),
    ("数组里的对象重复键", b'[{"a":1,"a":2}]'), ("键转义后相同", b'{"a":1,"\\u0061":2}'),
    ("NaN", b'{"k":NaN}'), ("Infinity", b'{"k":Infinity}'), ("-Infinity", b'{"k":-Infinity}'),
    ("1e999（溢出成无穷大）", b'{"k":1e999}'), ("-1e999", b'{"k":-1e999}'), ("5000 位整数", b'{"k":' + b"9" * 5000 + b"}"),
    ("孤立高代理项（转义）", b'{"k":"\\ud800"}'), ("孤立低代理项（转义）", b'{"k":"\\udc00"}'),
    ("代理项顺序颠倒", b'{"k":"\\udc00\\ud800"}'), ("合法代理对", b'{"k":"\\ud83d\\ude00"}'),
    ("键里的孤立代理项", b'{"\\ud800":1}'), ("数组深处的孤立代理项", b'[[[{"a":["\\udfff"]}]]]'),
    ("原始字节形式的代理项 ED A0 80", b'{"k":"\xed\xa0\x80"}'), ("非 UTF-8 字节", b'{"k":"\xff"}'),
    ("过长编码 C0 80", b'{"k":"\xc0\x80"}'), ("UTF-8 BOM", b"\xef\xbb\xbf{}"), ("UTF-16", '{"k":1}'.encode("utf-16")),
    ("字符串里的原始换行", b'{"k":"a\nb"}'), ("字符串里的原始制表符", b'{"k":"a\tb"}'), ("NUL 转义", b'{"k":"\\u0000"}'),
    ("尾随逗号", b'{"k":1,}'), ("单引号", b"{'k':1}"), ("注释", b'{"k":1}//x'), ("尾部多余内容", b'{"k":1} x'),
    ("两个值", b"{}{}"), ("前导零", b'{"k":01}'), ("十六进制数", b'{"k":0x10}'), ("空输入", b""), ("只有空白", b" \n"),
    ("顶层标量", b"1"), ("顶层字符串", b'"x"'), ("顶层 null", b"null"), ("顶层数组", b"[]"),
    ("嵌套 600 层数组", b"[" * 600 + b"]" * 600), ("嵌套 10 万层数组", b"[" * 100000 + b"]" * 100000),
    ("嵌套 600 层对象", b'{"a":' * 600 + b"1" + b"}" * 600),
    ("前后有回车与空白", b' \r\n{"k":1}\r\n'), ("true/false/null", b'{"a":true,"b":false,"c":null}'),
    ("负零与小数", b'{"a":-0,"b":1.0,"c":1e2}'),
]
for label, data in cases:
    try:
        v = run.strict_json(data, "CODE", "what")
        shown = repr(v)
        print("%-34s 接受  %s" % (label, shown if len(shown) < 70 else shown[:60] + "…"))
    except run.Fault as f:
        print("%-34s 拒收  Fault%s" % (label, f.args))
    except BaseException as e:
        print("%-34s 逃出 strict_json 的异常  %s" % (label, type(e).__name__))
print("--- safe() 抽查")
for label, x in [("空串", ""), ("字节 -", b"-"), ("反斜杠", "a\\x0ab"), ("非 UTF-8 字节", b"a\xff\xfeb"),
                 ("孤立代理项", "a\ud800b"), ("低代理项（非字节来源）", "a\udc80b"), ("换行与空格", "a b\nc"),
                 ("韩文填充符", "aㅤb"), ("不换行空格", "a b"), ("超长", "x" * 405), ("None", None), ("整数", 7)]:
    print("%-24s spaces=False %r | spaces=True %r" % (label, run.safe(x), run.safe(x, spaces=True)))
print("--- unescape() 往返")
for raw in [b"a b", b"\\x0a", b"\\", b"\xff\n", b"\\x5cx0a", b"-", b""]:
    shown = b"".join(bytes([c]) if 0x21 <= c < 0x7F and c != 0x5C else b"\\x%02x" % c for c in raw) or b"-"
    print("%r -> 预检转义 %r -> unescape %r %s" % (raw, shown, run.unescape(shown), "一致" if run.unescape(shown) == (raw or b"-") else "不一致"))
