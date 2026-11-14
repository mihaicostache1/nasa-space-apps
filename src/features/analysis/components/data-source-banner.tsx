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
  const warning = results[0]?.data.provenance.warning;
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
            <strong>Geometric</strong>: flat 0° horizon, terrain not applied
          </dd>
        </div>
      </dl>
      {warning && <p>{warning}</p>}
    </section>
  );
}
