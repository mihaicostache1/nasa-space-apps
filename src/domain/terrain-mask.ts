import type { HorizonPoint } from './horizon';

/** Reviewed GIS handoff, separate from the preliminary lunarwindow.horizon.v1 format. */
export type TerrainMask = {
  schemaVersion: 'lunarwindow.terrain-mask.v1';
  maskId: string;
  siteId: string;
  site: string;
  terrainModel: 'dem-horizon';
  observer: {
    lat: number;
    lon: number;
    coordinateSource: string;
    surfaceElevationM: number;
    mastHeightM: number;
    /** (surfaceElevationM + mastHeightM) / 1000 above the declared sphere. */
    altitudeKm: number;
  };
  referenceFrame: {
    body: 'Moon';
    name: string;
    realization: string;
    coordinateType: 'GEODETIC';
    longitudeConvention: 'east-positive';
    referenceSurface: { shape: 'sphere'; radiusKm: number };
  };
  angularUnits: 'degrees';
  azimuthConvention: 'clockwise-from-local-north';
  elevationReference: 'local-horizontal';
  refractionModel: 'none';
  /** Exactly 360 ordered integer azimuths 0..359; negative elevations are retained. */
  horizon: HorizonPoint[];
  provenance: {
    createdAtUtc: string;
    sources: {
      provider: string;
      productId: string;
      productVersion: string;
      sourceUrl: string;
      sourceSha256: string;
      retrievedAtUtc: string;
      resolutionM: number;
      crs: string;
    }[];
    algorithm: {
      name: string;
      version: string;
      curvatureModel: 'spherical' | 'quadratic-drop';
      rayStepM: number;
      maxDistanceM: number;
      noDataPolicy: 'reject';
    };
  };
};
