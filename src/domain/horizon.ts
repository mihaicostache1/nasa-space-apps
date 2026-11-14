/**
 * P2 terrain horizon contract (lunarwindow.horizon.v1); checked by horizon.schema.json in the
 * Python package. Angles are degrees; azimuth is clockwise from local north.
 */
export type HorizonPoint = { az: number; el: number };

export type HorizonProfile = {
  schemaVersion: 'lunarwindow.horizon.v1';
  siteId: string;
  name: string;
  lat: number;
  /** East-positive, [-180, 180]. */
  lon: number;
  coordinateSource: string;
  /** 'none' means a bare-sphere horizon: terrain is not modelled at this site. */
  terrainModel: 'lola-dem' | 'none';
  /** Ground height above the 1737.4 km reference sphere; null if unknown. */
  surfaceElevationM: number | null;
  mastHeightM: number;
  /** Ground + mast above the reference sphere, as passed to Horizons. */
  observerAltitudeKm: number;
  referenceRadiusM: number;
  /** Exactly 360 entries, az 0..359; each is the max of the rays within ±0.5°. */
  horizon: HorizonPoint[];
  /** Full-resolution rays for drawing the sky dome; null for terrainModel 'none'. */
  rays: {
    stepDeg: number;
    el: number[];
    /** Distance to the terrain that sets the horizon on each ray. */
    horizonDistanceKm: (number | null)[];
    /** Farthest terrain sampled; below parameters.maxRangeKm means the DEM ended. */
    reachKm: number[];
  } | null;
  quality: {
    /** Whole-degree bins whose distant terrain is missing; draw them as uncertain. */
    truncatedAzimuths: number[];
    minReachKm: number;
    missingSampleFraction: number;
    nearFieldAvailable: boolean;
    warnings: string[];
  };
  parameters: {
    mastHeightM: number;
    maxRangeKm: number;
    nearFieldKm: number;
    minDistanceM: number;
    raysPerDegree: number;
    stepGrowth: number;
    binning: 'max-per-degree';
  };
  sources: {
    productId: string | null;
    role: string | null;
    sourceUrl: string | null;
    sha256: string | null;
    resolutionM: number;
  }[];
  algorithmVersion: string;
};
