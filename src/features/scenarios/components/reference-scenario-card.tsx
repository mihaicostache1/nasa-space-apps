import type { ReferenceSite } from '@/domain/reference';
import type { VisibilityRule } from '@/domain/evaluation';
import {
  lastStartDate,
  stepOptions,
  utcDate,
  VISIBILITY_RULES,
  withSite,
  type ReferenceScenarioForm,
} from '../lib/reference-scenario';

type Props = {
  form: ReferenceScenarioForm;
  sites: ReferenceSite[];
  issues: string[];
  onChange: (form: ReferenceScenarioForm) => void;
};

export function ReferenceScenarioCard({
  form,
  sites,
  issues,
  onChange,
}: Props) {
  const site = sites.find((candidate) => candidate.id === form.siteId);
  const id = `scenario-${form.slot}`;
  return (
    <fieldset className="panel" aria-describedby={`${id}-issues`}>
      <legend>Scenario {form.slot}</legend>
      <label>
        Reference site
        <select
          value={form.siteId}
          onChange={(event) => {
            const next = sites.find((s) => s.id === event.target.value);
            if (next) onChange(withSite(form, next));
          }}
        >
          {sites.map((candidate) => (
            <option key={candidate.id} value={candidate.id}>
              {candidate.name}
            </option>
          ))}
        </select>
      </label>
      {site && (
        <p className="hint">
          {Math.abs(site.lat).toFixed(4)}°S, {site.lon.toFixed(4)}°E ·{' '}
          {(site.altitudeKm * 1000).toFixed(0)} m above the 1737.4 km sphere ·
          LOLA DEM reference point, not a landing target
        </p>
      )}
      <div className="fields">
        <label>
          Start (00:00 UTC)
          <input
            type="date"
            value={form.startDate}
            min={site && utcDate(site.availability.startUtc)}
            max={site && lastStartDate(site)}
            onChange={(event) =>
              onChange({ ...form, startDate: event.target.value })
            }
          />
        </label>
        <label>
          End (00:00 UTC, excluded)
          <input
            type="date"
            value={form.endDate}
            min={form.startDate}
            max={site && utcDate(site.availability.endUtc)}
            onChange={(event) =>
              onChange({ ...form, endDate: event.target.value })
            }
          />
        </label>
      </div>
      <div className="fields fields-1-2">
        <label>
          Sample interval
          <select
            value={form.stepMinutes}
            onChange={(event) =>
              onChange({ ...form, stepMinutes: Number(event.target.value) })
            }
          >
            {stepOptions(site).map((minutes) => (
              <option key={minutes} value={minutes}>
                {minutes / 60} h
              </option>
            ))}
          </select>
        </label>
        <label>
          Visible when
          <select
            value={form.visibilityRule}
            onChange={(event) =>
              onChange({
                ...form,
                visibilityRule: event.target.value as VisibilityRule,
              })
            }
          >
            {VISIBILITY_RULES.map((rule) => (
              <option key={rule.value} value={rule.value}>
                {rule.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div id={`${id}-issues`} aria-live="polite">
        {issues.map((issue) => (
          <p className="issue" key={issue}>
            {issue}
          </p>
        ))}
      </div>
    </fieldset>
  );
}
