import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, type GroupRun } from "../api/client";
import { Status, Tag, cn } from "../components/ui";
import { XrdChart, type Curve, type Overlay } from "../components/XrdChart";

const COLOR: Record<string, string> = { agents: "#121826", gsas2: "#c2410c", maud: "#15803d" };
const val = (r: GroupRun, k: string) => r.metrics[k]?.value ?? null;
const unc = (r: GroupRun, k: string) => r.metrics[k]?.uncertainty ?? null;
const f = (v: number | null | undefined, d = 6) => (v == null ? "—" : v.toFixed(d));

/** The same scan refined by several engines: the measured pattern with GSAS-II's calculated curve, every engine's
 *  reflection positions from its own refined cell, and the refined values side by side with the certificate. */
export function EngineCompare({ groupId }: { groupId: string }) {
  const g = useQuery({ queryKey: ["group", groupId], queryFn: () => api.group(groupId),
    refetchInterval: (q) => (q.state.data?.runs.some((r) => !["done", "failed"].includes(r.status)) ? 3000 : false) });
  const [log, setLog] = useState(true);
  const d = g.data;
  const curves: Curve[] = useMemo(() => (d?.runs ?? []).filter((r) => r.curve)
    .map((r) => ({ label: `${r.label} calculated`, color: COLOR[r.engine], x: r.curve!.x, y: r.curve!.calculated })), [d]);
  const overlays: Overlay[] = useMemo(() => (d?.runs ?? []).filter((r) => r.reflections?.length)
    .map((r) => ({ label: r.label, color: COLOR[r.engine],
      peaks: r.reflections!.map((p) => ({ ...p, d_A: 0, multiplicity: 0 })) })), [d]);
  if (!d) return <p className="p-4 text-xs text-muted">{g.isError ? String(g.error) : "Loading the comparison…"}</p>;
  const cert = d.certified ?? {};
  const hex = d.runs.some((r) => val(r, "c_refined") != null);
  return (
    <div className="h-full overflow-auto">
      <div className="flex items-center gap-3 border-b border-line px-4 py-2 text-[11.5px]">
        <span className="font-medium text-ink-2">{d.dataset}</span>
        <span className="font-mono text-muted">{d.measured?.file} · λ = {d.measured?.wavelength_A} Å</span>
        <div className="ml-auto flex items-center gap-3">
          {d.runs.map((r) => <span key={r.id} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: COLOR[r.engine] }} />{r.label}</span>)}
          <label className="inline-flex items-center gap-1 text-muted"><input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} /> log</label>
        </div>
      </div>
      {d.measured && <div className="px-2 pt-2"><XrdChart x={d.measured.x} y={d.measured.y} log={log} overlays={overlays} curves={curves} height={340} /></div>}
      <p className="px-4 pb-3 text-[11px] text-muted">
        Blue: measured. Dashed: GSAS-II's calculated pattern. Ticks: reflection positions from each engine's refined cell
        (computed by CoRefine from that cell). MAUD's batch mode does not export its calculated pattern, so it is shown by
        its positions only. Drag to zoom into a peak; double-click to reset.</p>
      <div className="px-4 pb-4">
        <table className="w-full text-[12px]">
          <thead><tr className="border-b border-line text-left text-[11px] text-muted">
            <th className="py-1.5 font-medium">Engine</th><th className="font-medium">a (Å)</th>
            {hex && <th className="font-medium">c (Å)</th>}
            <th className="font-medium">a − certified</th>{hex && <th className="font-medium">c − certified</th>}
            <th className="font-medium">Rwp</th><th className="font-medium">size</th><th className="font-medium">microstrain</th><th />
          </tr></thead>
          <tbody className="font-mono">
            {cert.a_A != null && <tr className="border-b border-line text-muted">
              <td className="py-1.5 font-sans">Certified</td><td>{f(cert.a_A)} ± {cert.a_uncertainty_A}</td>
              {hex && <td>{f(cert.c_A ?? null)}{cert.c_uncertainty_A ? ` ± ${cert.c_uncertainty_A}` : ""}</td>}
              <td colSpan={hex ? 6 : 4} className="font-sans text-[11px]">{cert.source}</td></tr>}
            {d.runs.map((r) => (
              <tr key={r.id} className="border-b border-line align-top">
                <td className="py-1.5 font-sans"><span className="font-medium" style={{ color: COLOR[r.engine] }}>{r.label}</span>
                  <div className="text-[10.5px] text-muted">{r.id}</div></td>
                <td>{f(val(r, "a_refined"))}{unc(r, "a_refined") ? <div className="text-[10.5px] text-muted">± {f(unc(r, "a_refined"))}</div> : null}</td>
                {hex && <td>{f(val(r, "c_refined"))}</td>}
                <td className={cn(Math.abs(val(r, "difference_from_certified") ?? 0) > 0.0005 && "text-bad")}>{f(val(r, "difference_from_certified"))}</td>
                {hex && <td>{f(val(r, "c_difference_from_certified"))}</td>}
                <td>{val(r, "Rwp") != null ? `${f(val(r, "Rwp"), 1)} %` : "—"}</td>
                <td>{val(r, "crystallite_size") != null ? `${f(val(r, "crystallite_size"), 2)} µm` : "—"}</td>
                <td>{val(r, "microstrain") != null ? f(val(r, "microstrain"), 5) : "—"}</td>
                <td className="font-sans"><Status status={r.status as never} />
                  {r.error && <div className="max-w-56 text-[10.5px] text-bad">{r.error.split("\n")[0]}</div>}</td>
              </tr>))}
          </tbody>
        </table>
        <div className="mt-3 flex flex-wrap gap-1.5 text-[11px]">
          <Tag tone="neutral">Rwp: lower is a closer fit of the whole pattern</Tag>
          <Tag tone="neutral">difference in red: outside the ±0.0005 Å target</Tag>
        </div>
      </div>
    </div>
  );
}
