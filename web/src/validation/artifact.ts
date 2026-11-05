/** Explicit anonymous aggregates only. No storage, requests, source text, identifiers or samples. */
import {faceDetectorMetadata} from '../video/runtime';
import type { DeliverySummary } from '../delivery/voice';
import type { SegmentSummary } from '../video/metrics';
export const VALIDATION_SCHEMA = 'jobseeker-validation-v1' as const;
export type ValidationKind = 'voice'|'face'|'gaze-phase0';
export type Evidence = 'synthetic-signal'|'public-fixture-real-model'|'human-device';
export type RunStatus = 'complete'|'invalid'|'aborted'|'error';
export type Metrics = Record<string,number|null>;
export type ValidationArtifact = ReturnType<typeof createArtifact>;
export type ReasonCode='viewport_changed'|'resolution_changed'|'invalid_resolution'|'camera_error'|'user_aborted'|'model_error'|'sampling_gap'|'invalid_timestamp'|'invalid_duration'|'no_samples'|'partial_coverage'|'invalid_energy'|'clipping'|'low_energy'|'constant_energy'|'too_short'|'insufficient_samples';
const REASONS=new Set(['viewport_changed','resolution_changed','invalid_resolution','camera_error','user_aborted','model_error','sampling_gap','invalid_timestamp','invalid_duration','no_samples','partial_coverage','invalid_energy','clipping','low_energy','constant_energy','too_short','insufficient_samples']);
const METRICS=new Set('samples totalSec analyzedSec coverage activeCandidateSec silenceCandidateSec silenceCandidateRatio pauseCount longPauseCount longestPauseSec syllables totalPacePerMin activeCandidatePacePerMin fillerCount answerMs analyzedMs detectedMs inMs edgeMs noneMs noneEpisodes longestNoneMs headMs turnedMs downMs e50Relative e50Px e80Px valAuc lensForward lensTurned topFalse screenFalse validRatio coldMs warmP50Ms warmP95Ms cpuSec peakRssMiB realTimeFactor cer cleanupCycles errorCount'.split(' '));
const DENOMINATORS=new Set('attempts observed accepted samples analyzedSec totalSec analyzedMs answerMs textUnits syllables'.split(' '));
export const EXPORT_NOTICE = '익명 집계만 파일로 내보냅니다. 내려받은 파일은 동의 철회나 결과 삭제로 회수할 수 없어요. 개인 정보를 덧붙이지 마세요.';
const clean = (values: Metrics,allowed:Set<string>): Metrics => Object.fromEntries(Object.entries(values).filter(([key])=>allowed.has(key)).map(([key,value])=>[key, value!=null&&Number.isFinite(value)&&value>=0?value:null]));
export function createArtifact(kind:ValidationKind,metrics:Metrics,denominators:Metrics, options:{evidence?:Evidence;status?:RunStatus;protocolVersion?:string;methodVersion?:string;configVersion?:string;delegate?:string;condition?:string;verdicts?:Record<string,'pass'|'fail'|'inconclusive'>;runId?:string;reasonCodes?:string[];cameraWidth?:number|null;cameraHeight?:number|null}={}) {
 const browser=typeof navigator==='undefined'?'unknown':/Firefox/.test(navigator.userAgent)?'firefox':/Edg\//.test(navigator.userAgent)?'edge':/Chrome/.test(navigator.userAgent)?'chromium':/Safari/.test(navigator.userAgent)?'safari':'unknown';
 const ua=typeof navigator==='undefined'?'':navigator.userAgent,os=/Android/.test(ua)?'android':/iPhone|iPad/.test(ua)?'ios':/Windows/.test(ua)?'windows':/Macintosh/.test(ua)?'macos':/Linux/.test(ua)?'linux':'unknown';
 const camera=kind==='voice'?{cameraWidth:null,cameraHeight:null}:faceDetectorMetadata();
 return {schemaVersion:VALIDATION_SCHEMA,kind,evidence:options.evidence??(typeof window==='undefined'||import.meta.env?.VITE_E2E_FAKE_FACE==='true'||faceDetectorMetadata().delegate==='synthetic'?'synthetic-signal':'human-device'),runId:options.runId??globalThis.crypto.randomUUID(),
 protocolVersion:options.protocolVersion??`${kind}-aggregate-v1`,methodVersion:options.methodVersion??(kind==='voice'?'browser-energy-candidates-v1':kind==='face'?'face-relative-posture-v1':'gaze-existing-v1'),
 configVersion:options.configVersion??`${kind}-thresholds-v1`,codeVersion:import.meta.env?.VITE_VALIDATION_CODE_VERSION||'unversioned-working-tree',dirty:import.meta.env?.VITE_VALIDATION_DIRTY!=='false',status:options.status??'complete',
 environment:{browser,os,viewportWidth:typeof innerWidth==='undefined'?null:innerWidth,viewportHeight:typeof innerHeight==='undefined'?null:innerHeight,devicePixelRatio:typeof devicePixelRatio==='undefined'?null:devicePixelRatio,cameraWidth:options.cameraWidth??camera.cameraWidth,cameraHeight:options.cameraHeight??camera.cameraHeight,condition:options.condition??'unspecified',delegate:options.delegate??(kind==='voice'?'AudioContext':'unknown')},denominators:clean(denominators,DENOMINATORS),metrics:clean(metrics,METRICS),verdicts:options.verdicts??{},reasonCodes:[...new Set(options.reasonCodes??[])].filter(reason=>REASONS.has(reason))};
}
export function voiceMetrics(v:DeliverySummary):Metrics {
 if(v.transcriptRevisionMatches===false) throw new Error('transcript revision is not current');
 return {totalSec:v.totalSec,analyzedSec:v.analyzedSec,coverage:v.coverage,activeCandidateSec:v.activeCandidateSec,silenceCandidateSec:v.silenceCandidateSec,silenceCandidateRatio:v.silenceCandidateRatio,pauseCount:v.pauseCount,longPauseCount:v.longPauseCount,longestPauseSec:v.longestPauseSec,syllables:v.syllables,totalPacePerMin:v.totalPacePerMin,activeCandidatePacePerMin:v.activeCandidatePacePerMin,fillerCount:v.fillers.reduce((n,f)=>n+f.count,0)};
}
export function faceMetrics(v:SegmentSummary):Metrics {
 return {samples:v.samples,answerMs:v.answerMs,analyzedMs:v.analyzedMs,detectedMs:v.detectedMs,inMs:v.inMs,edgeMs:v.edgeMs,noneMs:v.noneMs,noneEpisodes:v.noneEpisodes,longestNoneMs:v.longestNoneMs,headMs:v.headMs,turnedMs:v.turnedMs,downMs:v.downMs};
}
export function repeatSpreadReference(values:(number|null)[]):number|null {
 values=values.filter(v=>v!==null);
 if(values.length<3||values.some(v=>v===null||!Number.isFinite(v)||v<0))return null;
 const sorted=(values as number[]).slice().sort((a,b)=>a-b),mid=Math.floor(sorted.length/2),median=sorted.length%2?sorted[mid]:(sorted[mid-1]+sorted[mid])/2;
 return median>0?(sorted[sorted.length-1]-sorted[0])/median:null;
}
export function downloadArtifacts(artifacts:ValidationArtifact[]) {
 const blob=new Blob([JSON.stringify(artifacts,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');
 link.href=url;link.download='jobseeker-validation.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),0);
}

/** Repeat reference is meaningful only under the same recorded configuration and environment. */
export function compatibleRepeatSpread(artifacts:ValidationArtifact[]):number|null {
 const complete=artifacts.filter(a=>a.status==='complete');
 const signature=(a:ValidationArtifact)=>JSON.stringify([a.evidence,a.protocolVersion,a.methodVersion,a.configVersion,a.codeVersion,a.dirty,a.environment]);
 if(!complete.length||complete.some(a=>signature(a)!==signature(complete[0])))return null;
 return repeatSpreadReference(complete.map(a=>a.metrics.e50Relative??null));
}
