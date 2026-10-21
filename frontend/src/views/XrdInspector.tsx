import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, xrd, type XrdSimulated } from "../api/client";
import { type Overlay, XrdChart } from "../components/XrdChart";
import { Button, cn, inputCls } from "../components/ui";

const COLORS = ["#c2410c", "#15803d", "#7c3aed", "#b45309", "#0e7490"];
export const CU_KA1 = 1.5405929;

/** Measured scan (if the dataset is a pattern) with simulated reflections of any structures overlaid. */
export function XrdInspector({ datasetId, measured }: { datasetId: string; measured: boolean }) {
  const [file, setFile] = useState<string | undefined>();
  const [log, setLog] = useState(true);
  const m = useQuery({ queryKey: ["xrd-measured", datasetId, file], queryFn: () => xrd.measured(datasetId, file), enabled: measured });
  const all = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const structures = (all.data ?? []).filter((d) => d.valid && d.role === "reference_structure");
  const [sims, setSims] = useState<(XrdSimulated & { color: string })[]>([]);
  const [pick, setPick] = useState("");
  const [mp, setMp] = useState("");
  const [scale, setScale] = useState("1.0");
  const [wl, setWl] = useState(String(CU_KA1));
  const wavelength = measured ? m.data?.wavelength_A ?? null : Number(wl);
  const add = useMutation({
    mutationFn: (structure: string) => xrd.simulate({ structure, wavelength_A: wavelength!, two_theta_min: m.data?.range[0] ?? 10,
      two_theta_max: m.data?.range[1] ?? 150, volume_scale: Number(scale) || 1 }),
    onSuccess: (r) => setSims((s) => [...s, { ...r, label: `${r.label}${Number(scale) !== 1 ? ` ×V${scale}` : ""}`, color: COLORS[s.length % COLORS.length] }]),
  });
  const ownSim = useQuery({ queryKey: ["xrd-own", datasetId, wl], enabled: !measured && Number(wl) > 0,
    queryFn: () => xrd.simulate({ structure: `dataset:${datasetId}`, wavelength_A: Number(wl) }) });
  const overlays: Overlay[] = useMemo(() => [
    ...(!measured && ownSim.data ? [{ label: datasetId, color: COLORS[0], peaks: ownSim.data.peaks }] : []),
    ...sims.map((s) => ({ label: s.label, color: s.color, peaks: s.peaks })),
  ], [sims, ownSim.data, measured, datasetId]);

  return (
    <div className="rounded-lg border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <span className="text-xs font-semibold">Powder XRD</span>
        {measured && m.data && <>
          <select className="h-7 rounded border border-line-strong px-1.5 text-xs" value={m.data.file} onChange={(e) => setFile(e.target.value)}>
            {m.data.files.map((f) => <option key={f}>{f}</option>)}</select>
          <span className="text-[11px] text-muted">{m.data.n_points} points · λ = {m.data.wavelength_A ?? "not set"} Å
            {m.data.wavelength_source ? ` (${m.data.wavelength_source})` : ""}</span>
        </>}
        {!measured && <label className="flex items-center gap-1 text-[11px] text-muted">λ (Å)
          <input className="h-7 w-24 rounded border border-line-strong px-1.5 font-mono text-xs" value={wl} onChange={(e) => setWl(e.target.value)} /></label>}
        <label className="ml-auto flex items-center gap-1 text-[11px] text-muted">
          <input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} disabled={!measured} /> log intensity</label>
      </div>
      <div className="px-2 pt-2">
        {measured && m.isLoading && <p className="p-6 text-xs text-muted">Loading scan…</p>}
        {measured && m.isError && <p className="p-3 text-xs text-bad">{String(m.error)}</p>}
        {(!measured || m.data) && <XrdChart x={m.data?.x ?? []} y={m.data?.y ?? []} overlays={overlays} log={measured && log} />}
        <p className="px-1 pb-1 text-[10.5px] text-faint">Drag to zoom, double-click to reset. Sticks: kinematic intensities, no instrument profile.</p>
      </div>
      <div className="space-y-2 border-t border-line px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="font-medium text-ink-2">Overlay reflections of</span>
          <select className={cn(inputCls, "h-7 w-auto")} value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">a structure in Storage…</option>
            {structures.map((d) => <option key={d.id} value={d.id}>{d.id}</option>)}
          </select>
          <Button size="sm" variant="secondary" disabled={!pick || !wavelength || add.isPending} onClick={() => add.mutate(`dataset:${pick}`)}>Add</Button>
          <span className="text-faint">or</span>
          <input className={cn(inputCls, "h-7 w-24 font-mono")} placeholder="mp-149" value={mp} onChange={(e) => setMp(e.target.value)} />
          <Button size="sm" variant="secondary" disabled={!mp.trim() || !wavelength || add.isPending} onClick={() => add.mutate(`mp:${mp.trim().replace(/^mp:/, "")}`)}>Add</Button>
          <label className="ml-1 flex items-center gap-1 text-[11px] text-muted" title="Isotropic volume scale, e.g. a DFT V0 relative to the structure">
            volume ×<input className="h-7 w-14 rounded border border-line-strong px-1 font-mono text-xs" value={scale} onChange={(e) => setScale(e.target.value)} /></label>
        </div>
        {!wavelength && measured && <p className="text-[11px] text-warn">This dataset has no wavelength in its manifest; set one to compare with simulations.</p>}
        {add.isError && <p className="text-[11px] text-bad">{String(add.error instanceof Error ? add.error.message : add.error)}</p>}
        <div className="flex flex-wrap gap-2">
          {overlays.map((o, i) => (
            <span key={i} className="inline-flex items-center gap-1.5 rounded border border-line px-1.5 py-0.5 text-[11px]">
              <span className="size-2 rounded-sm" style={{ background: o.color }} />{o.label}
              <span className="text-muted">{o.peaks.length} reflections</span>
              {i >= (measured ? 0 : 1) && <button className="text-faint hover:text-ink" onClick={() => setSims((s) => s.filter((_, j) => j !== i - (measured ? 0 : 1)))}>×</button>}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
