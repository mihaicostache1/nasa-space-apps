'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReferenceEvaluationContract } from '@/domain/terrain-evaluation';
import type { ReferenceSiteCatalog } from '@/domain/reference';
import {
  ApiError,
  evaluateReference,
  fetchReferenceSites,
} from '@/lib/api-client';
import { ComparisonTimeline } from '@/features/analysis/components/comparison-timeline';
import { DataSourceBanner } from '@/features/analysis/components/data-source-banner';
import { MissionWindowFinder } from '@/features/analysis/components/mission-window-finder';
import { SkyExplorer } from '@/features/analysis/components/sky-explorer';
import { LanderView } from '@/features/analysis/components/lander-view';
import { modelBadge } from '@/features/analysis/lib/model';
import { AzimuthElevationChart } from '@/features/analysis/components/azimuth-elevation-chart';
import { PolarSiteMap } from '@/features/mission/components/polar-site-map';
import { MissionInsights } from '@/features/mission/components/mission-insights';
import { MissionShift } from '@/features/mission/components/mission-shift';
import { PlaybackControl } from '@/features/mission/components/playback-control';
import { domainHours, domainOf } from '@/features/analysis/lib/timeline';
import type { ScenarioResult } from '@/features/analysis/types';
import {
  defaultForm,
  toRequest,
  validateForm,
  withSite,
  type ReferenceScenarioForm,
} from '../lib/reference-scenario';
import { ReferenceScenarioCard } from './reference-scenario-card';

type CatalogState =
  | { status: 'loading' }
  | { status: 'ready'; data: ReferenceSiteCatalog }
  | { status: 'error'; message: string };

type SlotState = {
  status: 'idle' | 'loading' | 'ready' | 'error';
  data?: ReferenceEvaluationContract;
  /** The request that produced `data`, to detect stale results. */
  requestKey?: string;
  message?: string;
};

const requestKey = (form: ReferenceScenarioForm) =>
  JSON.stringify(toRequest(form));

function message(error: unknown) {
  return error instanceof ApiError || error instanceof Error
    ? error.message
    : 'Unexpected error.';
}

/** Scenario A is the first site; B contrasts with another site over the same period. */
function initialForms(catalog: ReferenceSiteCatalog): ReferenceScenarioForm[] {
  const [first, second] = catalog.sites;
  const contrast =
    catalog.sites.find((site) => site.id === 'lola-site23-reference') ??
    second ??
    first;
  return [defaultForm('A', first), defaultForm('B', contrast)];
}

