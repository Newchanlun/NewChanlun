"""#1429：提取 9011 样本指定构造器记录或用最小输入对照子窗 Zn；不调用塔。"""
import json
import sys
from pathlib import Path


def src(dir_):
    with (dir_ / 'objects.jsonl').open() as f:
        rows = [(i, json.loads(t)) for i, t in enumerate(f, 1)]
    bars = json.loads((dir_ / 'inputs/source.bars.frozen.json').read_text())
    assert len(bars) == 9011
    index = {(o['kind'], o['payload']['data'].get('entity_id')): (i, o) for i, o in rows}
    def get(kind, name):
        i, o = index[kind, name]
        return {'line': i, 'id': o['id']}, o['payload']['data']
    parent = 'center:1:301'
    pairid = 'pair:1:301:1:1262'
    c_ref, c = get('CC-016.center', parent)
    p_ref, p = get('CC-020.center_pair', pairid)
    _, right = get('CC-016.center', p['b_center_id'])
    r_ref, roles = get('CC-017.center_roles', c['roles_id'])
    large = [o['payload']['data']['entity_id'] for _, o in rows if o['kind']=='CC-016.center' and len(o['payload']['data']['members'])>=9]
    assert large == [parent]
    units=[]
    for uid in c['members']+p['connector_units']:
        ax, a = get('CC-022.unit_assignment', 'assign:'+uid)
        sx, s = get('CC-013.segment', uid)
        assert a['unit']['unit_object_id']==sx['id'] and s['fact_vector']['segment_broken']
        start=int(s['construction']['start_stroke'])
        end=int(s['geometric_end']['stroke_index'])
        refs=[r for r in s['stroke_refs'] if start<=int(r['stroke_index'])<=end]
        assert [int(r['stroke_index']) for r in refs]==list(range(start,end+1))
        assert all((r['end_anchor'],r['end_price'])==(t['start_anchor'],t['start_price']) for r,t in zip(refs,refs[1:]))
        def point(anchor, price):
            i=int(anchor); bar=bars[i]; value=int(price)
            assert bar['source_index']==i and value in (bar['low'],bar['high'])
            return [i,value]
        points=[point(r['start_anchor'],r['start_price']) for r in refs]+[point(refs[-1]['end_anchor'],refs[-1]['end_price'])]
        lo,hi=min(q for _,q in points),max(q for _,q in points)
        assert (lo,hi)==tuple(sorted((points[0][1],points[-1][1])))==(int(a['unit']['lo']),int(a['unit']['hi']))
        direct='UP' if points[-1][1]>points[0][1] else 'DOWN'
        assert direct==a['unit']['direction']==s['construction']['direction']
        assert (points[1][1]-points[0][1])*(points[2][1]-points[1][1])<0
        assert points[-1]==[int(s['geometric_end']['group_anchor']),int(s['geometric_end']['price'])]
        units.append({'unit':uid,'segment_record':sx,'assignment_record':ax,'status':a['status'],'reason':a['reason'],
                      'assigned_center':a['center_id'],'left':a['left_center_id'],'right':a['right_center_id'],
                      'geometric_end':points[-1],'first_three_points':points[:3],'source_direction':direct,'source_range':[lo,hi]})
    assert set(p['connector_units']).isdisjoint(c['members']+right['members'])
    assert c['break_unit']==p['connector_units'][0] and c['resume_anchor']=={'after_unit_id':c['members'][-1],'offset':'2'}
    return {'candidate':'68f7eb9dfef6b130b270071ffcc8b4d8191c74ed','snapshot_kind':'9011 final C/D and E/F constructor output','parent':parent,'center_record':c_ref,
            'parents_with_9_or_more':large,'parent_direction':c['zn_direction'],'parent_seed':c['seed_units'],'parent_members':c['members'],'resume_anchor':c['resume_anchor'],
            'roles_record':r_ref,'source_core':[int(roles['roles']['CORE'][k]['value']) for k in ('ZD','ZG')],'source_outer':roles['roles']['OUTER'],
            'pair':pairid,'pair_record':p_ref,'source_pair_status':p['status'],'source_pair_leaf':p['leaf'],'source_realization':p['realization'],
            'connector':p['connector_units'],'following_seed':right['seed_units'],'units':units}


def calc(doc):
    by={u['unit']:u for u in doc['units']}
    whole=[by[k] for k in doc['parent_members']]
    values={}
    for u in doc['units']:
        ps=u['first_three_points']; a,b,c=[p[1] for p in ps]
        assert (b-a)*(c-b)<0
        start=u['first_three_points'][0][1]; end=u['geometric_end'][1]
        lo,hi=sorted((start,end))
        assert [lo,hi]==u['source_range'] and lo<hi
        values[u['unit']]=(lo,hi,'UP' if end>start else 'DOWN')
    assert all(u['geometric_end']==v['first_three_points'][0] for u,v in zip(whole,whole[1:]))
    def evaluate(win):
        ids=[u['unit'] for u in win]; seed=ids[:3]
        def metrics(members):
            def stat(idx,fn):
                val=fn(values[k][idx] for k in members)
                return {'value':val,'contributors':[k for k in members if values[k][idx]==val]}
            return {'selected':members,'DD':stat(0,min),'GG':stat(1,max),'D':stat(0,max),'G':stat(1,min)}
        zd=max(values[k][0] for k in seed); zg=min(values[k][1] for k in seed)
        return {'window':ids,'core':[zd,zg],'strict_core':zd<zg,
                'local_seed':metrics([k for k in ids if values[k][2]==values[seed[0]][2]]),
                'parent_seed':metrics([k for k in ids if values[k][2]==doc['parent_direction']]),
                'all_units':metrics(ids)}
    windows=[evaluate(whole[i:i+3]) for i in (0,3,6)]
    assert windows[0]['core']==doc['source_core']
    return {'first_nine':windows,'unconsumed_by_first_nine':[u['unit'] for u in whole[9:]],
            'last_window_if_two_remaining_members_assigned_as_extension':evaluate(whole[6:]),
            'connector':doc['connector'],'following_seed':doc['following_seed']}


if __name__=='__main__':
    mode,arg=sys.argv[1:]
    if mode=='extract': result=src(Path(arg))
    elif mode=='calc': result=calc(json.loads(Path(arg).read_text()))
    else: raise SystemExit('用法：extract 原件目录 | calc input.json')
    print(json.dumps(result,ensure_ascii=False,indent=2))
