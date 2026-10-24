"""Fail-closed installed reader evidence. No model consensus used as proof."""
import copy
import html
import json
import math
from .evidence import require,fingerprint
from .build_sqlite import URL,C_SHA3
from .report import STAGES
from .phase2_cases import CASES,VM_CASES

def verify(v):
    require(v['passed'] is True and v['source_changed'] is False and fingerprint(v['source'])==v['source_sha256'],'Failure/source drift')
    require(tuple(s['name'] for s in v['stages'])==STAGES,'Missing/reordered stage')
    require(all(s['exit_code']==0 and s['timed_out'] is False and not s.get('interrupted',False) and math.isfinite(s['seconds']) and s['seconds']>=0 for s in v['stages']),'Failure/timeout')
    require(v['fresh_profile'] is True and v['initial_disk_absent'] is True and v['host_mounts']=='none' and v['vm_final']=='Deleted' and v['data_disk_removed'] is True and v['preexisting_profiles_unchanged'] is True,'Isolation/cleanup')
    for k,system in (('native_unit','Darwin'),('linux_unit','Linux')):
        r=v[k];require(r['passed'] is True and r['platform']==system and r['source_sha256']==v['source_sha256'] and r['count']==len(r['tests'])==len(set(r['tests'])) and r['count']>=72 and r['failures']==r['errors']==r['skipped']==0,'Portable tests missing/failed')
        require(all('test_readers.ServiceReaderCases.test_'+name in r['tests'] for name,_ in CASES),'Formal reader tests absent')
        require('test_readers.ReaderFailures.test_service_status_bounds_history_and_keeps_active_reference' in r['tests'],'Bounded status test absent')
        require('test_readers.ReaderFailures.test_missing_copy_still_requires_parent_sync_before_unpin' in r['tests'],'Release sync failure test absent')
    require(v['native_unit']['tests']==v['linux_unit']['tests'],'Different tests')
    p=v['provenance'];require(p['source_package_absent'] is True and p['location'].startswith('/usr/local/lib/python3.12/') and p['modules']=={k:h for k,h in v['source'].items() if k.startswith('keepweft/')} and p['library_sha256']==v['sqlite_build']['library_sha256'] and v['wheel_product_matches'] is True,'Installed source mismatch')
    require(v['sqlite_build']['url']==URL and v['sqlite_build']['source_sha3_256']==C_SHA3 and p['runtime']['python_sqlite']=='3.54.1','SQLite runtime')
    g=v['guest'];require(g['passed'] is True and g['source_sha256']==v['source_sha256'] and g['runtime']==p['runtime'] and g['owned_services_exited'] is True and g['owned_service_count']>0 and g['no_service_or_worker_processes_remaining'] is True,'Guest/source/cleanup mismatch')
    require(tuple(c['name'] for c in g['cases'])==tuple(n for n,_ in VM_CASES) and all(c['passed'] is True and math.isfinite(c['seconds']) and c['seconds']>=0 for c in g['cases']),'Missing/failed scenario')
    d={c['name']:c['details'] for c in g['cases']}
    r=d['roundtrip'];require(r['count']==40 and r['hash_preserved'] is True and r['pin_while_serving']==1 and r['pin_after_release']==0 and r['release_refused_while_serving'] is True and r['stale_revision_rejected_with_free_guard'] is True and r['missing_token_rejected'] is True,'Roundtrip/pin')
    for key in ('start_to_query_seconds','reader_rss_kib','controller_rss_kib','managed_logical_bytes_while_serving'):
        require(type(r[key]) in (float,int) and math.isfinite(r[key]) and r[key]>0,'Invalid measurement')
    require(d['controller_orphan']==dict(controller_sigkill=True,global_controller_recovered=True,orphan_state='ORPHAN_BUSY',reader_query_after_restart=40,paused_reader_retained=True,stale_release_rejected=True,unknown_pid_not_signalled=True,pin_after_proven_exit=0),'Lost occupancy/stale mutation')
    for name,point,state in [('before_spawn','reader_before_spawn','READY'),('after_spawn','reader_after_spawn','ORPHAN_BUSY')]:
        require(d[name]==dict(barrier_seen=point,state_after_restart=state,pin_after_restart=1,pin_after_release=0),'Spawn handoff')
    require(d['release_intent']==dict(barrier_seen='reader_release_intent',copy_present_before_restart=True,state_after_restart='RELEASED',pin_after_restart=0),'Release intent recovery')
    require(d['stop_timeout']==dict(stop_timeout_not_exit=True,pin_after_timeout=1,release_refused=True,pin_after_exit=0),'Timeout treated as death')
    for name,crash in [('missing_ready_crash',True),('readiness_timeout',False)]:
        require(d[name]==dict(barrier_seen='reader_before_ready',ready_absent=True,controller_crashed=crash,pin_before_exit=1,pin_after_release=0,deadline_error=None if crash else 'TimeoutError'),'Missing handshake treated as exit/success')
    require(d['readonly_release']==dict(os_errno=30,pin_before_repair=1,restart_refused=True,pin_after_repair=0,readonly_mount_removed=True),'Readonly repair')
    require(g['limits']==dict(vm_reboot_tested=False,power_loss_tested=False,reader_adoption_tested=False,long_term_gc_tested=False),'Unsupported claims')
    return True

