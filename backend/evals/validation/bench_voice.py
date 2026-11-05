"""Cached base CPU/INT8 smoke benchmark on exactly two verified public clips; no provider/config import."""
import argparse
import gc
import hashlib
import json
import os
import resource
import statistics
import time
import uuid
from pathlib import Path
from .compare import validate


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--fixtures',required=True,type=Path);parser.add_argument('--out',required=True,type=Path);parser.add_argument('--code-version',default='unversioned-working-tree');args=parser.parse_args()
    # These force cache-only execution before any model imports. No dotenv loading.
    os.environ['HF_HUB_OFFLINE']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model
    from evals.stt.data import load_pcm
    from evals.stt.score import normalize
    fixture=json.loads(Path(__file__).with_name('fixtures.json').read_text())['voice']
    refs=json.loads((args.fixtures/'references.json').read_text())
    pcm=[]
    for i,sha in enumerate(fixture['sha256']):
        data=(args.fixtures/f'voice-{i}.flac').read_bytes()
        if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('fixture checksum mismatch')
        pcm.append(load_pcm(data)[::3].astype('float32')/32768.)
    start=time.perf_counter();cpu=time.process_time()
    model=WhisperModel(download_model('base',local_files_only=True),device='cpu',compute_type='int8',cpu_threads=2,num_workers=1)
    model_load=(time.perf_counter()-start)*1000;latencies=[];errors=0;totalchars=0;edits=0
    def distance(a,b):
        row=list(range(len(b)+1))
        for i,x in enumerate(a,1):
            nxt=[i]
            for j,y in enumerate(b,1):nxt.append(min(nxt[-1]+1,row[j]+1,row[j-1]+(x!=y)))
            row=nxt
        return row[-1]
    for iteration in range(3):
        for i,samples in enumerate(pcm):
            before=time.perf_counter()
            try:
                segments,_=model.transcribe(samples,language='ko',task='transcribe',beam_size=5,vad_filter=True,condition_on_previous_text=False)
                text=' '.join(s.text.strip() for s in segments)
                if iteration==0:
                    reference=normalize(refs[i]);totalchars+=len(reference);edits+=distance(reference,normalize(text))
            except Exception:errors+=1
            latencies.append((time.perf_counter()-before)*1000)
    cpu_sec=time.process_time()-cpu
    # Explicit unload, collect, and second lifecycle to exercise cleanup without concurrent models.
    del model;gc.collect()
    second=WhisperModel(download_model('base',local_files_only=True),device='cpu',compute_type='int8',cpu_threads=2,num_workers=1)
    del second;gc.collect()
    warm=sorted(latencies[1:]);p95=warm[min(len(warm)-1,int((len(warm)-1)*.95+.999))]
    a=dict(schemaVersion='jobseeker-validation-v1',kind='voice',evidence='public-fixture-real-model',runId=str(uuid.uuid4()),protocolVersion='zeroth-test-first2-v1',methodVersion='faster-whisper-base-cpu-int8-v1',configVersion='ko-beam5-vad2threads-v1',codeVersion=args.code_version,dirty=True,status='complete',reasonCodes=[],environment=dict(browser='none',os='linux',viewportWidth=None,viewportHeight=None,devicePixelRatio=None,cameraWidth=None,cameraHeight=None,condition='public-read-speech',delegate='CPU'),denominators=dict(attempts=1,observed=6,accepted=6-errors),metrics=dict(totalSec=sum(len(x)/16000 for x in pcm),coldMs=model_load+latencies[0],warmP50Ms=statistics.median(warm),warmP95Ms=p95,cpuSec=cpu_sec,peakRssMiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,realTimeFactor=sum(latencies)/1000/(sum(len(x)/16000 for x in pcm)*3),cer=edits/totalchars if totalchars else None,cleanupCycles=2,errorCount=errors),verdicts=dict(quality='pass' if not errors else 'fail'))
    validate(a)
    with args.out.open('x') as file:json.dump(a,file,indent=2,allow_nan=False)
    print(json.dumps(a['metrics'],indent=2))


if __name__=='__main__':main()
