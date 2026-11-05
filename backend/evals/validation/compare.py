"""python -m evals.validation.compare --input run.json [--input ...] --out NEW_DIRECTORY"""
import argparse
import csv
import json
import math
import statistics
from pathlib import Path

SCHEMA = 'jobseeker-validation-v1'
KINDS = {'voice', 'face', 'gaze-phase0'}
EVIDENCE = {'synthetic-signal', 'public-fixture-real-model', 'human-device'}
FIELDS = {'schemaVersion','kind','evidence','runId','protocolVersion','methodVersion','configVersion','codeVersion','dirty','status','environment','denominators','metrics','verdicts','reasonCodes'}
ENV = {'browser','condition','delegate','os','viewportWidth','viewportHeight','cameraWidth','cameraHeight','devicePixelRatio'}
METRICS = {'samples','totalSec','analyzedSec','coverage','activeCandidateSec','silenceCandidateSec','silenceCandidateRatio','pauseCount','longPauseCount','longestPauseSec','syllables','totalPacePerMin','activeCandidatePacePerMin','fillerCount','answerMs','analyzedMs','detectedMs','inMs','edgeMs','noneMs','noneEpisodes','longestNoneMs','headMs','turnedMs','downMs','e50Relative','e50Px','e80Px','valAuc','lensForward','lensTurned','topFalse','screenFalse','validRatio','coldMs','warmP50Ms','warmP95Ms','cpuSec','peakRssMiB','realTimeFactor','cer','cleanupCycles','errorCount'}
REASONS = {'viewport_changed','resolution_changed','invalid_resolution','camera_error','user_aborted','model_error','sampling_gap','invalid_timestamp','invalid_duration','no_samples','partial_coverage','invalid_energy','clipping','low_energy','constant_energy','too_short','insufficient_samples'}
DENOMS = {'attempts','observed','accepted','samples','analyzedSec','totalSec','analyzedMs','answerMs','textUnits','syllables'}


def _finite(value):
    return value is None or (isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value))


def validate(a):
    if not isinstance(a,dict) or set(a) != FIELDS:raise ValueError('unknown or missing artifact fields')
    if a['schemaVersion'] != SCHEMA:raise ValueError('unknown schema version')
    if a['kind'] not in KINDS or a['evidence'] not in EVIDENCE:raise ValueError('unknown kind/evidence')
    if a['status'] not in {'complete','invalid','aborted','error'}:raise ValueError('unknown status')
    for key in ('runId','protocolVersion','methodVersion','configVersion','codeVersion'):
        value=a[key]
        if not isinstance(value,str) or not value or len(value)>160 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-' for c in value):raise ValueError('invalid '+key)
    if not isinstance(a['reasonCodes'],list) or any(not isinstance(r,str) or r not in REASONS for r in a['reasonCodes']):raise ValueError('unknown reason code')
    if not isinstance(a['dirty'],bool):raise ValueError('invalid dirty flag')
    env=a['environment']
    if not isinstance(env,dict) or not set(env)<=ENV or not {'browser','condition','delegate'}<=set(env):raise ValueError('invalid environment')
    for key,value in env.items():
        if key in {'browser','condition','delegate','os'}:
            if value is None:continue
            if not isinstance(value,str) or not value or len(value)>100 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._-/' for c in value):raise ValueError('invalid environment label')
        elif not _finite(value) or (value is not None and value<0):raise ValueError('invalid environment dimension')
    for name,allowed in [('metrics',METRICS),('denominators',DENOMS)]:
        obj=a[name]
        if not isinstance(obj,dict) or not set(obj)<=allowed:raise ValueError('unknown '+name)
        if any(not _finite(v) or (v is not None and v<0) for v in obj.values()):raise ValueError('invalid '+name)
    m=a['metrics']
    for key in ('samples','pauseCount','longPauseCount','syllables','fillerCount','noneEpisodes','cleanupCycles','errorCount'):
        if m.get(key) is not None and int(m[key])!=m[key]:raise ValueError('noninteger metric count')
    for key in ('coverage','silenceCandidateRatio','valAuc','lensForward','lensTurned','topFalse','screenFalse','validRatio'):
        if m.get(key) is not None and m[key]>1+1e-6:raise ValueError('ratio outside unit interval')
    for total,parts in [('detectedMs',('inMs','edgeMs')),('analyzedMs',('inMs','edgeMs','noneMs'))]:
        if all(m.get(k) is not None for k in (total,*parts)) and abs(m[total]-sum(m[k] for k in parts))>1e-6:raise ValueError('inconsistent metric totals')
    d=a['denominators']
    if d.get('attempts')!=1:raise ValueError('each artifact is exactly one attempt')
    for key in ('attempts','observed','accepted','samples','textUnits','syllables'):
        if d.get(key) is not None and int(d[key])!=d[key]:raise ValueError('noninteger count')
    for smaller,bigger in [('accepted','observed'),('analyzedSec','totalSec'),('analyzedMs','answerMs')]:
        if d.get(smaller) is not None and d.get(bigger) is not None and d[smaller]>d[bigger]+1e-6:raise ValueError('inconsistent denominator')
    if not isinstance(a['verdicts'],dict) or not set(a['verdicts'])<={'h1','h2','panel','rate','quality'} or any(v not in {'pass','fail','inconclusive'} for v in a['verdicts'].values()):raise ValueError('invalid verdicts')
    return a


