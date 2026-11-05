/** Current detector configuration, held only in this module's tab memory. */
export type DetectorMetadata={delegate:string;methodVersion:string;configVersion:string;cameraWidth:number|null;cameraHeight:number|null};
let metadata:DetectorMetadata={delegate:'unknown',methodVersion:'mediapipe-face-landmarker-float16-1',configVersion:'face-thresholds-v1',cameraWidth:null,cameraHeight:null};
export const faceDetectorMetadata=():DetectorMetadata=>({...metadata});
export function setDetectorMetadata(value:Partial<DetectorMetadata>){metadata={...metadata,...value};}
