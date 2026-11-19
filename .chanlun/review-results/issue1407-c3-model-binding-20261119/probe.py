"""一次模拟；冻结 FIN/5 不变，X maker.numerator 由 1 变 10。启动所有域的是 production_session。"""
import os,sys
from pathlib import Path
product=Path(sys.argv.pop(1)).resolve()
original=product/'rust/tests/c2_formal_entry.py'
sys.path.insert(0,str(original.parent))
source=original.read_text()
def piece(a,b):
    assert source.count(a)==1 and source.count(b)==1
    return source[source.index(a):source.index(b)]
setup=piece('    model_config =','    xp = command("serve-x"')
setup=setup.replace('    pp = write','    assert model_config["fee_profile"]["maker"]["numerator"]==1\n    model_config["fee_profile"]["maker"]["numerator"]=10\n    pp = write')
launch='''
    sys.path.insert(0,str(src/"s_session/tests"))
    from r4_anchor_fixture import TestAnchor
    sd=run/'sd'; sd.mkdir(); db=sd/'s.db'
    dec=dict(category="TestOnlyStructure",namespaces=["testonly.ohlc"])
    df=write("decl.json",dec)
    clock=write("sclock.json",dict(schema_revision="s-clock-plan/1",clock_plan_id="pse-01",origin_utc="2000-01-01T00:00:00Z",unit="ns",events={"input-1":dict(accept_ns="10",attempts=[dict(begin_ns="11",commit_ns="12")])}))
    catalog=src/'s_session/catalog/signed-catalog.json'; profile=src/'s_session/profiles/ohlc_integer_tb02a_v1.json'
    command("s-init",[bins/'s_structure_session','init','--protocol-revision','s-session/3','--db',db,'--session',sid,'--catalog',catalog,'--profile',profile,'--session-generation',gen,'--clock-plan',clock,'--delivery-retain-generations','4','--structure-source',df])
    sstate=sd/'state'; sstate.mkdir()
    anchor=TestAnchor(db,sstate,limits=dict(max_total_wire_bytes='1073741824',max_total_node_bytes='1073741824',max_total_nodes='10000000',max_total_records='10000000',max_total_requests='1000000',max_elapsed_ms='600000',max_staged_bytes='67108864',max_store_bytes='1073741824'))
    os.environ.update(anchor.env())
    sres=write('s-resources.json',dict(schema_revision="s-structure-resources/1",s_resources=dict(max_frame_bytes="1048576",read_timeout_ms="1000",write_timeout_ms="1000",response_timeout_ms="30000",audit_cache_source_bytes="1048576",queue_capacity="2",max_connections="2")))
    control=write('production.json',dict(manifest_revision='production-session-manifest/1',profile='simulation',state_dir=str(run/'launcher-state'),execution_capabilities=dict(namespaces=['x-sim']),structure_source=dec,
        s=dict(db=str(db),session=sid,catalog=str(catalog),profile=str(profile),clock_plan=str(clock),session_generation=gen,delivery_retain_generations='4',admission_job_limits=str(anchor.limits_path),writer_epoch='1',socket=str(run/'structure.sock'),resource_config=str(sres)),
        economic=dict(manifest=str(path),e=dict(db=str(nodes['E']['db']),epoch='1'),b=[dict(chong=a,db=str(nodes['B:'+a]['db']),epoch='1') for a in ['alpha','beta']]),
        x=dict(db=str(run/'x.db'),profile=str(pp),writer_epoch='1')))
    xp=command("outer",[bins/'production_session','--manifest',control],expected=None)
    for addr in [n["socket"] for n in nodes.values()]+[x_socket]:
        wait_ready(xp,addr,"outer")
'''
final='''
    model_ref=release["record"]["model_ref"]
    print("PASS",json.dumps(dict(command_hash=release["record"]["command_hash"],release_receipt=release["receipt_key"],e_model=model_ref,x_model=filled["model_content_hash"],fee=filled["originals"][1]["event"]["amount"],counts=counts,retained=sum(int(r["amount"]) for r in liability))))
    assert filled["originals"][0]["event"]["fill"]["amount"]==28
    assert filled["originals"][1]["event"]["amount"]==3
    assert filled["model_content_hash"]!=model_ref["content_hash"]
'''
pre=source[:source.index('    for domain in nodes:\n        launcher("start", domain)')]
econ=piece('    for a, raw in opener.items():','    model_config =')
runtime=piece('    s_requests = []','    # Q 使用既有 HTTP')
cleanup=source[source.rindex('\nfinally:\n    for label, p in reversed(processes):'):]
script=pre+'    freeze=data["exact_release"]\n'+setup+launch+econ+runtime+final+cleanup
exec(compile(script,str(original)+'-model-contrast','exec'),dict(__name__="__main__",__file__=str(original),os=os))
