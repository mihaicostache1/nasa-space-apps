'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReferenceSiteCatalog } from '@/domain/reference';
import type { ReferenceEvaluationContract } from '@/domain/terrain-evaluation';
import {
  ApiError,
  evaluateReference,
  fetchReferenceSites,
} from '@/lib/api-client';
import { ComparisonTimeline } from '@/features/analysis/components/comparison-timeline';
import { DataSourceBanner } from '@/features/analysis/components/data-source-banner';
import { LanderView } from '@/features/analysis/components/lander-view';
import { MissionWindowFinder } from '@/features/analysis/components/mission-window-finder';
import { SkyExplorer } from '@/features/analysis/components/sky-explorer';
import { modelBadge } from '@/features/analysis/lib/model';
import { domainHours, domainOf } from '@/features/analysis/lib/timeline';
import type { ScenarioResult } from '@/features/analysis/types';
import {
  defaultForm,
  toRequest,
  validateForm,
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
  const inFlight = useRef<AbortController | null>(null);

  const evaluate = useCallback(
    async (
      current: ReferenceScenarioForm[],
      sites: ReferenceSiteCatalog['sites'],
    ) => {
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

  return (
    <section className="workspace" aria-labelledby="workspace-heading">
      <div className="section-heading">
        <h2 id="workspace-heading">Compare two scenarios</h2>
        <span className="badge">
          ARCHIVED NASA DATA ·{' '}
          {modelBadge(
            results.map((result) => ({
              slot: result.slot,
              horizonMode: result.data.horizonMode,
            })),
          )}
        </span>
      </div>
      <DataSourceBanner catalog={catalog.data} results={results} />
      <div className="scenarios">
        {forms.map((form, index) => (
          <ReferenceScenarioCard
            key={form.slot}
            form={form}
            sites={sites}
            issues={
              slots[index]?.status === 'error' && slots[index].message
                ? [slots[index].message]
                : []
            }
            onChange={(next) =>
              setForms((current) =>
                current.map((f, i) => (i === index ? next : f)),
              )
            }
          />
        ))}
      </div>
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
      {results.length > 0 && (
        <>
          <LanderView
            results={results}
            cursorHours={cursor}
            onCursorChange={setCursorHours}
          />
          <ComparisonTimeline
            results={results}
            cursorHours={cursor}
            onCursorChange={setCursorHours}
          />
          <MissionWindowFinder
            results={results}
            onJump={(hours) => {
              setCursorHours(hours);
              document
                .getElementById('timeline-heading')
                ?.scrollIntoView({ behavior: 'smooth' });
            }}
          />
          <SkyExplorer results={results} cursorHours={cursor} />
        </>
      )}
    </section>
  );
}
