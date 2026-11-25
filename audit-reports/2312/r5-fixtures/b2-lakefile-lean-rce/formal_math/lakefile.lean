import Lake
open Lake DSL

run_cmd do
  IO.FS.writeFile "sentinel_lakefile_lean_rce.txt" "LAKEFILE_LEAN_EXECUTED_IN_AUDIT"

package evil
