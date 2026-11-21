import concurrent.futures
import json
import pathlib
import shlex
import subprocess
from collections import OrderedDict

root=pathlib.Path(".scratch-2128")
queries = OrderedDict([
    ("Q1", (["\"UnsupportedWalShmJournalCombination\" in:body,comments", "SHM R4 in:body,comments"], r"UnsupportedWalShmJournalCombination|介质再准入|R4.{0,15}SHM|SHM.{0,15}R4", ["docs/adr", ".chanlun/definitions", "analysis", "rust/src/bin/s_session_v3", "s_session"])),
    ("Q2", (["\"原会话端点\" in:body,comments", "\"残留 socket\" in:body,comments"], r"残留.*socket|socket.*残留|维护锁|maintenance\.lock|prepare_socket", ["docs/adr", ".chanlun/definitions", "analysis", "rust/src/bin/s_session_v3/admission.rs", "s_session/s_service_control.py"])),
    ("Q3", (["\"准入合同\" in:body,comments", "\"AwaitingMeasurement\" in:body,comments"], r"AwaitingMeasurement|无锚自动接管|八项.*(上限|峰值)|原启动绝对期限", ["docs/adr", ".chanlun/definitions", "analysis", "rust/src/bin/s_session_v3/admission_anchor.rs", "rust/src/bin/s_session_v3/admission_issuance.rs"])),
    ("Q4", (["\"具名恢复\" in:body,comments", "\"未完成Begin\" in:body,comments"], r"RecoverHandoff|recovered_begin|last_recovered_begin|未完成.{0,6}Begin|恢复幂等|resume_pending", ["docs/adr", ".chanlun/definitions", "analysis", "rust/src/bin/s_session_v3", "s_session/s_service_control.py"])),
    ("Q5", (["\"authority_epoch\" in:body,comments", "\"authorized_sources\" in:body,comments"], r"authority_epoch|authorized_sources|authority_profile|同轨迹|连续参照", ["docs/adr", ".chanlun/definitions", "analysis", "rust/src/history_simulation/runtime.rs", "rust/src/bin/production_session.rs"])),
    ("Q6", (["\"wal_checkpoint\" in:body,comments", "\"删除 WAL\" in:body,comments"], r"NO_CKPT_ON_CLOSE|wal_checkpoint|ColdConvertedContent|WAL.{0,12}收尾|从.{0,5}签锚.{0,6}重建", ["docs/adr", ".chanlun/definitions", "analysis", "rust/src/bin/s_structure_session.rs", "rust/src/bin/s_session_v3", "s_session"])),
    ("Q7", (["\"TB-07-C\" in:body,comments", "\"cut-1\" \"SHM\" in:body,comments"], r"checkpoint 恢复|同一故障|段.*恢复|不重发|H2.*恢复|完整历史双跑", ["docs/adr", ".chanlun/definitions", "analysis", "rust/tests/production_session_entry.rs"])),
])
(repo_rev, repo)=(subprocess.check_output(["git","rev-parse","origin/main"], text=True).strip(), "Newchanlun/NewChanlun")
def run_one(qid, search, regex, paths):
    results=[]
    for ix, word in enumerate(search, 1):
        cmd=["gh","issue","list","--repo",repo,"--state","all","--search",word,"--limit","100","--json","number,state,title,url"]
        proc=subprocess.run(cmd, text=True, capture_output=True, check=True)
        hits=json.loads(proc.stdout)
        (root/"queries"/f"{qid}.tracker{ix}.json").write_text(json.dumps(hits, ensure_ascii=False, indent=2)+"\n")
        results.append(dict(channel="tracker",query=word,command=shlex.join(cmd),hits=len(hits)))
    cmd=["git","grep","-nE",regex,repo_rev,"--",*paths]
    proc=subprocess.run(cmd, text=True, capture_output=True)
    assert proc.returncode in (0,1), proc.stderr
    hits=proc.stdout.splitlines()
    (root/"queries"/f"{qid}.repo.txt").write_text(proc.stdout)
    results.append(dict(channel="repo",query=regex,command=shlex.join(cmd),hits=len(hits)))
    return qid,results

with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
    jobs=[ex.submit(run_one, qid, *data) for qid,data in queries.items()]
    results=dict(job.result() for job in jobs)
(root/"queries.json").write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n")