def compare(artifacts, legacy_count=0):
    buckets={};seen=set()
    for a in artifacts:
        validate(a)
        if a['runId'] in seen:raise ValueError('duplicate runId: '+a['runId'])
        seen.add(a['runId'])
        compatibility={k:a[k] for k in ('schemaVersion','kind','evidence','protocolVersion','methodVersion','configVersion','codeVersion','dirty')}
        compatibility['environment']=a['environment']
        key=json.dumps(compatibility,sort_keys=True)
        buckets.setdefault(key,[]).append(a)
    groups=[]
    for key,rows in buckets.items():
        complete=[a for a in rows if a['status']=='complete']
        group={'compatibility':json.loads(key),'attempts':len(rows),**{s:sum(a['status']==s for a in rows) for s in ('complete','invalid','aborted','error')},'runIds':[a['runId'] for a in rows]}
        group['verdicts']={k:dict(passCount=sum(a['verdicts'].get(k)=='pass' for a in complete),denominator=len(complete),passRate=sum(a['verdicts'].get(k)=='pass' for a in complete)/len(complete) if complete else None) for k in sorted({k for a in rows for k in a['verdicts']})}
        values=[a['metrics'].get('e50Relative') for a in complete]
        values=[v for v in values if v is not None]
        med=statistics.median(values) if values else 0
        group['repeatSpreadReference']=(max(values)-min(values))/med if len(values)>=3 and med>0 else None
        group['reasonCounts']={reason:sum(reason in a['reasonCodes'] for a in rows) for reason in sorted({reason for a in rows for reason in a['reasonCodes']})}
        group['h2OverallCertified']=False
        group['metricMedians']={k:statistics.median(v) for k in sorted({k for a in complete for k in a['metrics']}) if (v:=[a['metrics'][k] for a in complete if a['metrics'].get(k) is not None])}
        groups.append(group)
    return {'schemaVersion':SCHEMA,'groups':groups,'legacyUnversionedCount':legacy_count,'note':'Evidence and incompatible conditions stay separate. Repeat spread is reference only; H2 overall is not certified.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',action='append',required=True,type=Path);parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args();rows=[];legacy=0
    for path in args.input:
        value=json.loads(path.read_text(),parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
        for item in value if isinstance(value,list) else [value]:
            if isinstance(item,dict) and 'schemaVersion' not in item and 'runs' in item:legacy+=len(item['runs']);continue
            rows.append(item)
    report=compare(rows,legacy)
    args.out.mkdir(parents=True,exist_ok=False)
    (args.out/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    with (args.out/'comparison.csv').open('w',newline='') as file:
        writer=csv.writer(file);writer.writerow(['group','kind','evidence','attempts','complete','invalid','aborted','error','repeatSpreadReference'])
        for i,g in enumerate(report['groups'],1):writer.writerow([i,g['compatibility']['kind'],g['compatibility']['evidence'],*[g[k] for k in ('attempts','complete','invalid','aborted','error','repeatSpreadReference')]])
    lines=['# Anonymous validation comparison','',report['note'],'',f'Legacy unversioned runs (excluded): {legacy}','']
    for i,g in enumerate(report['groups'],1):lines += [f'## Group {i}', '',f"Evidence: {g['compatibility']['evidence']}; complete {g['complete']}/{g['attempts']}; invalid {g['invalid']}; aborted {g['aborted']}; error {g['error']}.",'',f"Verdicts: {json.dumps(g['verdicts'])}",'']
    (args.out/'comparison.md').write_text('\n'.join(lines))


if __name__=='__main__':main()
