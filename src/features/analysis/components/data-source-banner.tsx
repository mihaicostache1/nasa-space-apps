import type { ReferenceSiteCatalog } from '@/domain/reference';
import { formatUtc } from '../lib/timeline';
import type { ScenarioResult } from '../types';

type Props = { catalog: ReferenceSiteCatalog; results: ScenarioResult[] };

/** States where the numbers come from and what the model leaves out. */
export function DataSourceBanner({ catalog, results }: Props) {
  const starts = catalog.sites.map((s) => Date.parse(s.availability.startUtc));
  const ends = catalog.sites.map((s) => Date.parse(s.availability.endUtc));
  const steps = [
    ...new Set(catalog.sites.map((s) => s.availability.stepMinutes)),
  ];
  const warnings = [
    ...new Set(results.map(({ data }) => data.provenance.warning)),
  ];
  const terrain = results.filter(({ data }) => data.horizonMode === 'terrain');
  return (
    <section className="source-banner" aria-label="Data source and model">
      <dl>
        <div>
          <dt>Data</dt>
          <dd>
            {catalog.provider} ephemerides, archived offline (
            {catalog.sites.length} verified reference points)
          </dd>
        </div>
        <div>
          <dt>Available period</dt>
          <dd>
            {formatUtc(Math.min(...starts))} – {formatUtc(Math.max(...ends))}{' '}
            (end excluded), every {steps.map((s) => `${s / 60} h`).join(' / ')}
          </dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd>
            {terrain.length ? (
              <>
                <strong>
                  Scenario {terrain.map((r) => r.slot).join(', ')}: LOLA terrain
                </strong>
                . Reviewed 0 m mast; explicit Mean Earth frame approximation.
                Other geometric results use a flat 0° horizon.
              </>
            ) : (
              <>
                <strong>Geometric</strong>: flat 0° horizon, terrain not applied
              </>
            )}
          </dd>
        </div>
      </dl>
      {warnings.map((warning) => (
        <p key={warning}>{warning}</p>
      ))}
      {terrain.map(
        ({ slot, data }) =>
          data.horizonMode === 'terrain' && (
            <p className="provenance-hash" key={slot}>
              Scenario {slot} · {data.maskId} · SHA-256{' '}
              {data.provenance.terrain.artifactSha256}
              <br />
              DEMs:{' '}
              {data.provenance.terrain.mask.provenance.sources
                .map(
                  (source) => `${source.productId} (${source.resolutionM} m)`,
                )
                .join(' / ')}
              <br />
              {data.provenance.terrain.compatibility.limitation}
            </p>
          ),
      )}
    </section>
  );
}
