"""Fail-closed correspondence checks; metrics stay observations, never guarantees."""
import copy,html,json,math
from .evidence import require,fingerprint
from .build_sqlite import C_SHA3,URL
STAGES=('initial','create','dependencies','upload','runtime','install','provenance','native','linux','linux-read','explore','guest-read','delete','final')
NAMES=('A_snapshot_cancel','B_sealed_restore','C_publication_takeover','D_capacity_repair')

def verify(v):
    require(v['passed'] is True and v['source_changed'] is False and fingerprint(v['source'])==v['source_sha256'],'Failed/changed source')
    require(tuple(s['name'] for s in v['stages'])==STAGES,'Missing/reordered stage')
    require(all(s['exit_code']==0 and s['timed_out'] is False and not s.get('interrupted',False) and math.isfinite(s['seconds']) and s['seconds']>=0 for s in v['stages']),'Failed/timed-out stage')
    require(v['fresh_profile'] is True and v['initial_disk_absent'] is True and v['host_mounts']=='none' and v['vm_final']=='Deleted' and v['data_disk_removed'] is True and v['preexisting_profiles_unchanged'] is True,'VM isolation/cleanup failed')
    for k,system in (('native_unit','Darwin'),('linux_unit','Linux')):
        r=v[k];require(r['passed'] is True and r['platform']==system and r['source_sha256']==v['source_sha256'] and r['count']==len(r['tests'])==len(set(r['tests'])) and r['count']>=24 and r['failures']==r['errors']==r['skipped']==0,'Portable suite failed/detached')
    require(v['native_unit']['tests']==v['linux_unit']['tests'],'Different portable tests')
    p=v['provenance'];require(p['source_package_absent'] is True and p['location'].startswith('/usr/local/lib/python3.12/') and p['modules']=={k:h for k,h in v['source'].items() if k.startswith('keepweft/')} and p['library_sha256']==v['sqlite_build']['library_sha256'],'Installed implementation detached')
    require(v['sqlite_build']['url']==URL and v['sqlite_build']['source_sha3_256']==C_SHA3 and p['runtime']['python_sqlite']=='3.54.1','Unqualified Linux SQLite')
    require(v['wheel_product_matches'] is True,'Wheel/source mismatch')
    g=v['guest'];require(g['passed'] is True and g['source_sha256']==v['source_sha256'] and g['runtime']==p['runtime'] and g['owned_children_exited'] is True and g['no_worker_processes_remaining'] is True,'Guest/source/cleanup failed')
    require(tuple(c['name'] for c in g['cases'])==NAMES and all(c['passed'] is True and math.isfinite(c['seconds']) and c['seconds']>=0 for c in g['cases']),'Missing scenario')
    ds={c['name']:c['details'] for c in g['cases']};a=ds[NAMES[0]]
    require(a['snapshot']['expected']['count']==a['snapshot']['expected']['max_seq']==192 and a['source_count_after']==224 and a['uncommitted_excluded'] is True and a['writer_commits']==32 and a['wal_while_reader_bytes']>a['wal_before_bytes']>=0 and a['reader_released'] is True,'Snapshot boundary/writer evidence wrong')
    require([c['kind'] for c in a['cancellations']]==['cancel','timeout'] and all(c['answer']['ok'] is False and c['worker_exited'] is True and c['staging_empty'] is True for c in a['cancellations']),'Cancellation faked success/cleanup')
    b=ds[NAMES[1]];require(b['source_count_after_backup']==81 and b['restored_copy_distinct'] is True and b['standalone_main_file'] is True and b['read_only_write_rejected'] is True and b['application']['count']==b['application']['max_seq']==80 and all(type(b[k]) in (int,float) and math.isfinite(b[k]) and b[k]>0 for k in ('backup_seconds','restore_to_first_HTTP_seconds')),'Sealed/application evidence failed')
    require([x['kind'] for x in b['negatives']]==['missing','wrong-uuid','foreign-key','schema','truncated','wrong-watermark'] and all(x['rejected'] is True for x in b['negatives']),'Missing invalid-input refusal')
    require(b['resources']['controller']['rss_kib']>0 and b['resources']['view']['rss_kib']>0 and b['resources']['store']['allocated_bytes']>0,'Missing real resource observations')
    cases=ds[NAMES[2]]['cases'];points=('copy_complete','publish_intent','after_rename','after_catalog','restore_materialized','delete_intent','after_unlink')
    require(tuple(c['point'] for c in cases)==points,'Missing crash cut')
    for c in cases:
        require(c['owner_killed'] is True and c['recovered'] is True and c['retired_attempt_rejected'] is True and c['staging_empty'] is True,'Crash/recovery mismatch')
        require(c['available']==(0 if c['point']=='copy_complete' else 2 if c['point']=='restore_materialized' else 1),'Lost/duplicate publication')
        if c['point']=='copy_complete':require(c['worker_lock_blocked_takeover'] is True,'Live writer takeover allowed')
        require(len(c['stale'])==2 and all(s['rejected'] is True for s in c['stale']),'Missing stale refusal')
        old_epoch,old_revision=c['stale']
        require(old_epoch['token']['epoch']<old_epoch['current']['epoch'] and old_epoch['token']['revision']==old_epoch['current']['revision'] and old_revision['token']['epoch']==old_revision['current']['epoch'] and old_revision['token']['revision']<old_revision['current']['revision'],'Confounded stale dimensions')
    d=ds[NAMES[3]];f=d['enospc'];r=d['readonly'];s=d['sqlite_full']
    require(f['real_errno']==28 and f['filler_bytes']>0 and f['at_full']['filesystem_free_bytes']==0 and f['failed_command']['ok'] is False and f['failed_command']['error']=='Refused' and type(f['failed_command']['sqlite_errorcode']) is int and f['failed_command']['sqlite_errorcode']&255 in (10,13,14) and f['startup_refused'] is True and f['previous_hash_preserved'] is True and f['diagnostic_mode']=='READ_ONLY_DIAGNOSTIC' and f['repair_backup_count']==160 and f['stale_rejected'] is True,'ENOSPC/repair not proven')
    require(r['real_remount'] is True and r['readonly_bind_mount'] is True and r['os_errno']==30 and type(r['inflight_sqlite_errorcode']) is int and r['inflight_sqlite_errorcode']&255 in (8,10,14) and r['retired_mutation_refused'] is True and r['reply']['ok'] is False and r['previous_hash_preserved'] is True and r['repair_succeeded'] is True,'Readonly/repair failed')
    require(s['actual_sqlite_errorcode']==13 and s['retired_controller'] is True and s['new_mutation_refused'] is True and s['explicit_reopen_repair'] is True and s['repair_backup_count']==160 and d['loop_unmounted'] is True and d['loop_device_detached'] is True,'SQLite FULL/loop cleanup failed')
    require(g['limits']==dict(power_loss_tested=False,vm_reboot_tested=False,hardware_tested=False,production_switch_tested=False),'Untested claims')
    return True

