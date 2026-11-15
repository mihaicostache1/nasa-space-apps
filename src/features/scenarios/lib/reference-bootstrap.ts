import type { ReferenceEvaluationRequest } from '@/domain/evaluation';
import type { ReferenceSiteCatalog } from '@/domain/reference';
import type { ReferenceEvaluationContract } from '@/domain/terrain-evaluation';
import type { Slot } from '@/features/analysis/types';
import { defaultForm, toRequest } from './reference-scenario';

export type ReferenceBootstrap = {
  releaseId: string;
  catalog: ReferenceSiteCatalog;
  scenarios: {
    slot: Slot;
    request: ReferenceEvaluationRequest;
    artifactSha256: string;
    data: ReferenceEvaluationContract;
  }[];
};

/** Reject a changed UI default rather than showing a snapshot for different inputs. */
export function bootstrapForms(bootstrap: ReferenceBootstrap) {
  if (
    bootstrap.scenarios.length !== 2 ||
    bootstrap.scenarios[0].slot !== 'A' ||
    bootstrap.scenarios[1].slot !== 'B'
  ) {
    throw new Error('Startup snapshots must describe scenarios A and B.');
  }
  return bootstrap.scenarios.map(({ slot, request }) => {
    const site = bootstrap.catalog.sites.find(
      (site) => site.id === request.siteId,
    );
    if (!site)
      throw new Error('Startup snapshot is missing its reference site.');
    const form = defaultForm(slot, site);
    const expected = toRequest(form);
    if (
      Object.entries(expected).some(
        ([key, value]) =>
          request[key as keyof ReferenceEvaluationRequest] !== value,
      ) ||
      Object.keys(request).length !== Object.keys(expected).length
    ) {
      throw new Error('Startup snapshot does not match the default scenario.');
    }
    return form;
  });
}
