'use client';

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent,
} from 'react';
import {
  angleDelta,
  cameraElevation,
  createSkyTrack,
  discAgainstSkyline,
  earthIllumination,
  horizonElAt,
  project,
  skyDrift,
  starAzimuth,
  starField,
  wrap360,
  type BodyState,
  type Camera,
  type SkyState,
} from '../lib/lander-view';
import { HOUR_MS, domainHours, domainOf, formatUtc } from '../lib/timeline';
import type { ScenarioResult, Slot } from '../types';

type Target = 'earth' | 'sun' | 'free';

/** Simulated hours per real second. */
const SPEEDS = [
  { hours: 6, label: '6 h/s' },
  { hours: 24, label: '1 day/s' },
  { hours: 72, label: '3 days/s' },
];
const STARS = starField(700);
const MINIMAP_H = 30;
const RULER_H = 24;
/** Throttle for pushing the playhead into the shared cursor (and the page). */
const REPORT_MS = 80;

const COLORS = {
  sun: '#f5c451',
  earth: '#6cb4ff',
  muted: '#a8b6c6',
  accent: '#d0f28c',
  danger: '#ff9b8a',
};

type Props = {
  results: ScenarioResult[];
  cursorHours: number;
  onCursorChange: (hours: number) => void;
};

type Scene = {
  track: (timeMs: number) => SkyState | null;
  drift: number;
  horizon: { el: number }[];
  terrain: boolean;
  label: string;
  startMs: number;
  totalHours: number;
  step: number;
  target: Target;
  speed: number;
  playing: boolean;
  onCursorChange: (hours: number) => void;
};

