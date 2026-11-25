-- 传统（非 module）文件：带 initialize，导入时由解释器执行。
initialize toySentinel : Unit ← do
  IO.FS.writeFile "/home/workspace/fm/tmp/consult-2312/expA/out/SENTINEL_INIT" "initialize ran\n"

def Toy.one : Nat := 1
