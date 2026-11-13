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
        <p className="eyebrow">NASA SPACE APPS 2026 · PROJECT STARTER</p>
        <h1>
          Find a window
          <br />
          to the Sun and Earth.
        </h1>
        <p>
          Compare lunar locations and mission dates. Start with two scenarios,
          then connect ephemeris data to explore sunlight and direct-to-Earth
          visibility.
        </p>
      </section>
      <ScenarioWorkspace />
      <footer>
        This starter has no ephemeris or terrain data connected. Coordinates
        below are illustrative inputs; no landing recommendation is produced.
      </footer>
    </main>
  );
}
