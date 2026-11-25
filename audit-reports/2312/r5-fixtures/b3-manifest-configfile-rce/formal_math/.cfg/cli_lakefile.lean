import Lake
open Lake DSL

run_cmd do
  IO.FS.writeFile "sentinel_inrepo_cli_manifest_rce.txt" "INREPO_CLI_MANIFEST_CONFIGFILE_RCE"

package Cli
