import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import type { XrdPeak } from "../api/client";

export interface Overlay { label: string; color: string; peaks: XrdPeak[] }

/** Measured scan as a line; simulated reflections as sticks (height = relative intensity) with hkl labels.
 *  Drag to zoom, double-click to reset. */
export function XrdChart({ x, y, overlays, log, height = 320 }: { x: number[]; y: number[]; overlays: Overlay[]; log: boolean; height?: number }) {
  const el = useRef<HTMLDivElement>(null);
  const overlaysRef = useRef(overlays);
  overlaysRef.current = overlays;
  useEffect(() => {
    if (!el.current) return;
    const hasData = x.length > 0;
    const xs = hasData ? x : overlays.flatMap((o) => o.peaks.map((p) => p.two_theta)).sort((a, b) => a - b);
    const ys = hasData ? y.map((v) => (log ? Math.max(v, 1e-3) : v)) : xs.map(() => null);
    const plot = new uPlot({
      width: el.current.clientWidth, height,
      scales: { x: { time: false }, y: { distr: log ? 3 : 1, range: hasData ? undefined : [0, 1] } },
      axes: [{ label: "2θ (°)", stroke: "#6b7484", grid: { stroke: "#eef0f3" } },
        { label: hasData ? "intensity" : "", stroke: "#6b7484", grid: { stroke: "#eef0f3" }, size: 60 }],
      legend: { show: false },
      cursor: { drag: { x: true, y: false } },
      series: [{}, { stroke: "#1f4fd1", width: 1, points: { show: false } }],
      hooks: {
        draw: [(u) => {
          const ctx = u.ctx;
          const { top, height: h } = u.bbox;
          overlaysRef.current.forEach((o, k) => {
            ctx.save();
            ctx.strokeStyle = o.color; ctx.fillStyle = o.color; ctx.lineWidth = 1.5 * devicePixelRatio;
            ctx.font = `${10 * devicePixelRatio}px "JetBrains Mono Variable", monospace`;
            for (const pk of o.peaks) {
              const px = u.valToPos(pk.two_theta, "x", true);
              if (px < u.bbox.left || px > u.bbox.left + u.bbox.width) continue;
              const len = (h * 0.32) * (pk.intensity / 100);
              const base = top + h - k * 4 * devicePixelRatio;
              ctx.beginPath(); ctx.moveTo(px, base); ctx.lineTo(px, base - len); ctx.stroke();
              if (pk.intensity >= 8) ctx.fillText(pk.hkl.replaceAll(" ", ""), px + 2 * devicePixelRatio, base - len - 2 * devicePixelRatio);
            }
            ctx.restore();
          });
        }],
      },
    }, [xs, ys as (number | null)[]], el.current);
    const ro = new ResizeObserver(() => el.current && plot.setSize({ width: el.current.clientWidth, height }));
    ro.observe(el.current);
    return () => { ro.disconnect(); plot.destroy(); };
  }, [x, y, log, height, overlays]);
  return <div ref={el} className="w-full" />;
}
