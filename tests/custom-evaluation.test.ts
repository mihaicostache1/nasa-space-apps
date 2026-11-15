import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import fixture from './fixtures/reference-evaluation-site01.json';
import type { ReferenceEvaluationDataset } from '@/domain/evaluation';
import {
  parseCustomEvaluation,
  type CustomEvaluationRequest,
} from '@/domain/custom-evaluation';
import {
  customErrorTitle,
  customRequest,
  defaultCustomForm,
} from '@/features/custom/lib/form';

describe('custom observer form', () => {
  it('requires an explicit geometric ground elevation and preserves height units', () => {
    expect(customRequest(defaultCustomForm).issues.join(' ')).toContain(
      'Ground elevation',
    );
    const result = customRequest({
      ...defaultCustomForm,
      ground: '1944.767',
      height: '2',
    });
    expect(result.issues).toEqual([]);
    expect(result.request?.location).toEqual({
      latitudeDeg: -89,
      longitudeDeg: 0,
      observerHeightM: 2,
      surfaceElevationM: 1944.767,
    });
    expect(result.request?.startUtc).toBe('2026-11-14T00:00:00Z');
  });
  it('rejects invalid coordinates, missing heights and impossible UTC dates', () => {
    for (const change of [
      { latitude: '-91' },
      { longitude: '181' },
      { height: '' },
      { height: '-1' },
      { ground: 'NaN' },
      { start: '2026-02-30T00:00' },
      { step: '60.5' },
    ]) {
      expect(
        customRequest({ ...defaultCustomForm, ground: '0', ...change }).issues
          .length,
      ).toBeGreaterThan(0);
    }
  });
  it('enforces runtime sample and duration bounds before submitting', () => {
    expect(
      customRequest({
        ...defaultCustomForm,
        ground: '0',
        end: '2026-12-16T00:00',
      }).issues.join(' '),
    ).toContain('31 days');
    expect(
      customRequest({
        ...defaultCustomForm,
        ground: '0',
        end: '2026-12-14T00:00',
        step: '15',
      }).issues.join(' '),
    ).toContain('744 samples');
  });
  it('requires terrain consent, checks the supported region and derives ground', () => {
    expect(
      customRequest({ ...defaultCustomForm, mode: 'terrain' }).issues.join(' '),
    ).toContain('Accept');
    expect(
      customRequest({
        ...defaultCustomForm,
        mode: 'terrain',
        accepted: true,
        latitude: '0',
      }).issues.join(' '),
    ).toContain('60–90°S');
    const result = customRequest({
      ...defaultCustomForm,
      mode: 'terrain',
      accepted: true,
    });
    expect(result.issues).toEqual([]);
    expect(result.request?.location.surfaceElevationM).toBeUndefined();
    expect(result.request?.allowMeanEarthApproximation).toBe(true);
    expect(
      customRequest({
        ...defaultCustomForm,
        mode: 'terrain',
        accepted: true,
        ground: '0',
      }).request?.location.surfaceElevationM,
    ).toBeUndefined();
  });
  it('distinguishes unavailable, invalid, upstream and incomplete result states', () => {
    expect(customErrorTitle({ status: 503, code: 'custom_disabled' })).toBe(
      'Custom evaluation unavailable',
    );
    expect(customErrorTitle({ status: 503, code: 'custom_busy' })).toBe(
      'Evaluation service busy',
    );
    expect(customErrorTitle({ status: 422 })).toBe(
      'Observer or coverage needs attention',
    );
    expect(customErrorTitle({ status: 502 })).toBe(
      'Horizons service unavailable',
    );
    expect(customErrorTitle({ status: 504 })).toBe(
      'Evaluation time limit reached',
    );
    expect(
      customErrorTitle({ status: 502, code: 'invalid_custom_response' }),
    ).toBe('Incomplete scientific data');
  });
});

describe('custom success response boundary', () => {
  const reference = fixture as unknown as ReferenceEvaluationDataset;
  const ephemeris = JSON.parse(
    readFileSync(
      new URL(
        '../data/reference/validation-30d/lola-site01-reference.json',
        import.meta.url,
      ),
      'utf8',
    ),
  ) as { provenance: ReferenceEvaluationDataset['provenance']['ephemeris'] };
  const request: CustomEvaluationRequest = {
    location: {
      latitudeDeg: reference.lat,
      longitudeDeg: reference.lon,
      observerHeightM: 0,
      surfaceElevationM: reference.altitudeKm * 1000,
    },
    horizonMode: 'geometric',
    allowMeanEarthApproximation: false,
    startUtc: reference.provenance.ephemeris.startUtc,
    endUtc: reference.provenance.ephemeris.endUtc,
    stepMinutes: reference.calculation.stepMinutes,
    visibilityRule: reference.calculation.visibilityRule,
  };
  // Explicit contract fixture wrapper; never used by the product's request path.
  const body = {
    ...reference,
    schemaVersion: 'lunarwindow.custom-evaluation.v1',
    dataMode: 'custom',
    observer: {
      lat: reference.lat,
      lon: reference.lon,
      mastHeightM: 0,
      surfaceElevationM: reference.altitudeKm * 1000,
      altitudeKm: reference.altitudeKm,
      coordinateSource: 'Contract-test observer',
    },
    allowMeanEarthApproximation: false,
    provenance: {
      ephemeris: ephemeris.provenance,
      ephemerisSha256: '0'.repeat(64),
      terrain: null,
      warning: 'Contract test; no production custom samples are synthesized.',
    },
  };
  it('preserves real engine values and accepts a complete matching payload', () => {
    expect(parseCustomEvaluation(body, request).metrics).toEqual(
      reference.metrics,
    );
  });
  it('rejects partial data instead of filling absent metrics or samples', () => {
    expect(() =>
      parseCustomEvaluation({ ...body, metrics: undefined }, request),
    ).toThrow();
    expect(() =>
      parseCustomEvaluation({ ...body, series: [] }, request),
    ).toThrow();
    expect(() =>
      parseCustomEvaluation(
        {
          ...body,
          provenance: { ...body.provenance, ephemerisSha256: 'missing' },
        },
        request,
      ),
    ).toThrow();
  });
  it('rejects a different observer, mode or sampling grid', () => {
    expect(() =>
      parseCustomEvaluation(body, {
        ...request,
        location: { ...request.location, latitudeDeg: -88 },
      }),
    ).toThrow();
    expect(() =>
      parseCustomEvaluation(body, {
        ...request,
        horizonMode: 'terrain',
        allowMeanEarthApproximation: true,
      }),
    ).toThrow();
    expect(() =>
      parseCustomEvaluation({ ...body, series: body.series.slice(1) }, request),
    ).toThrow();
    expect(() =>
      parseCustomEvaluation(body, { ...request, stepMinutes: 120 }),
    ).toThrow();
  });
});