def controls(v):
    mutations=[lambda x:x.update(passed=False),lambda x:x.update(source_changed=True),lambda x:x['stages'].pop(),lambda x:x['stages'][0].update(timed_out=True),lambda x:x['stages'][0].update(exit_code=1),lambda x:x.update(data_disk_removed=False),lambda x:x.update(initial_disk_absent=False),lambda x:x['provenance'].update(source_package_absent=False),lambda x:x['provenance']['modules'].clear(),lambda x:x['sqlite_build'].update(source_sha3_256='0'*64),lambda x:x['linux_unit']['tests'].pop(),lambda x:x['guest'].update(no_worker_processes_remaining=False),lambda x:x['guest']['cases'][0]['details'].update(source_count_after=192),lambda x:x['guest']['cases'][0]['details']['cancellations'][0]['answer'].update(ok=True),lambda x:x['guest']['cases'][1]['details'].update(read_only_write_rejected=False),lambda x:x['guest']['cases'][2]['details']['cases'][0].update(worker_lock_blocked_takeover=False),lambda x:x['guest']['cases'][2]['details']['cases'][1]['stale'][0]['token'].update(revision=-1),lambda x:x['guest']['cases'][3]['details']['enospc']['failed_command'].update(ok=True),lambda x:x['guest']['cases'][3]['details']['sqlite_full'].update(actual_sqlite_errorcode=0),lambda x:x['guest']['cases'][3]['details'].update(loop_unmounted=False),lambda x:x['guest']['limits'].update(power_loss_tested=True)]
    mutations += [lambda x:x['guest']['cases'][3]['details']['enospc']['failed_command'].update(error='JSONDecodeError',sqlite_errorcode=None),lambda x:x['guest']['cases'][3]['details']['readonly'].update(inflight_sqlite_errorcode=0)]
    mutations += [lambda x:x['guest']['cases'][1]['details'].update(source_count_after_backup=80)]
    for mutate in mutations:
        b=copy.deepcopy(v);mutate(b)
        try:verify(b)
        except (ValueError,KeyError,TypeError):pass
        else:raise ValueError('Invalid evidence accepted')
    return dict(passed=True,rejected=len(mutations))

def render(v):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>Keepweft technical explorations</title><style>body{font:16px system-ui;max-width:1050px;margin:40px auto;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>Keepweft: four technical explorations</h1><p>Passed: '+str(v.get('passed',False))+'</p><p>Installed minimal core in an isolated Linux VM. Barriers deliberately control snapshot/crash timing. Recorded RSS values are process snapshots, not peaks; timings are single controlled observations, not outage guarantees or performance comparisons. No VM reboot, abrupt power loss, hardware or production cutover qualification.</p><h2>Complete evidence</h2><pre>'+html.escape(json.dumps(v,indent=2,allow_nan=False))+'</pre></html>'
