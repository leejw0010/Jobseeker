/** Opt-in real AudioContext + real MediaPipe. No application API, camera, microphone, or user files. */
import {test,expect,type Browser,type Page} from '@playwright/test';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
const fixtures=process.env.VALIDATION_FIXTURES_DIR;
const output=process.env.VALIDATION_RESULTS_DIR||'/tmp/jobseeker-media-browser-artifacts';
test.beforeEach(async({page})=>{await page.goto('/');});
async function resources(browser:Browser){
 const session=await browser.newBrowserCDPSession();
 const result=await session.send('SystemInfo.getProcessInfo');await session.detach();
 let rss=0;for(const p of result.processInfo){try{rss+=Number(/VmHWM:\s+(\d+)/.exec(readFileSync(`/proc/${p.id}/status`,'utf8'))?.[1]||0);}catch{ /* exited process */ }}
 return {cpu:result.processInfo.reduce((sum,p)=>sum+p.cpuTime,0),rss:rss/1024};
}
function save(name:string,a:unknown){mkdirSync(output,{recursive:true});writeFileSync(join(output,name),JSON.stringify(a,null,2));}

test('PCM passes through live AudioContext analyser, shared recorder RMS and summaries; closes contexts repeatedly',async({page,browser})=>{
 const before=await resources(browser);
 const result=await page.evaluate(async()=>{
  const module='/src/delivery/voice.ts', artifacts='/src/validation/artifact.ts';
  const {byteTimeDomainEnergy,createVoiceSampler,summarizeVoice}=await import(module);
  const {createArtifact,voiceMetrics}=await import(artifacts);
  const rows=[];
  for(const condition of ['gated-tone','constant-tone','clipped-tone']){
   const ctx=new AudioContext({sampleRate:48000});await ctx.resume();const buffer=ctx.createBuffer(1,ctx.sampleRate*4,ctx.sampleRate),pcm=buffer.getChannelData(0);
   for(let i=0;i<pcm.length;i++){const t=i/ctx.sampleRate;pcm[i]=condition==='clipped-tone'?(i%32<16?-1:1):Math.sin(2*Math.PI*220*t)*(condition==='constant-tone'?.15:(Math.floor(t)%2===0?.2:.001));}
   const source=ctx.createBufferSource();source.buffer=buffer;const analyser=ctx.createAnalyser();analyser.fftSize=512;source.connect(analyser);const mute=ctx.createGain();mute.gain.value=0;analyser.connect(mute);mute.connect(ctx.destination);
   const sampler=createVoiceSampler(),buf=new Uint8Array(512);source.start();const start=ctx.currentTime;
   while(ctx.currentTime-start<4){analyser.getByteTimeDomainData(buf);sampler.add({t:ctx.currentTime-start,...byteTimeDomainEnergy(buf)});await new Promise(r=>setTimeout(r,100));}
   source.stop();source.disconnect();analyser.disconnect();mute.disconnect();await ctx.close();
   const summary=summarizeVoice(sampler.snapshot(),4);rows.push({condition,quality:summary.quality,reasons:summary.reasons,contextClosed:ctx.state==='closed',artifact:createArtifact('voice',voiceMetrics(summary),{attempts:1,totalSec:4,analyzedSec:summary.analyzedSec},{evidence:'synthetic-signal',condition,reasonCodes:summary.reasons,verdicts:{quality:summary.quality==='usable'?'pass':'fail'}})});
  }
  return rows;
 });
 const after=await resources(browser);const rows=result.map(r=>({...r.artifact,metrics:{...r.artifact.metrics,cpuSec:after.cpu-before.cpu,peakRssMiB:after.rss,cleanupCycles:3}}));save('pcm-audiocontext.json',rows);
 expect(result.every(r=>r.contextClosed)).toBe(true);
 // Scheduler gaps under parallel CI load must remain unreliable instead of weakening production thresholds.
 if(result[0].quality==='usable')expect(result[0].artifact.metrics.activeCandidateSec).toBeGreaterThan(1);
 else expect(result[0].reasons.some((r:string)=>r==='sampling_gap'||r==='partial_coverage')).toBe(true);
 expect(result[1].reasons).toContain('constant_energy');expect(result[2].reasons).toContain('clipping');
});

