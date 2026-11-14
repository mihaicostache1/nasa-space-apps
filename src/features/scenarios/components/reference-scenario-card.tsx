import { useState } from 'react';
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
  const [query, setQuery] = useState('');
  const site = sites.find((candidate) => candidate.id === form.siteId);
  const id = `scenario-${form.slot}`;
  return (
    <fieldset className="panel" aria-describedby={`${id}-issues`}>
      <legend>Scenario {form.slot}</legend>
      <label>
        Search verified sites
        <input
          type="search"
          placeholder="Find a reference point…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      <label>
        Reference site
        <select
          value={form.siteId}
          onChange={(event) => {
            const next = sites.find((s) => s.id === event.target.value);
            if (next) onChange(withSite(form, next));
          }}
        >
          {sites
            .filter(
              (candidate) =>
                candidate.id === form.siteId ||
                candidate.name.toLowerCase().includes(query.toLowerCase()),
            )
            .map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.name}{' '}
                {candidate.terrainMasks.length
                  ? '· terrain available'
                  : '· geometric'}
              </option>
            ))}
        </select>
      </label>
      {site && (
        <p className="hint">
          {Math.abs(site.lat).toFixed(4)}°{site.lat < 0 ? 'S' : 'N'},{' '}
          {Math.abs(site.lon).toFixed(4)}°{site.lon < 0 ? 'W' : 'E'} ·{' '}
          {(site.altitudeKm * 1000).toFixed(0)} m above the 1737.4 km sphere ·
          LOLA DEM reference point, not a landing target
        </p>
      )}
      <label>
        Horizon model
        <select
          value={form.horizonMode}
          onChange={(event) =>
            onChange({
              ...form,
              horizonMode: event.target.value as 'geometric' | 'terrain',
              maskId:
                event.target.value === 'terrain'
                  ? (site?.terrainMasks[0]?.maskId ?? '')
                  : '',
              allowMeanEarthApproximation: false,
            })
          }
        >
          <option value="geometric">Geometric · flat 0° horizon</option>
          <option value="terrain" disabled={!site?.terrainMasks.length}>
            LOLA terrain
            {!site?.terrainMasks.length ? ' · unavailable' : ' · reviewed mask'}
          </option>
        </select>
      </label>
      {form.horizonMode === 'terrain' && (
        <div className="terrain-consent">
          <p>
            Reviewed 0 m mast. A 2 m mast can change this horizon by up to 1.9°.
          </p>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={form.allowMeanEarthApproximation}
              onChange={(event) =>
                onChange({
                  ...form,
                  allowMeanEarthApproximation: event.target.checked,
                })
              }
            />
            <span>
              I accept the DE421 MOON_ME / DE441 MEAN_ME approximation. No frame
              transformation is applied.
            </span>
          </label>
        </div>
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
