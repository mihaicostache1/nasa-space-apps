'use client';

import { useEffect, useState } from 'react';

const destinations = [
  ['explore', 'Explore'],
  ['compare', 'Compare'],
  ['learn', 'Learn'],
  ['methodology', 'Methodology'],
] as const;

export function MissionNavigation() {
  const [active, setActive] = useState('overview');
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const ids = ['overview', ...destinations.map(([id]) => id)];
    let frame = 0;
    const update = () => {
      frame = 0;
      const header = document.querySelector('.masthead');
      const threshold = (header?.getBoundingClientRect().height ?? 80) + 72;
      let current = 'overview';
      for (const id of ids) {
        const element = document.getElementById(id);
        if (element && element.getBoundingClientRect().top <= threshold)
          current = id;
      }
      if (
        window.scrollY + window.innerHeight >=
        document.documentElement.scrollHeight - 2
      ) {
        current =
          [...ids].reverse().find((id) => document.getElementById(id)) ??
          current;
      }
      setActive(current);
      setScrolled(window.scrollY > 16);
    };
    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(update);
    };
    const mutations = new MutationObserver(schedule);
    mutations.observe(document.body, { childList: true, subtree: true });
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    schedule();
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      mutations.disconnect();
    };
  }, []);
  return (
    <header className="masthead" data-scrolled={scrolled}>
      <a
        className="wordmark"
        href="#overview"
        aria-label="LunarWindow overview"
      >
        <span className="brand-orbit" aria-hidden="true" />
        Lunar<span>Window</span>
      </a>
      <nav aria-label="Main navigation">
        {destinations.map(([id, label]) => (
          <a
            key={id}
            href={`#${id}`}
            aria-current={active === id ? 'location' : undefined}
            onClick={(event) => {
              if (!document.getElementById(id)) {
                event.preventDefault();
                document.getElementById('explore')?.scrollIntoView();
              }
            }}
          >
            {label}
          </a>
        ))}
      </nav>
      <a className="launch-link" href="#explore">
        Mission control <span aria-hidden="true">↗</span>
      </a>
      <div className="journey-progress" aria-hidden="true">
        <i />
      </div>
    </header>
  );
}
