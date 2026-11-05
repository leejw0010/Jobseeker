import {createArtifact, type Evidence, type RunStatus} from './artifact';
import type {FeasibilityReport} from '../video/gaze/calibration';
export function gazeArtifact(runId:string,status:RunStatus,report:FeasibilityReport|null,evidence:Evidence,delegate:string,skippedRate:boolean,reasonCodes:string[]=[],condition="baseline",observed=0,camera?:{w:number;h:number}|null){
 return createArtifact('gaze-phase0',report?{e50Relative:report.g2.e50Pct,e50Px:report.g2.e50Px,e80Px:report.g2.e80Px,valAuc:report.g1.valAuc,lensForward:report.g1.lensForward,lensTurned:report.g1.lensTurned,topFalse:report.g1.topFalse,screenFalse:report.g1.screenFalse,validRatio:report.validRatio}:{},
 {attempts:1,observed:report?.diag.quality.total??observed,accepted:report?.diag.quality.accepted??null},
 {cameraWidth:camera?.w,cameraHeight:camera?.h,reasonCodes,runId,status,evidence,delegate,condition:skippedRate?`${condition}-rate-skipped`:condition,protocolVersion:'gaze-phase0-v2',methodVersion:'gaze-existing-v1',configVersion:'gaze-thresholds-v1',verdicts:report?{h1:report.g1.verdict,h2:report.g2.verdict,panel:report.panelVerdict,rate:report.rateVerdict}:{}});
}
