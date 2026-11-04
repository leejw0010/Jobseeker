export type CalibrationInvalid = "viewport_changed" | "resolution_changed" | "invalid_resolution";
type Resolution = { width: number; height: number };
/** Once camera dimensions or viewport geometry change, an old calibration cannot become current again. */
export function createCalibrationGuard(viewport: string, initial?: Resolution) {
  let resolution = initial;
  let invalid: CalibrationInvalid | null = null;
  return {
    check(currentViewport: string, camera?: Resolution): CalibrationInvalid | null {
      if (invalid) return invalid;
      if (currentViewport !== viewport) return invalid = "viewport_changed";
      if (!camera) return null;
      if (![camera.width, camera.height].every((v) => Number.isFinite(v) && v > 0)) return invalid = "invalid_resolution";
      if (resolution && (resolution.width !== camera.width || resolution.height !== camera.height)) return invalid = "resolution_changed";
      resolution = { ...camera };
      return null;
    },
  };
}
