import { test, expect } from '@playwright/test';
import { createArtifact, voiceMetrics, faceMetrics, repeatSpreadReference } from '../../src/validation/artifact';
import { summarizeVoice } from '../../src/delivery/voice';
import { summarizeSegment } from '../../src/video/metrics';

test('aggregate export drops transcript tokens, IDs and raw arrays and sanitizes nonfinite',()=>{
 const summary=summarizeVoice([{t:0,rms:.1}],3,'음 secret user-123');
 const a=createArtifact('voice',voiceMetrics(summary),{attempts:1,totalSec:3,analyzedSec:.2},{evidence:'human-device'});
 const text=JSON.stringify(a); expect(text).not.toContain('secret');expect(text).not.toContain('user-123');expect(text).not.toContain('token');
 expect(a.schemaVersion).toBe('jobseeker-validation-v1');expect(a.metrics.fillerCount).toBe(1);expect(a.runId).toBeTruthy();
 expect(createArtifact('face',{...faceMetrics(summarizeSegment([])),coverage:NaN},{attempts:1}).metrics.coverage).toBeNull();
});
test('edited transcripts cannot create voice export',()=>{
 expect(()=>voiceMetrics({...summarizeVoice([],0),transcriptRevisionMatches:false})).toThrow('revision');
});
test('repeat spread needs three completed fresh runs, uses relative e50 median only',()=>{
 expect(repeatSpreadReference([.1,.2,.3])).toBeCloseTo(1);
 expect(repeatSpreadReference([.1,null,.3])).toBeNull();
});
test('recorder byte-domain RMS distinguishes clipped and quiet PCM',async()=>{
 const {byteTimeDomainEnergy}=await import('../../src/delivery/voice');
 expect(byteTimeDomainEnergy(new Uint8Array([128,128]))).toEqual({rms:0,clipped:false});
 expect(byteTimeDomainEnergy(new Uint8Array([0,255])).clipped).toBe(true);
});
test('export allows only schema fields and standard reason codes with explicit unknown environment',()=>{
 const a=createArtifact('voice',{rawFrame:7,coverage:1},{attempts:1,userId:99},{reasonCodes:['user_aborted'],status:'aborted'});
 expect(a.metrics).toEqual({coverage:1});expect(a.denominators).toEqual({attempts:1});
 expect(a.reasonCodes).toEqual(['user_aborted']);expect(a.environment.cameraWidth).toBeNull();
 expect(a.environment).toHaveProperty('os');expect(a.environment).toHaveProperty('viewportWidth');
});
test('face export keeps detector configuration from recording revision',async()=>{
 const {setDetectorMetadata}=await import('../../src/video/runtime');
 const {saveVideoSegment,getVideoSegmentMetadata,clearSessionVideo}=await import('../../src/video/metrics');
 setDetectorMetadata({delegate:'CPU',cameraWidth:640,cameraHeight:480});saveVideoSegment('s','a',summarizeSegment([]),'r1');
 setDetectorMetadata({delegate:'GPU',cameraWidth:1280,cameraHeight:720});
 expect(getVideoSegmentMetadata('s','a','r1')?.delegate).toBe('CPU');
 expect(getVideoSegmentMetadata('s','a','r2')).toBeUndefined();clearSessionVideo('s');expect(getVideoSegmentMetadata('s','a','r1')).toBeUndefined();
});
test('repeat reference refuses mixed environments and retains failed complete runs',async()=>{
 const {compatibleRepeatSpread}=await import('../../src/validation/artifact');
 const rows=[.1,.2,.3].map(v=>createArtifact('gaze-phase0',{e50Relative:v},{attempts:1},{verdicts:{h2:'fail'}}));
 expect(compatibleRepeatSpread(rows)).toBeCloseTo(1);
 rows[1].environment.condition='different';expect(compatibleRepeatSpread(rows)).toBeNull();
});
test('repeated exports identify the same recording with one anonymous run id',async()=>{
 const {saveVoiceSegment,getVoiceRunId,clearSessionVoice}=await import('../../src/delivery/voice');
 const {saveVideoSegment,getVideoRunId}=await import('../../src/video/metrics');
 const summary=summarizeVoice([],0);saveVoiceSegment('private-session','private-answer',summary,'r');const id=getVoiceRunId('private-session','private-answer','r');
 saveVoiceSegment('private-session','private-answer',summary,'r');expect(getVoiceRunId('private-session','private-answer','r')).toBe(id);expect(id).not.toContain('private');
 saveVideoSegment('private-session','private-answer',summarizeSegment([]),'r');const face=getVideoRunId('private-session','private-answer','r');
 saveVideoSegment('private-session','private-answer',summarizeSegment([]),'r');expect(getVideoRunId('private-session','private-answer','r')).toBe(face);clearSessionVoice('private-session');expect(getVoiceRunId('private-session','private-answer','r')).toBeUndefined();
});
test('automatic unit artifacts default to synthetic evidence and public fixtures stay explicit',()=>{
 expect(createArtifact('voice',{}, {attempts:1}).evidence).toBe('synthetic-signal');
 expect(createArtifact('face',{}, {attempts:1},{evidence:'public-fixture-real-model'}).evidence).toBe('public-fixture-real-model');
});
test('repeat reference omits missing e50 but needs three finite completed values',()=>{
 expect(repeatSpreadReference([.1,null,.2,.3])).toBeCloseTo(1);
});
