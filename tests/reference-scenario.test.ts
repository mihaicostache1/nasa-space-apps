import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import type { TerrainMask } from '@/domain/terrain-mask';
import type { ReferenceSite, ReferenceTerrainMask } from '@/domain/reference';
import {
  defaultForm,
  lastStartDate,
  stepOptions,
  toRequest,
  validateForm,
  withHorizonMode,
  withSite,
  missionShift,
} from '@/features/scenarios/lib/reference-scenario';
import { describeApiError } from '@/lib/api-client';

const site = (id: string, startUtc: string, endUtc: string): ReferenceSite => ({
  id,
  name: id,
  lat: -89.46,
  lon: -137.5,
  altitudeKm: 1.94,
  coordinateSource: 'test',
  supportedHorizonModes: ['geometric'],
  terrainMasks: [],
  availability: {
    startUtc,
    endUtc,
    endExclusive: true,
    stepMinutes: 60,
    sampleCount: 720,
  },
});

const site01 = site(
  'lola-site01-reference',
  '2026-11-14T00:00:00Z',
  '2026-12-14T00:00:00Z',
);

describe('reference scenario form', () => {
  const mask: TerrainMask = JSON.parse(
    readFileSync(
      new URL(
        '../data/reference/terrain-masks/lola-site01-reference-mast-0m.json',
        import.meta.url,
      ),
      'utf8',
    ),
  );
  const terrainSite: ReferenceSite = {
    ...site01,
    supportedHorizonModes: ['geometric', 'terrain'],
    terrainMasks: [
      {
        maskId: mask.maskId,
        artifactSha256:
          '4554c4dd492b59f57d30e2de8cecb33d84714da5248f98acefdb8abccc446f6d',
        observer: mask.observer,
        referenceFrame: mask.referenceFrame,
        demSources: mask.provenance.sources,
        requiresMeanEarthApproximation: true,
        framePolicy: 'mean-earth-reference-v1',
        limitation: 'Untransformed Mean Earth realizations.',
      },
    ],
  };

  it('requires explicit approximation acceptance and a registered terrain mask', () => {
    const form = {
      ...defaultForm('A', terrainSite),
      horizonMode: 'terrain' as const,
      maskId: mask.maskId,
    };
    expect(validateForm(form, terrainSite).join(' ')).toContain('Accept');
    expect(
      validateForm({ ...form, acceptFrameApproximation: true }, terrainSite),
    ).toEqual([]);
    expect(
      toRequest({ ...form, acceptFrameApproximation: true }),
    ).toMatchObject({
      horizonMode: 'terrain',
      maskId: mask.maskId,
      allowMeanEarthApproximation: true,
    });
    expect(
      validateForm({ ...form, acceptFrameApproximation: true }, site01).join(
        ' ',
      ),
    ).toContain('no reviewed terrain horizon');
    expect(
      withSite(
        { ...form, acceptFrameApproximation: true },
        { ...site01, id: 'other-reference' },
      ),
    ).toMatchObject({
      horizonMode: 'geometric',
      acceptFrameApproximation: false,
      maskId: '',
    });
  });

  it('compares equal mission durations and refuses unsupported six-week shifts', () => {
    const original = defaultForm('A', site01);
    const { original: a, revised: b } = missionShift(original, 7, 1);
    expect(a).toMatchObject({
      slot: 'A',
      startDate: '2026-11-14',
      endDate: '2026-11-15',
    });
    expect(b).toMatchObject({
      slot: 'B',
      siteId: a.siteId,
      startDate: '2026-11-21',
      endDate: '2026-11-22',
    });
    expect(validateForm(b, site01)).toEqual([]);
    expect(original.endDate).toBe('2026-12-14');
    const shifted = missionShift(original, 42, 1).revised;
    expect(shifted.startDate).toBe('2026-12-26');
    expect(validateForm(shifted, site01).join(' ')).toContain('archive');
  });
  it('defaults to the full archive and builds a geometric request', () => {
    const form = defaultForm('A', site01);
    expect(toRequest(form)).toEqual({
      siteId: 'lola-site01-reference',
      horizonMode: 'geometric',
      startUtc: '2026-11-14T00:00:00Z',
      endUtc: '2026-12-14T00:00:00Z',
      stepMinutes: 60,
      visibilityRule: 'any-disc',
    });
    expect(validateForm(form, site01)).toEqual([]);
  });

  it('offers whole multiples of the archive step up to one day', () => {
    expect(stepOptions(site01)).toEqual([60, 120, 180, 360, 720, 1440]);
    expect(lastStartDate(site01)).toBe('2026-12-13');
  });

  it.each([
    [{ startDate: '2026-11-01' }, 'archive'],
    [{ endDate: '2026-12-15' }, 'archive'],
    [{ startDate: '2026-11-20', endDate: '2026-11-20' }, 'follow'],
    [{ stepMinutes: 90 }, 'multiple'],
    [{ startDate: '' }, 'Choose'],
  ])('rejects invalid input %#', (change, expected) => {
    const issues = validateForm(
      { ...defaultForm('A', site01), ...change },
      site01,
    );
    expect(issues.join(' ')).toContain(expected);
  });

  it('keeps dates inside a newly selected site archive', () => {
    const shorter = site(
      'short',
      '2026-11-20T00:00:00Z',
      '2026-11-25T00:00:00Z',
    );
    const moved = withSite(defaultForm('B', site01), shorter);
    expect(moved).toMatchObject({
      siteId: 'short',
      startDate: '2026-11-20',
      endDate: '2026-11-25',
    });
    expect(validateForm(moved, shorter)).toEqual([]);
  });

  it('requires a known site', () => {
    expect(validateForm(defaultForm('A', site01), undefined)).toEqual([
      'Choose a reference site.',
    ]);
  });
});

