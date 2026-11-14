'use client';

import { useRef, useState } from 'react';
import type { ReferenceSite } from '@/domain/reference';
import { polarPosition } from '../lib/projections';

export function PolarSiteMap({
  sites,
  selectedId,
  onSelect,
}: {
  sites: ReferenceSite[];
  selectedId: string;
  onSelect: (site: ReferenceSite) => void;
}) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(
    null,
  );
  return (
    <div className="polar-map">
      <div className="map-tools">
        <span className="micro-label">SOUTH POLAR REFERENCE GRID</span>
        <div>
          <button
            className="quiet-button"
            type="button"
            aria-label="Zoom out map"
            disabled={zoom <= 1}
            onClick={() => setZoom(Math.max(1, zoom - 0.5))}
          >
            −
          </button>
          <button
            className="quiet-button"
            type="button"
            aria-label="Zoom in map"
            disabled={zoom >= 4}
            onClick={() => setZoom(Math.min(4, zoom + 0.5))}
          >
            +
          </button>
          <button
            className="quiet-button"
            type="button"
            onClick={() => {
              setZoom(1);
              setPan({ x: 0, y: 0 });
            }}
          >
            Reset map
          </button>
        </div>
      </div>
      <svg
        viewBox={`${240 - 240 / zoom + pan.x} ${240 - 240 / zoom + pan.y} ${480 / zoom} ${480 / zoom}`}
        role="group"
        aria-label="Selectable south-pole reference map; drag to pan"
        onPointerDown={(event) => {
          if ((event.target as Element).closest('[data-site]')) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          drag.current = {
            x: event.clientX,
            y: event.clientY,
            px: pan.x,
            py: pan.y,
          };
        }}
        onPointerMove={(event) => {
          if (
            !drag.current ||
            !event.currentTarget.hasPointerCapture(event.pointerId)
          )
            return;
          const scale =
            480 / zoom / event.currentTarget.getBoundingClientRect().width;
          setPan({
            x: drag.current.px - (event.clientX - drag.current.x) * scale,
            y: drag.current.py - (event.clientY - drag.current.y) * scale,
          });
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
      >
        <circle cx="240" cy="240" r="205" className="map-disc" />
        {[1, 2, 3, 4, 5].map((degrees) => (
          <g key={degrees}>
            <circle cx="240" cy="240" r={degrees * 34} className="grid" />
            <text x="247" y={240 - degrees * 34 + 12}>
              {90 - degrees}°S
            </text>
          </g>
        ))}
        {[0, 45, 90, 135, 180, 225, 270, 315].map((angle) => {
          const p = polarPosition(-84.5, angle);
          return (
            <line
              key={angle}
              x1="240"
              y1="240"
              x2={p.x}
              y2={p.y}
              className="grid"
            />
          );
        })}
        <text x="240" y="35" textAnchor="middle">
          0°
        </text>
        <text x="445" y="244" textAnchor="middle">
          90°E
        </text>
        <text x="240" y="451" textAnchor="middle">
          180°
        </text>
        <text x="30" y="244" textAnchor="middle">
          90°W
        </text>
        <circle cx="240" cy="240" r="3" className="pole-dot" />
        <text x="240" y="263" textAnchor="middle">
          SOUTH POLE
        </text>
        {sites.map((site, index) => {
          const p = polarPosition(site.lat, site.lon);
          return (
            <a
              key={site.id}
              data-site="true"
              href="#explore"
              aria-label={`Select ${site.name}`}
              aria-current={site.id === selectedId ? 'true' : undefined}
              onClick={(event) => {
                event.preventDefault();
                onSelect(site);
              }}
            >
              <title>
                {site.name} · {site.lat.toFixed(4)}°, {site.lon.toFixed(4)}° ·{' '}
                {site.terrainMasks.length
                  ? 'reviewed terrain available'
                  : 'geometric only'}
              </title>
              <circle
                cx={p.x}
                cy={p.y}
                r={site.id === selectedId ? 12 : 9}
                className={
                  site.id === selectedId ? 'map-marker selected' : 'map-marker'
                }
              />
              <text
                x={p.x}
                y={p.y + 3.5}
                textAnchor="middle"
                className="map-index"
              >
                {String(index + 1).padStart(2, '0')}
              </text>
            </a>
          );
        })}
        <path d="M45 412v6h56v-6" className="scale-bar" />
        <text x="73" y="436" textAnchor="middle">
          50 km
        </text>
      </svg>
      <div className="map-site-key">
        {sites.map((site, index) => (
          <button
            type="button"
            key={site.id}
            aria-pressed={site.id === selectedId}
            onClick={() => onSelect(site)}
          >
            <span>{String(index + 1).padStart(2, '0')}</span>
            {site.name}
          </button>
        ))}
      </div>
      <p className="hint">
        Coordinate diagram, not terrain imagery. South-pole equidistant
        projection; 0° longitude up, east-positive clockwise. Drag to pan; use
        zoom controls. DEM grid cells, not recommended landing targets.
      </p>
    </div>
  );
}
