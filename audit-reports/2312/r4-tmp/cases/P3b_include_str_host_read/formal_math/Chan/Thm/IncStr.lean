module
public section
def leaked : String := include_str (dbgTrace "INCLUDE_STR_EVAL_RAN" fun _ => "/Volumes/AgentStorage/fm/tmp/2312-d-review/host_secret_probe.txt")
theorem leaked_eq : leaked = "TOP_SECRET_HOST_CONTENT_42\n" := rfl
