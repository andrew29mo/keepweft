"""Fail-closed phase-one evidence contract; historical exploration receipts unchanged."""
import copy
import html
import json
import math
from .evidence import require,fingerprint
from .build_sqlite import URL,C_SHA3
from .report import STAGES
from .phase1_cases import CASES

def verify(v):
    require(v['passed'] is True and v['source_changed'] is False and fingerprint(v['source'])==v['source_sha256'],'Failure/source drift')
    require(tuple(s['name'] for s in v['stages'])==STAGES,'Missing/reordered stage')
    require(all(s['exit_code']==0 and s['timed_out'] is False and not s.get('interrupted',False) and math.isfinite(s['seconds']) and s['seconds']>=0 for s in v['stages']),'Failure/timeout')
    require(v['fresh_profile'] is True and v['initial_disk_absent'] is True and v['host_mounts']=='none' and v['vm_final']=='Deleted' and v['data_disk_removed'] is True and v['preexisting_profiles_unchanged'] is True,'Isolation/cleanup')
    for k,system in (('native_unit','Darwin'),('linux_unit','Linux')):
        r=v[k];require(r['passed'] is True and r['platform']==system and r['source_sha256']==v['source_sha256'] and r['count']==len(r['tests'])==len(set(r['tests'])) and r['count']>=55 and r['failures']==r['errors']==r['skipped']==0,'Portable tests missing/failed')
        require(all('test_requests.ServiceCases.test_'+name in r['tests'] for name,_ in CASES),'Formal service tests absent')
    require(v['native_unit']['tests']==v['linux_unit']['tests'],'Different tests')
    p=v['provenance'];require(p['source_package_absent'] is True and p['location'].startswith('/usr/local/lib/python3.12/') and p['modules']=={k:h for k,h in v['source'].items() if k.startswith('keepweft/')} and p['library_sha256']==v['sqlite_build']['library_sha256'] and v['wheel_product_matches'] is True,'Installed source mismatch')
    require(v['sqlite_build']['url']==URL and v['sqlite_build']['source_sha3_256']==C_SHA3 and p['runtime']['python_sqlite']=='3.54.1','SQLite runtime')
    g=v['guest'];require(g['passed'] is True and g['source_sha256']==v['source_sha256'] and g['runtime']==p['runtime'] and g['owned_services_exited'] is True and type(g['owned_service_count']) is int and g['owned_service_count']>0 and g['no_service_or_worker_processes_remaining'] is True,'Guest/source/cleanup mismatch')
    require(tuple(c['name'] for c in g['cases'])==tuple(n for n,_ in CASES) and all(c['passed'] is True and math.isfinite(c['seconds']) and c['seconds']>=0 for c in g['cases']),'Missing/failed scenario')
    d={c['name']:c['details'] for c in g['cases']}
    a=d['dedup_restart'];require(a['state']=='AVAILABLE' and a['same_operation'] is True and a['objects']==1 and a['conflict']=='CONFLICT' and a['old_epoch_new_key']=='RETIRED' and a['restart_replay_readonly'] is True,'Dedup/restart')
    a=d['receipt_refusal'];require(a==dict(receipt_limit=2,available_preserved=2,hashes_preserved=True,refusal_before_prune=True),'Pre-admission deletion')
    a=d['saturated_cancel'];require(a['queue_limit']==1 and a['receipt_limit']==2 and a['full_code']=='RECEIPT_FULL' and a['rotation']=='BUSY' and a['queued_cancel']=='CANCELLED' and a['active_cancel']=='CANCEL_ACCEPTED' and a['terminal']=='CANCELLED' and a['objects']==0 and a['staging_empty'] is True and math.isfinite(a['status_seconds']) and a['status_seconds']>=0,'Saturated cancel')
    a=d['cancel_before_intent'];require(a==dict(point='before_publish',cancel='CANCEL_ACCEPTED',state='CANCELLED',objects=0,restart_after_intent=False),'Cancel before intent')
    a=d['cancel_after_intent'];require(a==dict(point='publish_intent',cancel='TOO_LATE',state='AVAILABLE',objects=1,restart_after_intent=True),'Cancel after intent')
    a=d['generation_gc'];require(a['completed_rollovers']==4 and len(a['retained_receipts_after_each'])==3 and all(type(x) is int and 0<=x<=1 for x in a['retained_receipts_after_each']) and a['forgotten_submit']=='RETIRED' and a['forgotten_lookup']=='RESULT_GONE' and a['crash_after_advance'] is True and a['old_key_after_crash']=='RETIRED' and a['no_new_objects'] is True,'GC replay')
    for name,point,state,count in [('lost_admission','admitted','FAILED',0),('lost_rename','after_rename','AVAILABLE',1),('lost_catalog','after_catalog','AVAILABLE',1)]:
        require(d[name]==dict(point=point,response_not_read=True,same_operation=True,state=state,objects=count),'Lost-response replay')
    require(d['cancel_crash']==dict(cancel_durable_before_kill=True,state='CANCELLED',objects=0),'Cancel recovery')
    require(d['deadline']==dict(state='FAILED',objects=0,staging_empty=True),'Timeout fake success')
    require(d['retention_crash']==dict(state='FAILED',deleted_attributed=True,latest_preserved=True,objects=1),'Retention attribution crash')
    require(g['limits']==dict(vm_reboot_tested=False,power_loss_tested=False,managed_reader_tested=False,scheduler_tested=False),'Unsupported claims')
    return True

