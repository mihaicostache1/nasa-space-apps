import type { ReferenceArchiveCoverage } from './evaluation';
import type { TerrainMask } from './terrain-mask';

/** Reviewed mask verified against the site's full archive; no horizon payload. */
export type ReferenceTerrainMask = {
  maskId: string;
  artifactSha256: string;
  observer: TerrainMask['observer'];
  referenceFrame: TerrainMask['referenceFrame'];
  demSources: TerrainMask['provenance']['sources'];
  /** Discovery does not accept the approximation for subsequent evaluations. */
  requiresMeanEarthApproximation: boolean;
  framePolicy: 'mean-earth-reference-v1';
  limitation: string;
};

/** GET /api/reference/sites: verified archived reference points (not landing targets). */
export type ReferenceSite = {
  id: string;
  name: string;
  lat: number;
  /** East-positive degrees. */
  lon: number;
  /** Observer altitude above the 1737.4 km reference sphere. */
  altitudeKm: number;
  coordinateSource: string;
  availability: ReferenceArchiveCoverage;
  supportedHorizonModes: ('geometric' | 'terrain')[];
  terrainMasks: ReferenceTerrainMask[];
};

export type ReferenceSiteCatalog = {
  schemaVersion: 'lunarwindow.reference-catalog.v1';
  provider: string;
  timeScale: 'UTC';
  longitudeConvention: 'east-positive';
  sites: ReferenceSite[];
};
