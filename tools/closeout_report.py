"""Validate closeout evidence separately from historical phase-two receipts."""
import copy
import html
import json
import math
from .evidence import require
from . import phase2_report
from .report import STAGES as BASE_STAGES
from .closeout_cases import validate_samples,CYCLES,RSS_DRIFT_KIB,READER_DWELL_SECONDS
EXTRA=('closeout','closeout-read',*(s+'-'+k for k in ('serving','release_intent') for s in ('prepare','prepare-read','schedule','finish','finish-read')),'closeout-cleanup')
STAGES=BASE_STAGES[:-2]+EXTRA+BASE_STAGES[-2:]

def baseline(v):
    b=copy.deepcopy(v);b['stages']=[s for s in v['stages'] if s['name'] in BASE_STAGES];return b

def verify(v):
    phase2_report.verify(baseline(v))
    require(tuple(s['name'] for s in v['stages'])==STAGES,'Missing closeout stage')
    require(all(s['exit_code']==0 and s['timed_out'] is False and not s.get('interrupted',False) and math.isfinite(s['seconds']) and s['seconds']>=0 for s in v['stages']),'Closeout failure/timeout')
    for k in ('native_unit','linux_unit'):
        require(v[k]['count']>=79 and all('test_closeout.CloseoutCases.'+name in v[k]['tests'] for name in ('test_documented_cli','test_receipt_exhaustion_preserves_stop_release','test_byte_exhaustion_preserves_stop_release','test_resource_checks_reject_restart_leaks_and_missing_observation','test_owned_snapshot_ignores_only_shared_free_space')),'Closeout portable tests missing')
    c=v['closeout'];require(c['passed'] is True and c['runtime']==v['provenance']['runtime'],'Closeout/runtime failed')
    require(tuple(x['name'] for x in c['cases'])==('documented_cli','receipt_capacity','logical_capacity','bounded_cycles') and all(x['passed'] is True and math.isfinite(x['seconds']) and x['seconds']>=0 for x in c['cases']),'Missing case')
    d={x['name']:x['details'] for x in c['cases']}
    require(d['documented_cli']==dict(installed_cli=True,barriers=False,query_count=40,pin_after_release=0,socket_mode='0600',socket_removed=True),'Documented workflow failed')
    for name,kind,code in [('receipt_capacity','receipts','RECEIPT_FULL'),('logical_capacity','logical_bytes','Refused')]:
        r=d[name];require(r['kind']==kind and r['refusal_code']==code and r['attempts'][-1]==dict(ok=False,code=code) and len(r['attempts'])>=2 and all(x==dict(ok=True,code=None) for x in r['attempts'][:-1]),'Wrong capacity challenge')
        require(r['inventory_preserved_on_refusal'] is r['receipts_preserved_on_refusal'] is r['stop_exit_proven'] is True and r['query_at_full']==40 and r['pin_before_stop']==1 and r['pin_after_release']==0 and r['logical_bytes_after_release']>0,'Unsafe refusal/cleanup')
        require(r['options']==dict(artifact_bytes=262144,headroom_bytes=65536,keep=8,**(dict(max_receipts=4) if kind=='receipts' else dict(budget_bytes=1300000))),'Undeclared capacity policy')
    r=d['bounded_cycles'];require(r['cycles']==CYCLES and r['reader_dwell_seconds']==READER_DWELL_SECONDS and r['restarts']==0 and r['warmup_cycles']==4 and r['rss_drift_allowance_kib']==RSS_DRIFT_KIB and r['retained_metadata_explained'] is True and r['long_term_qualification'] is False and r['ledger_rows']==40,'Unsupported endurance claim')
    validate_samples(r['samples'])
    require(len(r['cycle_seconds'])==CYCLES and all(math.isfinite(s) and s>=READER_DWELL_SECONDS for s in r['cycle_seconds']) and math.isfinite(r['seconds']) and r['seconds']>=sum(r['cycle_seconds']),'Invalid cycle timings')
    require([r['kind'] for r in v['reboots']]==['serving','release_intent'],'Missing reboot')
    for r in v['reboots']:
        require(r['boot_changed'] is True and r['polls'] and r['polls'][-1]['exit_code']==0 and r['polls'][-1]['timed_out'] is False,'Reboot not observed')
        d=r['details'];require(d['kind']==r['kind'] and d['boot_before']!=d['boot_after'] and len(d['boot_before'])==len(d['boot_after'])==36,'Boot identity not changed')
        require(d['journal_before']==d['journal_after_before_controller'] and len(d['journal_before']['sha256'])==64,'Shutdown cleanup masqueraded as recovery')
        before=d['journal_before']['rows'];require(len(before['restores'])==len(before['pins'])==1 and before['pins'][0][1]==1 and before['restores'][0][2]==('SERVING' if r['kind']=='serving' else 'RELEASING'),'Wrong preserved state')
        require(d['copy_hash_preserved_before_recovery'] is d['controller_killed_before_reboot'] is d['old_epoch_rejected'] is True and d['pin_after_release']==0 and d['state_after_recovery']==('READY' if r['kind']=='serving' else 'RELEASED') and d['query_count']==(40 if r['kind']=='serving' else None),'Formal recovery not proven')
    require(v['closeout_cleanup']==dict(no_product_processes_remaining=True),'Closeout processes retained')
    require(v['limits']==dict(normal_vm_reboot_tested=True,power_loss_tested=False,long_term_gc_tested=False,systemd_package_tested=False),'Unsupported scope')
    return True

