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
        <p className="eyebrow">NASA SPACE APPS 2026 · LUNAR SOUTH POLE</p>
        <h1>
          Find a window
          <br />
          to the Sun and Earth.
        </h1>
        <p>
          Compare lunar south-pole reference sites and dates: when is the Sun up
          for power, when is Earth up for a direct link, and when are both up at
          once?
        </p>
      </section>
      <ScenarioWorkspace />
      <footer>
        <p>
          <strong>Sources.</strong> Sun and Earth positions: NASA/JPL Horizons,
          archived offline (DE441). Site coordinates and heights: NASA GSFC PGDA
          LOLA digital elevation models (DE421 MOON_ME, 1737.4 km sphere).
        </p>
        <p>
          <strong>Limits.</strong> Results use a flat 0° horizon: local terrain,
          eclipses, power generation and radio-link performance are not
          modelled, and event times are bracketed by the sampling interval. The
          reference points are DEM grid cells, not landing recommendations. The
          QuickMap cross-checks validate the displayed Sun and Earth angles for
          observers about 100–144 km above the surface; they do not validate
          terrain shadows seen from the ground.
        </p>
      </footer>
    </main>
  );
}
