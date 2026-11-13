'use client';

import { useState } from 'react';
import { scenarioSchema, type Scenario } from '@/domain/scenario';

const initialScenarios: Scenario[] = ['A', 'B'].map((slot, index) => ({
  name: `Scenario ${slot}`,
  location: {
    latitudeDeg: -89 + index * 0.5,
    longitudeDeg: index * 30,
    altitudeKm: 0,
  },
  startUtc: '2026-11-14T00:00:00Z',
  endUtc: '2026-11-15T00:00:00Z',
  stepMinutes: 60,
}));

export function ScenarioWorkspace() {
  const [scenarios, setScenarios] = useState(initialScenarios);
  const [status, setStatus] = useState(
    'Edit two scenarios to prepare a comparison.',
  );

  function update(index: number, updater: (scenario: Scenario) => Scenario) {
    setScenarios((current) =>
      current.map((scenario, slot) =>
        slot === index ? updater(scenario) : scenario,
      ),
    );
    setStatus('Inputs changed. Validate scenarios when ready.');
  }

  function validate() {
    const issues = scenarios.flatMap((scenario) => {
      const result = scenarioSchema.safeParse(scenario);
      return result.success
        ? []
        : result.error.issues.map(
            (issue) =>
              `${scenario.name}: ${issue.path.join('.')} — ${issue.message}`,
          );
    });
    setStatus(
      issues.length
        ? issues.join(' ')
        : 'Both scenarios are valid. Connect an ephemeris provider to calculate Sun and Earth positions.',
    );
  }

  return (
    <section aria-labelledby="workspace-heading">
      <div className="section-heading">
        <h2 id="workspace-heading">Comparison workspace</h2>
        <span className="badge">SETUP MODE</span>
      </div>
      <div className="scenarios">
        {scenarios.map((scenario, index) => (
          <fieldset className="panel" key={index}>
            <legend>{scenario.name}</legend>
            <p className="hint">Custom location · illustrative coordinates</p>
            <div className="fields">
              <label>
                Latitude (°)
                <input
                  type="number"
                  min="-90"
                  max="90"
                  step="any"
                  value={
                    Number.isNaN(scenario.location.latitudeDeg)
                      ? ''
                      : scenario.location.latitudeDeg
                  }
                  onChange={(event) =>
                    update(index, (s) => ({
                      ...s,
                      location: {
                        ...s.location,
                        latitudeDeg: event.target.valueAsNumber,
                      },
                    }))
                  }
                />
              </label>
              <label>
                Longitude (° east)
                <input
                  type="number"
                  min="-180"
                  max="180"
                  step="any"
                  value={
                    Number.isNaN(scenario.location.longitudeDeg)
                      ? ''
                      : scenario.location.longitudeDeg
                  }
                  onChange={(event) =>
                    update(index, (s) => ({
                      ...s,
                      location: {
                        ...s.location,
                        longitudeDeg: event.target.valueAsNumber,
                      },
                    }))
                  }
                />
              </label>
            </div>
            <label>
              Altitude above reference surface (km)
              <input
                type="number"
                step="any"
                value={
                  Number.isNaN(scenario.location.altitudeKm)
                    ? ''
                    : scenario.location.altitudeKm
                }
                onChange={(event) =>
                  update(index, (s) => ({
                    ...s,
                    location: {
                      ...s.location,
                      altitudeKm: event.target.valueAsNumber,
                    },
                  }))
                }
              />
            </label>
            <div className="fields">
              <label>
                Start date (UTC)
                <input
                  type="date"
                  value={scenario.startUtc.slice(0, 10)}
                  onChange={(event) =>
                    update(index, (s) => ({
                      ...s,
                      startUtc: event.target.value
                        ? `${event.target.value}T00:00:00Z`
                        : '',
                    }))
                  }
                />
              </label>
              <label>
                End date (UTC)
                <input
                  type="date"
                  value={scenario.endUtc.slice(0, 10)}
                  onChange={(event) =>
                    update(index, (s) => ({
                      ...s,
                      endUtc: event.target.value
                        ? `${event.target.value}T00:00:00Z`
                        : '',
                    }))
                  }
                />
              </label>
            </div>
            <label>
              Sample interval
              <select
                value={scenario.stepMinutes}
                onChange={(event) =>
                  update(index, (s) => ({
                    ...s,
                    stepMinutes: Number(event.target.value),
                  }))
                }
              >
                <option value={15}>15 minutes</option>
                <option value={60}>1 hour</option>
                <option value={360}>6 hours</option>
              </select>
            </label>
          </fieldset>
        ))}
      </div>
      <div className="actions">
        <button type="button" onClick={validate}>
          Validate scenarios <span aria-hidden="true">→</span>
        </button>
        <p role="status">{status}</p>
      </div>
      <div className="result-grid">
        {[
          'Sun & Earth horizon',
          'Sunlight timeline',
          'Communication windows',
        ].map((title, index) => (
          <section className="panel placeholder" key={title}>
            <p className="eyebrow">0{index + 1} / ANALYSIS</p>
            <h3>{title}</h3>
            <p>Awaiting ephemeris data</p>
          </section>
        ))}
      </div>
    </section>
  );
}