export function ScenarioWorkspace() {
  const [catalog, setCatalog] = useState<CatalogState>({ status: 'loading' });
  const [forms, setForms] = useState<ReferenceScenarioForm[]>([]);
  const [slots, setSlots] = useState<SlotState[]>([
    { status: 'idle' },
    { status: 'idle' },
  ]);
  const [cursorHours, setCursorHours] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [activeSlot, setActiveSlot] = useState<'A' | 'B'>('A');
  const [view, setView] = useState<'lander' | 'sky' | 'map'>('lander');
  const [playbackOwner, setPlaybackOwner] = useState<
    'lander' | 'samples' | null
  >(null);
  const [shiftKeys, setShiftKeys] = useState<string[] | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  const evaluate = useCallback(
    async (
      current: ReferenceScenarioForm[],
      sites: ReferenceSiteCatalog['sites'],
    ) => {
      setPlaybackOwner(null);
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;
      const issues = current.map((form) =>
        validateForm(
          form,
          sites.find((site) => site.id === form.siteId),
        ),
      );
      setSlots((previous) =>
        current.map((_, index) =>
          issues[index].length
            ? {
                ...previous[index],
                status: 'error',
                message: issues[index].join(' '),
              }
            : { ...previous[index], status: 'loading', message: undefined },
        ),
      );
      await Promise.all(
        current.map(async (form, index) => {
          if (issues[index].length) return;
          try {
            const data = await evaluateReference(
              toRequest(form),
              controller.signal,
            );
            if (controller.signal.aborted) return;
            setSlots((previous) =>
              previous.map((slot, i) =>
                i === index
                  ? { status: 'ready', data, requestKey: requestKey(form) }
                  : slot,
              ),
            );
          } catch (error) {
            if (controller.signal.aborted) return;
            setSlots((previous) =>
              previous.map((slot, i) =>
                i === index
                  ? { ...slot, status: 'error', message: message(error) }
                  : slot,
              ),
            );
          }
        }),
      );
    },
    [],
  );

  useEffect(() => {
    const controller = new AbortController();
    fetchReferenceSites(controller.signal)
      .then((data) => {
        if (!data.sites.length)
          throw new Error('The reference catalog is empty.');
        const defaults = initialForms(data);
        setCatalog({ status: 'ready', data });
        setForms(defaults);
        void evaluate(defaults, data.sites);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setCatalog({ status: 'error', message: message(error) });
      });
    return () => {
      controller.abort();
      inFlight.current?.abort();
    };
  }, [attempt, evaluate]);

  if (catalog.status === 'loading') {
    return (
      <section className="workspace" aria-busy="true">
        <p className="status-line">Loading verified reference sites…</p>
      </section>
    );
  }
  if (catalog.status === 'error') {
    return (
      <section className="workspace">
        <div className="panel error-panel" role="alert">
          <h2>Data unavailable</h2>
          <p>{catalog.message}</p>
          <button
            type="button"
            onClick={() => {
              setCatalog({ status: 'loading' });
              setAttempt((n) => n + 1);
            }}
          >
            Retry
          </button>
        </div>
      </section>
    );
  }

  const sites = catalog.data.sites;
  const results: ScenarioResult[] = slots.flatMap((slot, index) =>
    slot.data && forms[index]
      ? [
          {
            slot: forms[index].slot,
            data: slot.data,
            stale: slot.requestKey !== requestKey(forms[index]),
          },
        ]
      : [],
  );
  const anyStale = results.some((result) => result.stale);
  const loading = slots.some((slot) => slot.status === 'loading');
  const maxHours = Math.max(
    0,
    ...results.map(({ data }) =>
      domainHours(
        domainOf(
          data.provenance.ephemeris.startUtc,
          data.provenance.ephemeris.endUtc,
        ),
      ),
    ),
  );
  const cursor = Math.min(cursorHours, Math.max(0, maxHours - 1));
  const activeForm = forms.find((form) => form.slot === activeSlot)!;
  const activeSite = sites.find((site) => site.id === activeForm.siteId)!;
  const activeResult = results.find((result) => result.slot === activeSlot);
  const step = Math.min(...forms.map((form) => form.stepMinutes)) / 60;
  const changeForm = (next: ReferenceScenarioForm) => {
    setPlaybackOwner(null);
    setForms((current) =>
      current.map((form) => (form.slot === next.slot ? next : form)),
    );
  };
  const selectSlot = (slot: 'A' | 'B') => {
    setPlaybackOwner(null);
    setActiveSlot(slot);
  };
  const shiftMatches =
    shiftKeys !== null &&
    forms.every((form, index) => requestKey(form) === shiftKeys[index]);
  const shiftReady =
    shiftMatches &&
    slots.every(
      (slot, index) =>
        slot.status === 'ready' && slot.requestKey === shiftKeys?.[index],
    );
  const shiftState = !shiftKeys
    ? 'idle'
    : !shiftMatches
      ? 'stale'
      : loading
        ? 'loading'
        : shiftReady
          ? 'ready'
          : 'error';

  return (
    <section className="workspace" aria-labelledby="workspace-heading">
      <div className="section-heading workspace-heading" data-reveal>
        <div>
          <p className="eyebrow">Explore / Mission control</p>
          <h2 id="workspace-heading">Explore the Moon.</h2>
          <p className="section-copy">
            Choose a location. Follow its sky. Find time with Sun and Earth in
            view.
          </p>
        </div>
        <span className="badge">
          <i className="earth-dot" /> VERIFIED DATA ·{' '}
          {modelBadge(
            results.map(({ slot, data }) => ({
              slot,
              horizonMode: data.horizonMode,
            })),
          )}
        </span>
      </div>
      <div className="mission-bar">
        <span>
          <strong>{activeSite.name}</strong>
        </span>
        <span>
          {Math.abs(activeSite.lat).toFixed(4)}°{activeSite.lat < 0 ? 'S' : 'N'}{' '}
          / {Math.abs(activeSite.lon).toFixed(4)}°
          {activeSite.lon < 0 ? 'W' : 'E'}
        </span>
        <span>
          {activeForm.startDate} → {activeForm.endDate}
        </span>
        <a href="#compare">Compare scenarios ↗</a>
      </div>
      <div className="mission-grid" data-reveal>
        <div className="mission-controls" id="scenario-controls">
          <div className="control-heading">
            <span className="micro-label">Choose your observer</span>
            <div className="toggle" role="group" aria-label="Edit scenario">
              {(['A', 'B'] as const).map((slot) => (
                <button
                  type="button"
                  key={slot}
                  aria-pressed={activeSlot === slot}
                  onClick={() => selectSlot(slot)}
                >
                  {slot}
                </button>
              ))}
            </div>
          </div>
          {forms.map((form, index) => (
            <div key={form.slot} hidden={activeSlot !== form.slot}>
              <ReferenceScenarioCard
                form={form}
                sites={sites}
                issues={
                  slots[index]?.status === 'error' && slots[index].message
                    ? [slots[index].message]
                    : []
                }
                onChange={changeForm}
              />
            </div>
          ))}
          <p className="hint custom-note">
            Have a specific location?{' '}
            <a href="#evaluate">Evaluate your coordinates →</a>
          </p>
          <div className="actions">
            <button
              type="button"
              disabled={loading}
              onClick={() => void evaluate(forms, sites)}
            >
              {loading ? 'Calculating…' : 'Update comparison'}{' '}
              <span aria-hidden="true">→</span>
            </button>
            <p role="status">
              {loading
                ? 'Evaluating archived ephemerides…'
                : anyStale
                  ? 'Inputs changed: results below are out of date until you update.'
                  : results.length
                    ? 'Results match the inputs above.'
                    : ''}
            </p>
          </div>
        </div>
        <div className="visual-stage">
          <div className="stage-toolbar">
            <span className="micro-label">OBSERVATION / {activeSlot}</span>
            <div className="toggle" role="group" aria-label="Visualization">
              <button
                type="button"
                aria-pressed={view === 'lander'}
                onClick={() => {
                  setPlaybackOwner(null);
                  setView('lander');
                }}
              >
                Lander view
              </button>
              <button
                type="button"
                aria-pressed={view === 'sky'}
                onClick={() => {
                  setPlaybackOwner(null);
                  setView('sky');
                }}
              >
                Sky dome
              </button>
              <button
                type="button"
                aria-pressed={view === 'map'}
                onClick={() => {
                  setPlaybackOwner(null);
                  setView('map');
                }}
              >
                Polar map
              </button>
            </div>
          </div>
          <div
            className="view-transition"
            key={`${view}-${activeSlot}-${activeResult?.data.horizonMode ?? 'loading'}-${activeResult?.data.siteId ?? ''}`}
          >
            {view === 'map' ? (
              <PolarSiteMap
                sites={sites}
                selectedId={activeForm.siteId}
                onSelect={(site) => changeForm(withSite(activeForm, site))}
              />
            ) : view === 'lander' && activeResult ? (
              <LanderView
                key={slots[activeSlot === 'A' ? 0 : 1].requestKey}
                results={results}
                selectedSlot={activeSlot}
                onSelectSlot={selectSlot}
                cursorHours={cursor}
                onCursorChange={setCursorHours}
                disabled={loading || anyStale}
                playing={playbackOwner === 'lander'}
                onPlayingChange={(playing) =>
                  setPlaybackOwner(playing ? 'lander' : null)
                }
              />
            ) : activeResult ? (
              <SkyExplorer
                key={`${activeResult.slot}-${activeResult.data.siteId}-${activeResult.data.horizonMode}`}
                result={activeResult}
                cursorHours={cursor}
                onCursorChange={setCursorHours}
              />
            ) : (
              <div className="visual-loading" aria-busy={loading}>
                <span className="loading-orbit" />
                <p>
                  {loading
                    ? 'Resolving your lunar sky…'
                    : 'Apply the mission parameters to explore the sky.'}
                </p>
                <span className="micro-label">
                  NASA/JPL HORIZONS · VERIFIED ARCHIVE
                </span>
              </div>
            )}
          </div>
        </div>
        <MissionInsights result={activeResult} cursorHours={cursor} />
      </div>
      <details className="provenance-details">
        <summary>
          Dataset, observer and model provenance{' '}
          <span>NASA/JPL Horizons + NASA LOLA</span>
        </summary>
        <DataSourceBanner catalog={catalog.data} results={results} />
      </details>
      {results.length > 0 && (
        <>
          <section id="compare" className="comparison-section" data-reveal>
            <div className="section-heading">
              <div>
                <p className="eyebrow">Compare / Mission opportunities</p>
                <h2>Compare two scenarios</h2>
                <p className="section-copy">
                  Which lunar location better supports your mission?
                </p>
              </div>
              <PlaybackControl
                playing={playbackOwner === 'samples'}
                onPlayingChange={(playing) =>
                  setPlaybackOwner(playing ? 'samples' : null)
                }
                hours={cursor}
                max={Math.max(0, maxHours - step)}
                step={step}
                disabled={loading || anyStale}
                onChange={setCursorHours}
              />
            </div>
            <div
              className="comparison-edit-actions"
              role="group"
              aria-label="Change comparison scenarios"
            >
              {(['A', 'B'] as const).map((slot) => (
                <button
                  type="button"
                  key={slot}
                  onClick={() => {
                    selectSlot(slot);
                    document
                      .getElementById('scenario-controls')
                      ?.scrollIntoView({
                        behavior: window.matchMedia(
                          '(prefers-reduced-motion: reduce)',
                        ).matches
                          ? 'instant'
                          : 'smooth',
                        block: 'center',
                      });
                  }}
                >
                  Edit scenario {slot} <span aria-hidden="true">↗</span>
                </button>
              ))}
            </div>
            <ComparisonTimeline
              results={results}
              cursorHours={cursor}
              onCursorChange={setCursorHours}
            />
          </section>
          <MissionWindowFinder
            results={results}
            onJump={(hours) => {
              setCursorHours(hours);
              document
                .getElementById('timeline-heading')
                ?.scrollIntoView({ behavior: 'smooth' });
            }}
          />
          <details className="elevation-details mission-planning-details">
            <summary>
              Compare a shifted mission period <span>Advanced planning</span>
            </summary>
            <MissionShift
              form={forms[0]}
              site={sites.find((site) => site.id === forms[0].siteId)!}
              disabled={loading}
              comparisonState={shiftState}
              results={shiftReady ? results : []}
              onApply={(next) => {
                setShiftKeys(next.map(requestKey));
                setForms(next);
                setCursorHours(0);
                void evaluate(next, sites);
              }}
            />
          </details>
          <details className="elevation-details">
            <summary>
              Inspect azimuth / elevation detail <span>Cartesian view ↗</span>
            </summary>
            <AzimuthElevationChart results={results} cursorHours={cursor} />
          </details>
        </>
      )}
    </section>
  );
}
