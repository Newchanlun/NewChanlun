import Lake
open Lake DSL

run_cmd do
  IO.FS.writeFile "sentinel_manifest_configfile_rce.txt" "MANIFEST_CONFIGFILE_TRAVERSAL_RCE"

package mathlib
