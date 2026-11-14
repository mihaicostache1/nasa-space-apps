'use client';

import { useEffect, useRef, type ReactNode } from 'react';

/** Progressive enhancement: content stays visible without JavaScript or motion. */
export function ExperienceMotion({ children }: { children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = root.current;
    if (!element || !('IntersectionObserver' in window)) return;
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;
    const observed = new WeakSet<Element>();
    const reveal = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            (entry.target as HTMLElement).dataset.revealed = 'true';
            reveal.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.06, rootMargin: '0px 0px -24px 0px' },
    );
    const discover = () => {
      element
        .querySelectorAll<HTMLElement>('[data-reveal]')
        .forEach((section) => {
          if (preference.matches) section.dataset.revealed = 'true';
          else if (!observed.has(section)) {
            observed.add(section);
            reveal.observe(section);
          }
        });
    };
    const configure = () => {
      if (preference.matches) element.dataset.introComplete = 'true';
      element.dataset.motion = preference.matches ? 'reduced' : 'ready';
      discover();
    };
    const finishIntro = (event: AnimationEvent) => {
      if (event.animationName === 'panel-enter')
        element.dataset.introComplete = 'true';
    };
    const progress = () => {
      frame = 0;
      const scrollable =
        document.documentElement.scrollHeight - window.innerHeight;
      element.style.setProperty(
        '--journey-progress',
        `${scrollable > 0 ? Math.min(1, window.scrollY / scrollable) : 0}`,
      );
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(progress);
    };
    const mutations = new MutationObserver(() => {
      discover();
      schedule();
    });
    mutations.observe(element, { childList: true, subtree: true });
    preference.addEventListener('change', configure);
    element.addEventListener('animationend', finishIntro);
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    configure();
    progress();
    return () => {
      reveal.disconnect();
      mutations.disconnect();
      cancelAnimationFrame(frame);
      preference.removeEventListener('change', configure);
      element.removeEventListener('animationend', finishIntro);
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
    };
  }, []);
  return (
    <div ref={root} className="experience">
      {children}
    </div>
  );
}

/** Animate presentation only. Intermediate, uncomputed numeric values are never shown. */
export function MotionValue({
  children,
  className = '',
}: {
  children: string;
  className?: string;
}) {
  return (
    <span className={`motion-value ${className}`} key={children}>
      {children}
    </span>
  );
}
