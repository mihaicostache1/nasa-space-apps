import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import metadata from '../data/frontend/reference-bootstrap.json';
import { bootstrapForms } from '@/features/scenarios/lib/reference-bootstrap';
import { referenceBootstrap } from '@/features/scenarios/lib/reference-bootstrap.server';
import {
  toRequest,
  validateForm,
} from '@/features/scenarios/lib/reference-scenario';

vi.mock('server-only', () => ({}));

const release = new URL(
  '../data/releases/lunarwindow-demo-v1/',
  import.meta.url,
);
const sha256 = (bytes: Buffer) =>
  createHash('sha256').update(bytes).digest('hex');

describe('verified reference startup', () => {
  it('ships the exact pinned response objects with all samples and provenance', () => {
    const manifestBytes = readFileSync(
      new URL('bundle/manifest.json', release),
    );
    expect(sha256(manifestBytes)).toBe(metadata.releaseManifestSha256);
    const manifest = JSON.parse(manifestBytes.toString());
    expect(referenceBootstrap.releaseId).toBe(manifest.runId);
    for (const [index, scenario] of referenceBootstrap.scenarios.entries()) {
      const source = metadata.scenarios[index];
      const bytes = readFileSync(
        new URL(`bundle/${source.output.filename}`, release),
      );
      expect(sha256(bytes)).toBe(scenario.artifactSha256);
      expect(
        manifest.jobs.some(
          (job: { output: unknown }) =>
            JSON.stringify(job.output) === JSON.stringify(source.output),
        ),
      ).toBe(true);
      expect(scenario.data).toEqual(JSON.parse(bytes.toString()));
      expect(scenario.data.dataMode).toBe('reference');
      expect(scenario.data.siteId).toBe(scenario.request.siteId);
      expect(scenario.data.horizonMode).toBe('geometric');
      expect(scenario.data.series).toHaveLength(720);
      expect(scenario.data.provenance.ephemeris.provider).toBe(
        'NASA/JPL Horizons',
      );
      expect(scenario.data.provenance.ephemeris.startUtc).toBe(
        scenario.request.startUtc,
      );
      expect(scenario.data.provenance.ephemeris.endUtc).toBe(
        scenario.request.endUtc,
      );
      expect(scenario.data.calculation.stepMinutes).toBe(
        scenario.request.stepMinutes,
      );
      expect(scenario.data.calculation.visibilityRule).toBe(
        scenario.request.visibilityRule,
      );
    }
  });

  it('initializes inputs for precisely the saved evaluations', () => {
    const forms = bootstrapForms(referenceBootstrap);
    expect(forms.map((form) => form.slot)).toEqual(['A', 'B']);
    forms.forEach((form, index) => {
      expect(toRequest(form)).toEqual(
        referenceBootstrap.scenarios[index].request,
      );
      expect(
        validateForm(
          form,
          referenceBootstrap.catalog.sites.find(
            (site) => site.id === form.siteId,
          ),
        ),
      ).toEqual([]);
    });
  });

  it('rejects a missing site, a different request or reversed scenario pairing', () => {
    const changed = structuredClone(referenceBootstrap);
    changed.scenarios[0].request.visibilityRule = 'full-disc';
    expect(() => bootstrapForms(changed)).toThrow('does not match');
    expect(() =>
      bootstrapForms({
        ...referenceBootstrap,
        catalog: { ...referenceBootstrap.catalog, sites: [] },
      }),
    ).toThrow('missing');
    expect(() =>
      bootstrapForms({
        ...referenceBootstrap,
        scenarios: [...referenceBootstrap.scenarios].reverse(),
      }),
    ).toThrow('A and B');
  });
});
