-- R4-A1 独立复验样本：零导入 include_str (unsafe (unsafeIO ...))；在 R5 精化前被 kindIssues 拒，哨兵未写入
module
public section
@[expose] def leak : String :=
  include_str (unsafe (
    match unsafeIO (do
      IO.FS.writeFile "sentinel_v1a_rce.txt" "PWNED_R5"
      return System.FilePath.mk "/etc/hosts") with
    | .ok p => p
    | .error _ => System.FilePath.mk ""))