def controls(v):
    changes=[lambda x:x.update(passed=False),lambda x:x.update(source_changed=True),lambda x:x['stages'].pop(),lambda x:x['stages'][0].update(timed_out=True),lambda x:x['stages'][0].update(exit_code=1),lambda x:x.update(data_disk_removed=False),lambda x:x.update(host_mounts='host'),lambda x:x['provenance']['modules'].clear(),lambda x:x['linux_unit']['tests'].pop(),lambda x:x['guest']['cases'][0]['details'].update(pin_while_serving=0),lambda x:x['guest']['cases'][0]['details'].update(start_to_query_seconds=float('nan')),lambda x:x['guest']['cases'][1]['details'].update(orphan_state='READY'),lambda x:x['guest']['cases'][1]['details'].update(stale_release_rejected=False),lambda x:x['guest']['cases'][2]['details'].update(barrier_seen=None),lambda x:x['guest']['cases'][3]['details'].update(state_after_restart='READY'),lambda x:x['guest']['cases'][4]['details'].update(copy_present_before_restart=False),lambda x:x['guest']['cases'][5]['details'].update(stop_timeout_not_exit=False),lambda x:x['guest']['cases'][8]['details'].update(pin_before_repair=0),lambda x:x['guest']['cases'][8]['details'].update(os_errno=13),lambda x:x['guest'].update(no_service_or_worker_processes_remaining=False),lambda x:x['guest']['limits'].update(power_loss_tested=True),lambda x:x['guest']['limits'].update(vm_reboot_tested=True)]
    changes += [lambda x:x['guest']['cases'][6]['details'].update(ready_absent=False),lambda x:x['guest']['cases'][7]['details'].update(deadline_error='Refused')]
    changes += [lambda x:x['guest']['cases'][0]['details'].update(stale_revision_rejected_with_free_guard=False),lambda x:x['guest']['cases'][0]['details'].update(missing_token_rejected=False)]
    for change in changes:
        b=copy.deepcopy(v);change(b)
        try:verify(b)
        except (ValueError,KeyError,TypeError):continue
        raise ValueError('Corrupted evidence accepted')
    return dict(passed=True,rejected=len(changes))

def render(v):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>Keepweft guarded restore</title><style>body{font:16px system-ui;max-width:1050px;margin:40px auto;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>Keepweft: one restored copy and managed reader</h1><p>Passed: '+str(v.get('passed',False))+'</p><p>Installed service and reader in an isolated Linux VM. SIGKILL, SIGSTOP, spawn/release barriers, real EROFS and repair. VM timings/RSS are point observations, not native performance or an SLO. No VM reboot, sudden power loss, orphan adoption or long-term GC qualification.</p><pre>'+html.escape(json.dumps(v,indent=2,allow_nan=False))+'</pre></html>'