def controls(v):
    mutations=[lambda x:x.update(passed=False),lambda x:x.update(source_changed=True),lambda x:x['stages'].pop(),lambda x:x['stages'][0].update(timed_out=True),lambda x:x['stages'][0].update(exit_code=1),lambda x:x.update(data_disk_removed=False),lambda x:x.update(host_mounts='host source'),lambda x:x['provenance']['modules'].clear(),lambda x:x['linux_unit']['tests'].pop(),lambda x:x['guest']['cases'][0]['details'].update(objects=2),lambda x:x['guest']['cases'][1]['details'].update(refusal_before_prune=False),lambda x:x['guest']['cases'][2]['details'].update(active_cancel='RECEIPT_FULL'),lambda x:x['guest']['cases'][3]['details'].update(objects=1),lambda x:x['guest']['cases'][4]['details'].update(cancel='CANCEL_ACCEPTED'),lambda x:x['guest']['cases'][5]['details'].update(old_key_after_crash='AVAILABLE'),lambda x:x['guest']['cases'][6]['details'].update(same_operation=False),lambda x:x['guest']['cases'][9]['details'].update(state='AVAILABLE'),lambda x:x['guest']['cases'][10]['details'].update(state='AVAILABLE'),lambda x:x['guest']['limits'].update(power_loss_tested=True),lambda x:x['guest']['cases'][11]['details'].update(deleted_attributed=False),lambda x:x['guest'].update(no_service_or_worker_processes_remaining=False)]
    for change in mutations:
        b=copy.deepcopy(v);change(b)
        try:verify(b)
        except (ValueError,KeyError,TypeError):continue
        raise ValueError('Corrupted evidence accepted')
    return dict(passed=True,rejected=len(mutations))

def render(v):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>Keepweft phase one</title><style>body{font:16px system-ui;max-width:1050px;margin:40px auto;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>Keepweft phase one: requests, generations and cancellation</h1><p>Passed: '+str(v.get('passed',False))+'</p><p>Actual installed service/worker processes in a fresh isolated Linux VM. Controlled SIGKILL and scheduling barriers, not VM reboot or power loss. Timings are observations, not performance/SLO claims. Managed readers and scheduling remain unimplemented. Historical four-exploration evidence is separate.</p><pre>'+html.escape(json.dumps(v,indent=2,allow_nan=False))+'</pre></html>'
