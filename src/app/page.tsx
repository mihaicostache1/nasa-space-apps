import { ScenarioWorkspace } from '@/features/scenarios/components/scenario-workspace';
import { LunarPortrait } from '@/features/mission/components/lunar-portrait';
import { MissionNavigation } from '@/features/mission/components/mission-navigation';
import { ExperienceMotion } from '@/features/mission/components/experience-motion';
import { HorizonLesson } from '@/features/mission/components/horizon-lesson';

export default function Home() {
  return (
    <ExperienceMotion>
      <a className="skip-link" href="#explore">
        Skip to mission explorer
      </a>
      <MissionNavigation />
      <main>
        <section className="hero" id="overview" aria-labelledby="hero-heading">
          <div className="hero-copy">
            <p className="eyebrow">
              <span className="eyebrow-line" />
              LUNAR EXPLORATION / MISSION INTELLIGENCE
            </p>
            <h1 id="hero-heading">
              <span className="headline-line">Every landing</span>
              <span className="headline-line">has a window.</span>
              <span className="headline-line">
                <em>Find yours.</em>
              </span>
            </h1>
            <p className="hero-description">
              See the Moon from your landing site. Explore sunlight, Earth
              visibility, and the moments when they align.
            </p>
            <div className="hero-actions">
              <a className="primary-link" href="#explore">
                Explore the Moon <span aria-hidden="true">↗</span>
              </a>
              <a className="text-link" href="#learn">
                Discover the science <span aria-hidden="true">→</span>
              </a>
            </div>
            <p className="hero-provenance">
              <i className="earth-dot" /> NASA/JPL HORIZONS <span>×</span> NASA
              LOLA
              <br />
              <small>
                Real archived observations. Clearly stated assumptions.
              </small>
            </p>
          </div>
          <LunarPortrait />
          <a href="#explore" className="hero-scroll">
            <span aria-hidden="true">↓</span> SCROLL TO MISSION CONTROL
          </a>
        </section>
        <div className="mission-intro" data-reveal>
          <p>
            Where you land changes
            <br />
            <strong>what becomes possible.</strong>
          </p>
          <span>
            EXPLORE THE SITE.
            <br />
            UNDERSTAND THE SKY.
            <br />
            FIND THE WINDOW.
          </span>
        </div>
        <div id="explore" className="explorer-anchor">
          <ScenarioWorkspace />
        </div>
        <section
          className="learn-section"
          id="learn"
          aria-labelledby="learn-heading"
          data-reveal
        >
          <div className="section-heading">
            <div>
              <p className="eyebrow">03 / A LITTLE LUNAR PERSPECTIVE</p>
              <h2 id="learn-heading">The horizon changes everything.</h2>
            </div>
            <p className="section-copy">
              Two lines of sight.
              <br />
              One operational decision.
            </p>
          </div>
          <div className="learn-grid">
            <article data-reveal>
              <span className="lesson-number">01 / LIGHT</span>
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
              <span className="lesson-number">02 / CONNECTION</span>
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
              <span className="lesson-number">03 / POSSIBILITY</span>
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
        </section>
        <HorizonLesson />
        <section
          className="methodology-section"
          id="methodology"
          aria-labelledby="methodology-heading"
          data-reveal
        >
          <div>
            <p className="eyebrow">04 / THE SCIENCE BEHIND THE VIEW</p>
            <h2 id="methodology-heading">
              Designed for discovery.
              <br />
              Grounded in evidence.
            </h2>
            <p className="section-copy">
              Every result has a source.
              <br />
              Every model has a limit.
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
                <span>01</span> The observations
              </summary>
              <p>
                Sun and Earth directions come from archived NASA/JPL Horizons
                ephemerides. The catalog reports each site&apos;s available
                dates and sampling intervals. Changing the selection never
                downloads or invents missing observations.
              </p>
            </details>
            <details>
              <summary>
                <span>02</span> The local horizon
              </summary>
              <p>
                Geometric mode uses a flat 0° horizon. Reviewed terrain mode is
                available only at Site01, using checksummed LOLA DEMs and the 0
                m reference mast. These are DEM reference points, not approved
                landing targets.
              </p>
            </details>
            <details>
              <summary>
                <span>03</span> The assumptions
              </summary>
              <p>
                The DE421 MOON_ME terrain frame and DE441 MEAN_ME ephemerides
                have different realizations. Terrain requires explicit
                acceptance of an approximation; no transformation is applied. A
                2 m mast can shift the current horizon by up to 1.9°, requiring
                matching observer data.
              </p>
            </details>
            <details>
              <summary>
                <span>04</span> The limits
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
          <p>See the Moon from your landing site.</p>
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
