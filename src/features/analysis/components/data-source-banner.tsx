import type { ReferenceSiteCatalog } from '@/domain/reference';
import { describeModel } from '../lib/model';
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
    ...new Set(results.map((result) => result.data.provenance.warning)),
  ];
  const perSlot = results.map((result) => ({
    slot: result.slot,
    ...describeModel(result.data),
  }));
  // One line when every scenario uses the same model; otherwise one per slot.
  const models =
    new Set(perSlot.map((m) => m.label)).size > 1
      ? perSlot
      : [
          {
            slot: null,
            label: perSlot[0]?.label ?? 'Geometric',
            detail:
              perSlot[0]?.detail ?? 'flat 0° horizon, terrain not applied',
          },
        ];
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
            {models.map(({ slot, label, detail }) => (
              <span className="model-line" key={slot ?? 'default'}>
                {slot && <span className="slot">{slot}</span>}
                <strong>{label}</strong>: {detail}
              </span>
            ))}
          </dd>
        </div>
      </dl>
      {warnings.map((warning) => (
        <p key={warning}>{warning}</p>
      ))}
    </section>
  );
}
