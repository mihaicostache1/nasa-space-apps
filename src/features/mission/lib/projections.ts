/** Azimuthal equidistant sky: zenith at centre, north up, east right. */
export function skyPosition(az: number, el: number, low = -10, radius = 185) {
  const radial = ((90 - el) / (90 - low)) * radius;
  const angle = (az * Math.PI) / 180;
  return {
    x: 240 + radial * Math.sin(angle),
    y: 240 - radial * Math.cos(angle),
  };
}

/** South-pole equidistant diagram. Longitude zero is up; east is clockwise. */
export function polarPosition(lat: number, lon: number) {
  const radius = ((90 + lat) / 5) * 170;
  const angle = (lon * Math.PI) / 180;
  return {
    x: 240 + radius * Math.sin(angle),
    y: 240 - radius * Math.cos(angle),
  };
}