def controls(v):
    mutations=[lambda x:x['stages'].pop(12),lambda x:x['stages'][12].update(timed_out=True),lambda x:x['closeout'].update(passed=False),lambda x:x['closeout']['cases'].pop(),lambda x:x['closeout']['cases'][0]['details'].update(installed_cli=False),lambda x:x['closeout']['cases'][1]['details'].update(pin_after_release=1),lambda x:x['closeout']['cases'][2]['details'].update(inventory_preserved_on_refusal=False),lambda x:x['closeout']['cases'][3]['details'].update(restarts=1),lambda x:x['closeout']['cases'][3]['details']['samples'].pop(),lambda x:x['closeout']['cases'][3]['details']['samples'][-1].update(rss_kib=999999),lambda x:x['closeout']['cases'][3]['details']['samples'][-1].update(children=1),lambda x:x['reboots'][0]['details'].update(boot_after=x['reboots'][0]['details']['boot_before']),lambda x:x['reboots'][0]['details']['journal_after_before_controller'].update(sha256='0'*64),lambda x:x['reboots'][1]['details']['journal_before']['rows']['restores'][0].__setitem__(2,'RELEASED'),lambda x:x['reboots'][1]['details'].update(old_epoch_rejected=False),lambda x:x['closeout_cleanup'].update(no_product_processes_remaining=False),lambda x:x['limits'].update(power_loss_tested=True)]
    mutations += [lambda x:x['closeout']['cases'][3]['details'].update(reader_dwell_seconds=0),lambda x:x['closeout']['cases'][3]['details']['cycle_seconds'].__setitem__(0,.1)]
    for mutate in mutations:
        b=copy.deepcopy(v);mutate(b)
        try:verify(b)
        except (ValueError,KeyError,TypeError):continue
        raise ValueError('Corrupted closeout evidence accepted')
    return dict(passed=True,rejected=len(mutations),baseline_rejected=phase2_report.controls(baseline(v))['rejected'])

def render(v):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>Keepweft bounded closeout</title><style>body{font:16px system-ui;max-width:1050px;margin:40px auto;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>Keepweft: installed workflow, capacity and normal reboot</h1><p>Passed: '+str(v.get('passed',False))+'</p><p>Fresh isolated Linux VM, installed wheel with source imports removed. Documented CLI, separate receipt/soft-byte rejection, 24 same-controller cycles with 5-second reader dwell each, and two normal guest reboots. Persistent catalog is compared before reboot and after boot before controller recovery. RSS is sampled Linux VM process RSS, not peak/physical/native performance. Metadata intentionally grows with retained tombstones/guards; no unlimited endurance, automated GC, systemd packaging, sudden-power-loss or boot zero-gap qualification. Historical phase-two case-group flags apply only to that case group.</p><pre>'+html.escape(json.dumps(v,indent=2,allow_nan=False))+'</pre></html>'
