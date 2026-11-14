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
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries)
          if (entry.isIntersecting) setActive(entry.target.id);
      },
      { rootMargin: '-15% 0px -65% 0px' },
    );
    const ids = ['overview', ...destinations.map(([id]) => id)];
    const observed = new Set<Element>();
    const observeSections = () => {
      for (const id of ids) {
        const element = document.getElementById(id);
        if (element && !observed.has(element)) {
          observed.add(element);
          observer.observe(element);
        }
      }
      if (observed.size === ids.length) mutations.disconnect();
    };
    const mutations = new MutationObserver(observeSections);
    mutations.observe(document.body, { childList: true, subtree: true });
    observeSections();
    return () => {
      observer.disconnect();
      mutations.disconnect();
    };
  }, []);
  return (
    <header className="masthead">
      <a
        className="wordmark"
        href="#overview"
        aria-label="LunarWindow overview"
      >
        <span className="brand-orbit" aria-hidden="true" />
        LUNAR<span>WINDOW</span>
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
