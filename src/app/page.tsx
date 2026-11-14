import Link from 'next/link';
import { ScenarioWorkspace } from '@/features/scenarios/components/scenario-workspace';

export default function Home() {
  return (
    <main>
      <header className="masthead">
        <Link className="wordmark" href="/">
          LUNAR / NAVIGATOR
        </Link>
        <a
          href="https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/"
          target="_blank"
          rel="noreferrer"
        >
          Challenge brief ↗
        </a>
      </header>
      <section className="intro">
        <p className="eyebrow">LUNAR SOUTH POLE / OPERATIONS PLANNING</p>
        <h1>
          Find a window
          <br />
          to the Sun and Earth.
        </h1>
        <p>
          Two locations. One mission decision. Compare sunlight, Earth
          visibility, and the windows that keep your mission connected.
        </p>
        <nav className="mission-nav" aria-label="Dashboard sections">
          <a href="#workspace-heading">01 / Plan</a>
          <a href="#operations-heading">02 / Operations</a>
          <a href="#timeline-heading">03 / Timeline</a>
          <a href="#finder-heading">04 / Windows</a>
        </nav>
      </section>
      <ScenarioWorkspace />
      <footer>
        <p>
          <strong>Sources.</strong> Sun and Earth positions: NASA/JPL Horizons,
          archived offline (DE441). Site coordinates and heights: NASA GSFC PGDA
          LOLA digital elevation models (DE421 MOON_ME, 1737.4 km sphere).
        </p>
        <p>
          <strong>Limits.</strong> Results use a flat 0° horizon unless the
          reviewed LOLA terrain horizon is selected, which exists for one
          reference point. Eclipses, power generation and radio-link performance
          are not modelled, and event times are bracketed by the sampling
          interval. The reference points are DEM grid cells, not landing
          recommendations. The QuickMap cross-checks validate the displayed Sun
          and Earth angles for observers about 100–144 km above the surface;
          they do not validate terrain shadows seen from the ground.
        </p>
      </footer>
    </main>
  );
}