test('licensed pinned public image runs existing real MediaPipe video detector and closes/reloads sequentially',async({page,browser})=>{
 test.skip(!fixtures,'Set VALIDATION_FIXTURES_DIR to the explicit prepared public-fixture directory');
 const manifest=JSON.parse(readFileSync(new URL('../../../backend/evals/validation/fixtures.json',import.meta.url),'utf8'));
 for(const [name,key] of [['face.png','face'],['face.task','model']])expect(createHash('sha256').update(readFileSync(join(fixtures!,name))).digest('hex')).toBe(manifest[key].sha256);
 await page.route('**/fixture/face.png',r=>r.fulfill({body:readFileSync(join(fixtures!,'face.png')),contentType:'image/png'}));
 await page.route('**/fixture/face.task',r=>r.fulfill({body:readFileSync(join(fixtures!,'face.task')),contentType:'application/octet-stream'}));
 const before=await resources(browser);
 const result=await page.evaluate(async()=>{
  const detectorModule='/src/video/detector.ts',metricModule='/src/video/metrics.ts',artifactModule='/src/validation/artifact.ts';
  const {loadFaceDetector,faceDetectorMetadata}=await import(detectorModule);const {faceFeatures}=await import(metricModule);const {createArtifact}=await import(artifactModule);
  const image=new Image();image.src='/fixture/face.png';await image.decode();const canvas=document.createElement('canvas');canvas.width=640;canvas.height=480;const draw=canvas.getContext('2d')!;
  draw.drawImage(image,80,0,480,480);
  const stream=canvas.captureStream(30),video=document.createElement('video');video.srcObject=stream;video.muted=true;video.playsInline=true;document.body.append(video);await video.play();
  const times:number[]=[];let detected=0,observed=0,blankDetected=0,coldMs=0;const delegates:string[]=[];
  try{
   for(let cycle=0;cycle<2;cycle++){
    const start=performance.now();const d=await loadFaceDetector();delegates.push(faceDetectorMetadata().delegate);
    try{
     for(let i=0;i<12;i++){
      draw.fillStyle='black';draw.fillRect(0,0,640,480);if(i<10)draw.drawImage(image,80,0,480,480);await new Promise(r=>setTimeout(r,40));
      const before=performance.now(),points=d.detect(video,before);times.push(performance.now()-before);if(cycle===0&&i===0)coldMs=performance.now()-start;
      const state=faceFeatures(points).state;observed++;if(i<10&&state!=='none')detected++;if(i>=10&&state!=='none')blankDetected++;
     }
    }finally{d.close();}
   }
  }finally{stream.getTracks().forEach(t=>t.stop());video.srcObject=null;video.remove();}
  const warm=times.slice(1).sort((a,b)=>a-b);
  return {detected,observed,blankDetected,delegates,tracksStopped:stream.getTracks().every(t=>t.readyState==='ended'),artifact:createArtifact('face',{coldMs,warmP50Ms:warm[Math.floor(warm.length/2)],warmP95Ms:warm[Math.ceil((warm.length-1)*.95)],cleanupCycles:2},{attempts:1,observed,accepted:detected},{evidence:'public-fixture-real-model',delegate:delegates[0],condition:'nasa-portrait-plus-blank',protocolVersion:'public-portrait-smoke-v1',methodVersion:'mediapipe-face-landmarker-float16-1',verdicts:{quality:detected>0&&blankDetected===0?'pass':'fail'}})};
 });
 expect(result.detected).toBeGreaterThan(0);expect(result.blankDetected).toBe(0);expect(result.tracksStopped).toBe(true);expect(result.delegates).toHaveLength(2);
 const after=await resources(browser);save('face-real-model.json',{...result.artifact,metrics:{...result.artifact.metrics,cpuSec:after.cpu-before.cpu,peakRssMiB:after.rss}});
});