const mask: ReferenceTerrainMask = {
  maskId: 'lola-site01-reference-mast-0m',
  artifactSha256: 'a'.repeat(64),
  observer: {
    lat: -89.46,
    lon: -137.5,
    coordinateSource: 'test',
    surfaceElevationM: 1944.77,
    mastHeightM: 0,
    altitudeKm: 1.94477,
  },
  referenceFrame: {
    body: 'Moon',
    name: 'MOON_ME',
    realization: 'DE421',
    coordinateType: 'GEODETIC',
    longitudeConvention: 'east-positive',
    referenceSurface: { shape: 'sphere', radiusKm: 1737.4 },
  },
  demSources: [],
  requiresMeanEarthApproximation: true,
  framePolicy: 'mean-earth-reference-v1',
  limitation: 'No frame transformation is applied.',
};

const terrainSite: ReferenceSite = {
  ...site01,
  supportedHorizonModes: ['geometric', 'terrain'],
  terrainMasks: [mask],
};

describe('terrain horizon', () => {
  it('builds a terrain request only after the approximation is accepted', () => {
    const form = withHorizonMode(
      defaultForm('A', terrainSite),
      'terrain',
      terrainSite,
    );
    expect(form).toMatchObject({
      horizonMode: 'terrain',
      maskId: 'lola-site01-reference-mast-0m',
      acceptFrameApproximation: false,
    });
    expect(validateForm(form, terrainSite).join(' ')).toContain(
      'Accept the frame approximation',
    );

    const accepted = { ...form, acceptFrameApproximation: true };
    expect(validateForm(accepted, terrainSite)).toEqual([]);
    expect(toRequest(accepted)).toEqual({
      siteId: 'lola-site01-reference',
      horizonMode: 'terrain',
      maskId: 'lola-site01-reference-mast-0m',
      allowMeanEarthApproximation: true,
      startUtc: '2026-11-14T00:00:00Z',
      endUtc: '2026-12-14T00:00:00Z',
      stepMinutes: 60,
      visibilityRule: 'any-disc',
    });
  });

  it('stays geometric for a site without a reviewed mask', () => {
    const form = withHorizonMode(defaultForm('A', site01), 'terrain', site01);
    expect(form.horizonMode).toBe('geometric');
    expect(toRequest(form).horizonMode).toBe('geometric');
    expect(
      validateForm({ ...form, horizonMode: 'terrain' }, site01).join(' '),
    ).toContain('no reviewed terrain horizon');
  });

  it('returns to the flat horizon when the site changes', () => {
    const form = {
      ...withHorizonMode(defaultForm('A', terrainSite), 'terrain', terrainSite),
      acceptFrameApproximation: true,
    };
    const other = site(
      'lola-site23-reference',
      '2026-11-14T00:00:00Z',
      '2026-12-14T00:00:00Z',
    );
    expect(withSite(form, other)).toMatchObject({
      siteId: 'lola-site23-reference',
      horizonMode: 'geometric',
      maskId: '',
      acceptFrameApproximation: false,
    });
  });
});

describe('API error messages', () => {
  it('summarises structured validation errors', () => {
    expect(
      describeApiError(422, {
        error: {
          code: 'validation_error',
          message: 'Invalid request. Check the listed fields.',
          details: [
            {
              location: ['body', 'startUtc'],
              message: 'Outside archive coverage',
              type: 'value_error',
            },
          ],
        },
      }),
    ).toBe(
      'Invalid request. Check the listed fields. startUtc: Outside archive coverage',
    );
  });

  it('falls back to the HTTP status for unstructured bodies', () => {
    expect(describeApiError(503, null)).toBe('The API returned HTTP 503.');
    expect(describeApiError(502, { detail: 'x' })).toBe(
      'The API returned HTTP 502.',
    );
  });
});
