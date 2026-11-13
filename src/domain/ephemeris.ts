/** P1 export contract; checked by ephemeris.schema.json in the Python package. */
export type EphemerisSample = {
  /** ISO 8601 UTC. Exports include start and exclude end. */
  t: string;
  /** Apparent body-center angles in degrees; azimuth clockwise from north. */
  sunAz: number;
  sunEl: number;
  earthAz: number;
  earthEl: number;
  sunAngularRadiusDeg: number;
  earthAngularRadiusDeg: number;
};

export type EphemerisRequest = {
  target: 'sun' | 'earth';
  sourceUrl: string;
  retrievedAtUtc: string;
  responseSha256: string;
  apiVersion: string;
  /** Actual models reported by Horizons. */
  modelHeader: Record<string, string>;
};

export type EphemerisDataset = {
  schemaVersion: 'lunarwindow.ephemeris.v2';
  siteId: string;
  site: string;
  lat: number;
  lon: number;
  altitudeKm: number;
  coordinateSource: string;
  series: EphemerisSample[];
  provenance: {
    provider: 'NASA/JPL Horizons';
    observerCenter: 'coord@301';
    coordinateType: 'GEODETIC';
    longitudeConvention: 'east-positive';
    timeScale: 'UTC';
    startUtc: string;
    endUtc: string;
    endExclusive: true;
    stepMinutes: number;
    terrainModel: 'none';
    positionType: 'airless-apparent-body-center';
    quantities: [4, 13];
    angularSizeModel: 'equatorial-radius';
    requests: EphemerisRequest[];
  };
};
