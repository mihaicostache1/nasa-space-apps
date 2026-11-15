// Imported only by the server page: release data never becomes client JavaScript.
import metadata from '../../../../data/frontend/reference-bootstrap.json';
import site01 from '../../../../data/releases/lunarwindow-demo-v1/bundle/cfd797e74c84793cecb70df8144806430336242d9a5c8cc5fbf2549251be3340.json';
import site23 from '../../../../data/releases/lunarwindow-demo-v1/bundle/c269f1768c2ce7165a4cf67b9ce3c349dca8f433ac6d437762ccb04a2aed758d.json';
import type { ReferenceSiteCatalog } from '@/domain/reference';
import type { ReferenceEvaluationContract } from '@/domain/terrain-evaluation';
import { bootstrapForms, type ReferenceBootstrap } from './reference-bootstrap';

const payloads = [site01, site23];

/** CI verifies metadata, original response hashes, and current NASA/LOLA evidence. */
export const referenceBootstrap: ReferenceBootstrap = {
  releaseId: metadata.releaseId,
  catalog: metadata.catalog as ReferenceSiteCatalog,
  scenarios: metadata.scenarios.map((scenario, index) => ({
    slot: scenario.slot as 'A' | 'B',
    request:
      scenario.request as ReferenceBootstrap['scenarios'][number]['request'],
    artifactSha256: scenario.output.sha256,
    data: payloads[index] as ReferenceEvaluationContract,
  })),
};

bootstrapForms(referenceBootstrap);
