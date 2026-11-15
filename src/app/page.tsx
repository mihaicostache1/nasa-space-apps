import { ScenarioWorkspace } from '@/features/scenarios/components/scenario-workspace';
import { LunarPortrait } from '@/features/mission/components/lunar-portrait';
import { MissionNavigation } from '@/features/mission/components/mission-navigation';
import { ExperienceMotion } from '@/features/mission/components/experience-motion';
import { HorizonLesson } from '@/features/mission/components/horizon-lesson';
import { CustomEvaluationWorkspace } from '@/features/custom/components/custom-evaluation-workspace';
import { referenceBootstrap } from '@/features/scenarios/lib/reference-bootstrap.server';

export default function Home() {
  return (
    <ExperienceMotion>
      <a className="skip-link" href="#explore">
        Skip to mission explorer
      </a>
      <MissionNavigation />
      <main>
        <section
          className="hero editorial-hero"
          id="overview"
          aria-labelledby="hero-heading"
        >
          <div className="hero-copy">
            <p className="eyebrow">Lunar mission intelligence</p>
            <h1 id="hero-heading">
              <span className="headline-line">Every landing</span>
              <span className="headline-line">has a window.</span>
              <span className="headline-line">
                <em>Find yours.</em>
              </span>
            </h1>
            <p className="hero-description">
              Explore sunlight, Earth visibility, and operational windows across
              the lunar surface.
            </p>
            <div className="hero-actions">
              <a className="primary-link" href="#explore">
                Explore the Moon <span aria-hidden="true">↗</span>
              </a>
              <a className="text-link" href="#compare">
                Compare locations <span aria-hidden="true">→</span>
              </a>
            </div>
            <p className="hero-provenance">
              Two lines of sight. A clearer mission decision.
            </p>
          </div>
          <LunarPortrait />
          <a href="#explore" className="hero-scroll">
            <span aria-hidden="true">↓</span> Start exploring
          </a>
        </section>
        <aside className="credibility-strip" aria-label="Scientific foundation">
          <p>Evidence behind every window.</p>
          <ul>
            <li>NASA/JPL Horizons</li>
            <li>NASA LOLA terrain</li>
            <li>Verified archives</li>
            <li>Transparent assumptions</li>
          </ul>
        </aside>
        <section
          className="product-pathways"
          aria-label="Choose your starting point"
          data-reveal
        >
          <article>
            <div className="pathway-visual pathway-explore" aria-hidden="true">
              <span />
              <i />
            </div>
            <h2>Explore the Moon</h2>
            <p>
              Discover how sunlight and Earth visibility change across lunar
              locations.
            </p>
            <a href="#explore">
              Explore a reference site <span aria-hidden="true">↗</span>
            </a>
          </article>
          <article>
            <div className="pathway-visual pathway-compare" aria-hidden="true">
              <span />
              <i />
            </div>
            <h2>Compare mission scenarios</h2>
            <p>
              Understand which locations provide better operational
              opportunities.
            </p>
            <a href="#compare">
              Compare two scenarios <span aria-hidden="true">↗</span>
            </a>
          </article>
          <article>
            <div className="pathway-visual pathway-evaluate" aria-hidden="true">
              <span />
              <i />
            </div>
            <h2>Evaluate your coordinates</h2>
            <p>
              Analyze a specific lunar observer using geographic coordinates.
            </p>
            <a href="#evaluate">
              Configure an observer <span aria-hidden="true">↗</span>
            </a>
          </article>
        </section>
        <div id="explore" className="explorer-anchor">
          <ScenarioWorkspace bootstrap={referenceBootstrap} />
        </div>
        <CustomEvaluationWorkspace />
        <section
          className="learn-section editorial-learn"
          id="learn"
          aria-labelledby="learn-heading"
          data-reveal
        >
          <div className="section-heading">
            <div>
              <p className="eyebrow">Learn the science</p>
              <h2 id="learn-heading">The horizon changes everything.</h2>
            </div>
            <p className="section-copy">
              Understand the geometry before you interpret the numbers.
            </p>
          </div>
          <div className="learn-grid">
            <article data-reveal>
              <span className="lesson-number">Sunlight</span>
              <div className="lesson-graphic solar-lesson" aria-hidden="true">
                <span />
                <i />
              </div>
              <h3>A low Sun. A long shadow.</h3>
              <p>
                At these south-polar sites, the Sun stays close to the horizon.
                A ridge can hide its disc even when it sits above a flat
                geometric horizon.
              </p>
              <a href="#explore">Inspect the Sun&apos;s path ↗</a>
            </article>
            <article data-reveal>
              <span className="lesson-number">Earth visibility</span>
              <div className="lesson-graphic earth-lesson" aria-hidden="true">
                <span />
                <i />
              </div>
              <h3>Earth isn&apos;t always in view.</h3>
              <p>
                The archived Earth track changes relative to the local horizon.
                Direct visibility opens a geometric opportunity; a working radio
                link needs further engineering.
              </p>
              <a href="#compare">Explore visibility windows ↗</a>
            </article>
            <article data-reveal>
              <span className="lesson-number">Operational windows</span>
              <div className="lesson-graphic joint-lesson" aria-hidden="true">
                <span />
                <i />
              </div>
              <h3>Find the overlap.</h3>
              <p>
                Joint windows mark the samples with Sun and Earth visible
                together. Their edges are bounded by the data cadence, not exact
                predicted event times.
              </p>
              <a href="#finder-heading">Find a window ↗</a>
            </article>
          </div>
          <p className="editorial-diagram-note">
            Conceptual diagrams illustrate the geometry; mission results come
            from the evaluated samples.
          </p>
        </section>
        <HorizonLesson />
        <section
          className="methodology-section editorial-methodology"
          id="methodology"
          aria-labelledby="methodology-heading"
          data-reveal
        >
          <div>
            <p className="eyebrow">Methodology</p>
            <h2 id="methodology-heading">
              Every result.
              <br />A traceable foundation.
            </h2>
            <p className="section-copy">
              Inspect the observations, the observer, and the assumptions behind
              the analysis.
            </p>
            <a
              className="text-link"
              href="https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/"
              target="_blank"
              rel="noreferrer"
            >
              NASA Space Apps challenge ↗
            </a>
          </div>
          <div className="methodology-rows">
            <details open>
              <summary>
                <span>01</span> Data provenance &amp; observations
              </summary>
              <p>
                Sun and Earth directions come from archived NASA/JPL Horizons
                ephemerides. The catalog reports each site&apos;s available
                dates and sampling intervals. Reference evaluations stay within
                that archive. Custom evaluation, when enabled by the server,
                fetches and archives observations for the requested observer.
                Missing samples are rejected rather than filled in.
              </p>
            </details>
            <details>
              <summary>
                <span>02</span> The observer &amp; coordinate system
              </summary>
              <p>
                Latitude and east-positive longitude identify a point on the
                Moon. Observer altitude combines ground elevation above the
                1737.4 km reference sphere and height above the ground. The
                reference archives use their recorded observer heights; changing
                a height requires matching observations and terrain.
              </p>
            </details>
            <details>
              <summary>
                <span>03</span> Geometric &amp; terrain horizons
              </summary>
              <p>
                Geometric mode compares directions with a flat 0° local horizon.
                Terrain mode compares them with a DEM-derived skyline. The
                reference catalog advertises reviewed masks; Site01 currently
                has a reviewed 0 m mask. Custom terrain is preliminary, needs
                configured DEMs and complete ray coverage, and never silently
                falls back to geometric mode.
              </p>
            </details>
            <details>
              <summary>
                <span>04</span> Visibility, windows &amp; time
              </summary>
              <p>
                The selected any-disc, body-center, or full-disc rule determines
                visibility relative to the horizon. The engine holds each
                sampled state until the next sample and groups consecutive
                states into windows. Setting times are bracketed by the sample
                cadence. Windows clipped by the evaluation period are lower
                bounds, not measured complete events.
              </p>
            </details>
            <details>
              <summary>
                <span>05</span> Frames, resolution &amp; height sensitivity
              </summary>
              <p>
                DE421 MOON_ME terrain and the Horizons Mean Earth orientation
                are paired only with explicit acceptance of the documented
                approximation. No frame transformation is applied. DEM
                resolution and observer height affect the skyline: a 2 m mast
                changed the Site01 reference horizon by up to 1.9°. That
                sensitivity is specific to Site01, not a rule for every site.
              </p>
            </details>
            <details>
              <summary>
                <span>06</span> Scientific &amp; operational limits
              </summary>
              <p>
                Visibility is sample-based geometric line of sight. The model
                does not calculate eclipses, power production, radio-link
                quality, or landing safety. The elevated-observer QuickMap
                checks do not independently validate surface terrain shadows.
              </p>
            </details>
          </div>
        </section>
      </main>
      <footer>
        <a className="wordmark" href="#overview">
          <span className="brand-orbit" aria-hidden="true" />
          LUNAR<span>WINDOW</span>
        </a>
        <div>
          <p>A clearer view of your mission window.</p>
          <p>NASA Space Apps 2026 · Independent challenge project</p>
        </div>
        <p className="footer-attribution">
          Moon artwork:{' '}
          <a
            href="https://svs.gsfc.nasa.gov/5416/"
            target="_blank"
            rel="noreferrer"
          >
            NASA&apos;s Scientific Visualization Studio
          </a>{' '}
          / LRO LROC.
          <br />
          LRO-based visualization with illustrative shading; the polar map is a
          coordinate diagram.
        </p>
      </footer>
    </ExperienceMotion>
  );
}