/** A lander's-eye camera on the real Sun and Earth tracks, at true angular scale. */
export function LanderView({ results, cursorHours, onCursorChange }: Props) {
  const [selected, setSelected] = useState<Slot>('A');
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(24);
  const [target, setTarget] = useState<Target>('earth');

  const result = results.find((r) => r.slot === selected) ?? results[0];
  const { data } = result;
  const startMs = Date.parse(data.provenance.ephemeris.startUtc);
  const totalHours = domainHours(
    domainOf(
      data.provenance.ephemeris.startUtc,
      data.provenance.ephemeris.endUtc,
    ),
  );
  const step = data.calculation.stepMinutes / 60;
  const track = useMemo(
    () => createSkyTrack(data.series, data.calculation.stepMinutes),
    [data],
  );
  const drift = useMemo(() => skyDrift(data.series), [data]);
  const terrain = data.horizonMode === 'terrain';

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<Scene | null>(null);
  const timeRef = useRef(cursorHours);
  const reportedRef = useRef(cursorHours);
  const lastReportRef = useRef(0);
  const cameraRef = useRef<{ az: number; el: number } | null>(null);
  const frameRef = useRef<number | null>(null);
  const lastFrameRef = useRef<number | null>(null);
  const sizeRef = useRef({ width: 0, height: 0 });
  const reducedMotionRef = useRef(false);
  const dragRef = useRef<{ x: number; y: number } | null>(null);

  const draw = useCallback((dt: number): boolean => {
    const scene = sceneRef.current;
    const canvas = canvasRef.current;
    const { width, height } = sizeRef.current;
    const ctx = canvas?.getContext('2d');
    if (!scene || !canvas || !ctx || !width) return true;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const hours = timeRef.current;
    const state = scene.track(scene.startMs + hours * HOUR_MS);
    const pxPerDeg = Math.min(22, Math.max(10, width / 46));
    const viewHeightDeg = height / pxPerDeg;

    let settled = true;
    if (state) {
      const body =
        scene.target === 'sun'
          ? state.sun
          : scene.target === 'earth'
            ? state.earth
            : null;
      const current = cameraRef.current;
      const desired = body
        ? { az: body.az, el: cameraElevation(body.el, viewHeightDeg) }
        : (current ?? { az: state.earth.az, el: 1 });
      if (!current || reducedMotionRef.current) {
        cameraRef.current = desired;
      } else {
        const k = 1 - Math.exp(-dt * 7);
        const dAz = angleDelta(current.az, desired.az);
        const dEl = desired.el - current.el;
        if (Math.abs(dAz) < 0.01 && Math.abs(dEl) < 0.01) {
          cameraRef.current = desired;
        } else {
          settled = false;
          cameraRef.current = {
            az: wrap360(current.az + dAz * k),
            el: current.el + dEl * k,
          };
        }
      }
    }
    const view = cameraRef.current ?? { az: 0, el: 1 };
    const camera: Camera = { ...view, pxPerDeg, width, height };
    drawScene(ctx, camera, scene, state, hours);
    return settled;
  }, []);

  const frame = useCallback(
    function step(now: number) {
      const scene = sceneRef.current;
      const last = lastFrameRef.current;
      const dt = last === null ? 0 : Math.min(0.1, (now - last) / 1000);
      lastFrameRef.current = now;
      if (scene?.playing) {
        let t = timeRef.current + dt * scene.speed;
        if (t >= scene.totalHours) t = 0;
        timeRef.current = t;
        const snapped = Math.floor(t / scene.step) * scene.step;
        if (
          snapped !== reportedRef.current &&
          now - lastReportRef.current >= REPORT_MS
        ) {
          reportedRef.current = snapped;
          lastReportRef.current = now;
          scene.onCursorChange(snapped);
        }
      }
      const settled = draw(dt);
      if (scene?.playing || !settled) {
        frameRef.current = requestAnimationFrame(step);
      } else {
        frameRef.current = null;
        lastFrameRef.current = null;
      }
    },
    [draw],
  );

  const requestFrame = useCallback(() => {
    if (frameRef.current !== null) return;
    lastFrameRef.current = null;
    frameRef.current = requestAnimationFrame(frame);
  }, [frame]);

  // Latest inputs for the animation loop, which runs outside React renders.
  useLayoutEffect(() => {
    sceneRef.current = {
      track,
      drift,
      horizon: data.horizon,
      terrain,
      label: `${result.slot} · ${data.site}`,
      startMs,
      totalHours,
      step,
      target,
      speed,
      playing,
      onCursorChange,
    };
    requestFrame();
  });

  // Follow the shared cursor when someone else moves it (slider, window finder).
  useEffect(() => {
    if (cursorHours === reportedRef.current) return;
    reportedRef.current = cursorHours;
    timeRef.current = cursorHours;
    requestFrame();
  }, [cursorHours, requestFrame]);

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    reducedMotionRef.current = query.matches;
    const update = () => (reducedMotionRef.current = query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;
    const resize = () => {
      const width = wrap.clientWidth;
      const height = Math.round(Math.min(420, Math.max(280, width * 0.42)));
      const dpr = window.devicePixelRatio || 1;
      sizeRef.current = { width, height };
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.height = `${height}px`;
      draw(0);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [draw]);

  useEffect(
    () => () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    },
    [],
  );

  function togglePlay() {
    if (playing) {
      const snapped = Math.floor(timeRef.current / step) * step;
      timeRef.current = snapped;
      reportedRef.current = snapped;
      onCursorChange(snapped);
    } else if (timeRef.current >= totalHours - step) {
      timeRef.current = 0;
    }
    setPlaying(!playing);
  }

  function onPointerDown(event: PointerEvent<HTMLCanvasElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - box.left;
    const y = event.clientY - box.top;
    if (y < MINIMAP_H) {
      // The strip maps 0–360° across the width: jump the camera there.
      const az = ((x - 8) / (box.width - 16)) * 360;
      cameraRef.current = {
        az: wrap360(az),
        el: cameraRef.current?.el ?? 1,
      };
      setTarget('free');
      requestFrame();
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { x: event.clientX, y: event.clientY };
  }

  function onPointerMove(event: PointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current;
    const camera = cameraRef.current;
    if (!drag || !camera) return;
    const pxPerDeg = Math.min(22, Math.max(10, sizeRef.current.width / 46));
    const limit = sizeRef.current.height / pxPerDeg / 2 - 2;
    cameraRef.current = {
      az: wrap360(camera.az - (event.clientX - drag.x) / pxPerDeg),
      el: Math.min(
        limit,
        Math.max(-limit, camera.el + (event.clientY - drag.y) / pxPerDeg),
      ),
    };
    dragRef.current = { x: event.clientX, y: event.clientY };
    if (target !== 'free') setTarget('free');
    requestFrame();
  }

  const shown = track(startMs + cursorHours * HOUR_MS);

  return (
    <section className="analysis" aria-labelledby="lander-heading">
      <div className="section-heading">
        <h2 id="lander-heading">Lander&apos;s view</h2>
        {results.length > 1 && (
          <div className="toggle" role="group" aria-label="Scenario">
            {results.map((r) => (
              <button
                key={r.slot}
                type="button"
                aria-pressed={r.slot === result.slot}
                onClick={() => setSelected(r.slot)}
              >
                {r.slot}
              </button>
            ))}
          </div>
        )}
      </div>
      <figure className="panel lander">
        <div className="lander-controls">
          <button type="button" className="play" onClick={togglePlay}>
            {playing ? 'Pause' : 'Play the period'}
          </button>
          <div className="toggle" role="group" aria-label="Playback speed">
            {SPEEDS.map((option) => (
              <button
                key={option.hours}
                type="button"
                aria-pressed={speed === option.hours}
                onClick={() => setSpeed(option.hours)}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="toggle" role="group" aria-label="Camera">
            {(['earth', 'sun', 'free'] as Target[]).map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={target === option}
                onClick={() => setTarget(option)}
              >
                {option === 'earth'
                  ? 'Follow Earth'
                  : option === 'sun'
                    ? 'Follow Sun'
                    : 'Free look'}
              </button>
            ))}
          </div>
        </div>
        <div className="lander-canvas" ref={wrapRef}>
          <canvas
            ref={canvasRef}
            role="img"
            aria-label="Animated view from the reference point toward the horizon, drawn from the archived Sun and Earth positions"
            aria-describedby="lander-caption"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={() => (dragRef.current = null)}
            onPointerCancel={() => (dragRef.current = null)}
          />
        </div>
        <figcaption id="lander-caption">
          <span className="slot">{result.slot}</span> {data.site},{' '}
          {terrain ? 'reviewed LOLA terrain skyline' : 'flat 0° horizon'}.{' '}
          {describe(shown, startMs + cursorHours * HOUR_MS)} Angular sizes and
          positions are to scale; the camera follows the selected body, and the
          strip at the top shows the whole horizon. Drag to look around.
        </figcaption>
      </figure>
    </section>
  );
}

function describe(state: SkyState | null, timeMs: number): string {
  if (!state) return 'The cursor is outside this scenario’s period.';
  const { fraction } = earthIllumination(state.sun, state.earth);
  const body = (name: string, b: BodyState) =>
    `${name} is ${b.visible ? 'visible' : 'hidden'}, ${b.el.toFixed(1)}° elevation at ${b.az.toFixed(0)}° azimuth`;
  return `At ${formatUtc(timeMs)} the ${body('Sun', state.sun)}; ${body('Earth', state.earth)}, ${Math.round(fraction * 100)}% lit.`;
}

function drawScene(
  ctx: CanvasRenderingContext2D,
  camera: Camera,
  scene: Scene,
  state: SkyState | null,
  hours: number,
) {
  const { width: w, height: h, pxPerDeg: ppd } = camera;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#020409';
  ctx.fillRect(0, 0, w, h);
  if (!state) {
    ctx.fillStyle = COLORS.muted;
    ctx.font = '12px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('Outside this scenario’s period', w / 2, h / 2);
    return;
  }
  const { sun, earth } = state;
  const sunUp = sun.visible;

  // Stars: no atmosphere, so the sky stays black; they turn with the sky.
  for (const star of STARS) {
    const p = project(
      camera,
      starAzimuth(star.az, hours, scene.drift),
      star.el,
    );
    if (p.x < 0 || p.x > w || p.y < 0 || p.y > h) continue;
    ctx.globalAlpha = 0.35 + 0.65 * star.brightness;
    ctx.fillStyle = '#e4ecff';
    const size = 0.9 + 1.6 * star.brightness;
    ctx.fillRect(p.x, p.y, size, size);
  }
  ctx.globalAlpha = 1;

  drawSun(
    ctx,
    camera,
    sun,
    discAgainstSkyline(sun, scene.horizon) !== 'hidden',
  );
  drawEarth(ctx, camera, earth, sun);

  // Ground, drawn over the bodies so the skyline occludes them for real.
  const horizonY: number[] = [];
  const ground = new Path2D();
  ground.moveTo(0, h);
  for (let x = 0; x <= w + 2; x += 2) {
    const az = camera.az + (x - w / 2) / ppd;
    const y = project(camera, az, horizonElAt(scene.horizon, az)).y;
    horizonY.push(y);
    ground.lineTo(x, y);
  }
  ground.lineTo(w, h);
  ground.closePath();
  const groundTop = Math.min(...horizonY);
  const base = ctx.createLinearGradient(0, groundTop, 0, h);
  base.addColorStop(0, sunUp ? '#4b4a47' : '#15171a');
  base.addColorStop(1, '#08090a');
  ctx.fillStyle = base;
  ctx.fill(ground);
  // Low sunlight brightens the terrain facing the Sun.
  if (sunUp) {
    const light = ctx.createLinearGradient(0, 0, w, 0);
    for (let i = 0; i <= 10; i++) {
      const az = camera.az + ((i / 10) * w - w / 2) / ppd;
      const facing = Math.max(
        0,
        Math.cos((angleDelta(az, sun.az) * Math.PI) / 180),
      );
      light.addColorStop(
        i / 10,
        `rgba(228, 224, 214, ${0.04 + 0.28 * facing ** 2})`,
      );
    }
    ctx.fillStyle = light;
    ctx.fill(ground);
  } else if (earth.visible) {
    // Earthshine is all that lights the ground once the Sun is gone.
    ctx.fillStyle = 'rgba(108, 180, 255, 0.05)';
    ctx.fill(ground);
  }
  ctx.beginPath();
  horizonY.forEach((y, i) => (i ? ctx.lineTo(i * 2, y) : ctx.moveTo(0, y)));
  ctx.strokeStyle = sunUp
    ? 'rgba(255, 236, 200, 0.85)'
    : 'rgba(150, 170, 190, 0.4)';
  ctx.lineWidth = 1.5;
  ctx.stroke();

  // Dashed outlines for whatever the skyline hides, drawn only over the ground.
  ctx.save();
  ctx.clip(ground);
  for (const [body, color] of [
    [sun, COLORS.sun],
    [earth, COLORS.earth],
  ] as const) {
    if (discAgainstSkyline(body, scene.horizon) === 'full') continue;
    const p = project(camera, body.az, body.el);
    ctx.beginPath();
    ctx.arc(p.x, p.y, Math.max(4, body.radiusDeg * ppd), 0, Math.PI * 2);
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.75;
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }
  ctx.restore();

  const lit = earthIllumination(sun, earth).fraction;
  labelBody(
    ctx,
    camera,
    earth,
    COLORS.earth,
    `EARTH · ${Math.round(lit * 100)}% LIT`,
  );
  labelBody(ctx, camera, sun, COLORS.sun, 'SUN');

  drawRuler(ctx, camera);
  drawMinimap(ctx, camera, scene, state);

  // Heads-up text.
  ctx.font = '11px monospace';
  ctx.textAlign = 'left';
  ctx.fillStyle = '#eef3f9';
  ctx.fillText(scene.label, 10, MINIMAP_H + 18);
  ctx.fillStyle = COLORS.muted;
  ctx.fillText(
    `${formatUtc(state.timeMs)} · T+${Math.floor(hours)} h`,
    10,
    MINIMAP_H + 34,
  );
  const narrow = w < 640;
  chip(
    ctx,
    narrow ? 10 : w - 10,
    MINIMAP_H + (narrow ? 52 : 18),
    `SUN ${sunUp ? 'VISIBLE' : 'HIDDEN'}`,
    sunUp ? COLORS.sun : COLORS.danger,
    narrow ? 'left' : 'right',
  );
  chip(
    ctx,
    narrow ? 10 : w - 10,
    MINIMAP_H + (narrow ? 68 : 34),
    `EARTH ${earth.visible ? 'VISIBLE' : 'HIDDEN'}`,
    earth.visible ? COLORS.earth : COLORS.danger,
    narrow ? 'left' : 'right',
  );
  ctx.textAlign = 'left';
  ctx.fillStyle = 'rgba(168, 182, 198, 0.8)';
  ctx.fillText(
    `${scene.terrain ? 'LOLA terrain skyline' : 'Flat 0° horizon'} · to scale, 1° = ${ppd.toFixed(0)} px`,
    10,
    h - RULER_H - 8,
  );
}

function drawSun(
  ctx: CanvasRenderingContext2D,
  camera: Camera,
  sun: BodyState,
  aboveSkyline: boolean,
) {
  const p = project(camera, sun.az, sun.el);
  const r = Math.max(2, sun.radiusDeg * camera.pxPerDeg);
  const glow = r * 16;
  if (p.x < -glow || p.x > camera.width + glow) return;
  // No atmosphere: the glare is the disc's own, gone once it is behind terrain.
  if (aboveSkyline) {
    const halo = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, glow);
    halo.addColorStop(0, 'rgba(255, 246, 220, 0.95)');
    halo.addColorStop(0.07, 'rgba(255, 220, 150, 0.55)');
    halo.addColorStop(0.3, 'rgba(255, 190, 110, 0.12)');
    halo.addColorStop(1, 'rgba(255, 170, 90, 0)');
    ctx.fillStyle = halo;
    ctx.fillRect(p.x - glow, p.y - glow, glow * 2, glow * 2);
  }
  ctx.beginPath();
  ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
  ctx.fillStyle = '#fffbea';
  ctx.fill();
}

function drawEarth(
  ctx: CanvasRenderingContext2D,
  camera: Camera,
  earth: BodyState,
  sun: BodyState,
) {
  const p = project(camera, earth.az, earth.el);
  const r = Math.max(3, earth.radiusDeg * camera.pxPerDeg);
  if (p.x < -r * 3 || p.x > camera.width + r * 3) return;
  const { fraction, bearingDeg } = earthIllumination(sun, earth);

  // Thin atmosphere glow, then the night side.
  const rim = ctx.createRadialGradient(p.x, p.y, r * 0.9, p.x, p.y, r * 1.5);
  rim.addColorStop(0, 'rgba(108, 180, 255, 0.25)');
  rim.addColorStop(1, 'rgba(108, 180, 255, 0)');
  ctx.fillStyle = rim;
  ctx.fillRect(p.x - r * 1.5, p.y - r * 1.5, r * 3, r * 3);
  ctx.beginPath();
  ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
  ctx.fillStyle = '#122238';
  ctx.fill();

  // Lit part: the half facing the Sun plus or minus the terminator ellipse.
  ctx.save();
  ctx.translate(p.x, p.y);
  ctx.rotate(((bearingDeg - 90) * Math.PI) / 180);
  ctx.beginPath();
  ctx.moveTo(0, -r);
  ctx.arc(0, 0, r, -Math.PI / 2, Math.PI / 2);
  for (let i = 0; i <= 32; i++) {
    const t = Math.PI / 2 - (i / 32) * Math.PI;
    ctx.lineTo(r * (1 - 2 * fraction) * Math.cos(t), r * Math.sin(t));
  }
  ctx.closePath();
  const day = ctx.createRadialGradient(r * 0.45, 0, 0, 0, 0, r);
  day.addColorStop(0, '#f2f8ff');
  day.addColorStop(0.35, '#8cc4ff');
  day.addColorStop(1, '#2a64b0');
  ctx.fillStyle = day;
  ctx.fill();
  ctx.restore();
}

function labelBody(
  ctx: CanvasRenderingContext2D,
  camera: Camera,
  body: BodyState,
  color: string,
  text: string,
) {
  const p = project(camera, body.az, body.el);
  const r = Math.max(4, body.radiusDeg * camera.pxPerDeg);
  ctx.font = '10px monospace';
  ctx.fillStyle = color;
  const top = MINIMAP_H + (camera.width < 640 ? 84 : 50);
  const bottom = camera.height - RULER_H - 24;
  if (p.x < 0 || p.x > camera.width) {
    // Off screen: point to it from the nearest edge.
    const right = p.x > camera.width;
    const y = Math.min(bottom, Math.max(top, p.y));
    const off = Math.abs(angleDelta(camera.az, body.az)).toFixed(0);
    ctx.textAlign = right ? 'right' : 'left';
    ctx.fillText(
      right ? `${text} ${off}° →` : `← ${text} ${off}°`,
      right ? camera.width - 10 : 10,
      y,
    );
    return;
  }
  ctx.textAlign = 'center';
  const above = p.y - r - 10 > top;
  ctx.fillText(text, p.x, above ? p.y - r - 8 : p.y + r + 16);
}

function chip(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  text: string,
  color: string,
  align: CanvasTextAlign,
) {
  ctx.font = '10px monospace';
  ctx.textAlign = align;
  ctx.fillStyle = color;
  ctx.fillText(`● ${text}`, x, y);
}

function drawRuler(ctx: CanvasRenderingContext2D, camera: Camera) {
  const { width: w, height: h, pxPerDeg: ppd } = camera;
  const top = h - RULER_H;
  ctx.fillStyle = 'rgba(5, 9, 15, 0.7)';
  ctx.fillRect(0, top, w, RULER_H);
  const left = camera.az - w / 2 / ppd;
  ctx.font = '10px monospace';
  ctx.textAlign = 'center';
  for (let deg = Math.floor(left); deg <= left + w / ppd + 1; deg++) {
    const x = (deg - left) * ppd;
    const az = wrap360(deg);
    const major = az % 5 === 0;
    ctx.fillStyle = major ? COLORS.muted : 'rgba(168, 182, 198, 0.4)';
    ctx.fillRect(x, top, 1, major ? 7 : 4);
    if (az % 10 === 0 && x > 16 && x < w - 16) {
      const cardinal = { 0: 'N', 90: 'E', 180: 'S', 270: 'W' }[az];
      ctx.fillStyle = cardinal ? '#eef3f9' : COLORS.muted;
      ctx.fillText(cardinal ?? `${az}°`, x, top + 19);
    }
  }
}

function drawMinimap(
  ctx: CanvasRenderingContext2D,
  camera: Camera,
  scene: Scene,
  state: SkyState,
) {
  const { width: w, pxPerDeg: ppd } = camera;
  const x = (az: number) => 8 + (wrap360(az) / 360) * (w - 16);
  const mid = MINIMAP_H / 2 + 4;
  ctx.fillStyle = 'rgba(5, 9, 15, 0.88)';
  ctx.fillRect(0, 0, w, MINIMAP_H);
  ctx.strokeStyle = 'rgba(42, 55, 68, 1)';
  ctx.beginPath();
  ctx.moveTo(0, MINIMAP_H - 0.5);
  ctx.lineTo(w, MINIMAP_H - 0.5);
  ctx.stroke();

  // Field of view, split where it crosses north.
  const half = camera.width / 2 / ppd;
  const from = wrap360(camera.az - half);
  const span = half * 2;
  ctx.fillStyle = 'rgba(208, 242, 140, 0.12)';
  ctx.strokeStyle = 'rgba(208, 242, 140, 0.6)';
  const parts =
    from + span <= 360
      ? [[from, span]]
      : [
          [from, 360 - from],
          [0, from + span - 360],
        ];
  for (const [start, length] of parts) {
    const left = x(start);
    const width = (length / 360) * (w - 16);
    ctx.fillRect(left, 3, width, MINIMAP_H - 6);
    ctx.strokeRect(left + 0.5, 3.5, width - 1, MINIMAP_H - 7);
  }

  // Skyline, exaggerated vertically.
  ctx.beginPath();
  for (let az = 0; az <= 360; az += 2) {
    const px = 8 + (az / 360) * (w - 16);
    const y = mid - horizonElAt(scene.horizon, az) * 2;
    if (az) ctx.lineTo(px, y);
    else ctx.moveTo(px, y);
  }
  ctx.strokeStyle = 'rgba(201, 169, 121, 0.7)';
  ctx.lineWidth = 1;
  ctx.stroke();

  ctx.font = '9px monospace';
  ctx.textAlign = 'center';
  ctx.fillStyle = COLORS.muted;
  for (const [az, label] of [
    [0, 'N'],
    [90, 'E'],
    [180, 'S'],
    [270, 'W'],
  ] as const) {
    ctx.fillText(label, x(az) + (az === 0 ? 4 : 0), 11);
  }
  for (const [body, color] of [
    [state.sun, COLORS.sun],
    [state.earth, COLORS.earth],
  ] as const) {
    ctx.beginPath();
    ctx.arc(x(body.az), mid - body.el * 2, 3.5, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.globalAlpha = body.visible ? 1 : 0.4;
    ctx.fill();
    ctx.globalAlpha = 1;
  }
}
