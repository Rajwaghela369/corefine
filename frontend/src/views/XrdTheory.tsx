import { useMutation, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";
import { api, xrd, type XrdCompare } from "../api/client";
import type { Overlay } from "../components/XrdChart";
import { Button, Tag, cn, num } from "../components/ui";

const small = "h-7 rounded-md border border-line-strong bg-surface px-2 text-xs outline-none focus:border-accent";

/** Theory vs experiment for one measured scan: compare a model, or identify the phase among MP polymorphs. */
export function XrdTheory({ datasetId, file, wavelength, onOverlay, onProfile }: { datasetId: string; file?: string; wavelength: number;
  onOverlay: (o: Overlay) => void; onProfile: (c: XrdCompare | null) => void }) {
  const all = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const structures = (all.data ?? []).filter((d) => d.valid && d.role === "reference_structure");
  const [model, setModel] = useState("");
  const [b0, setB0] = useState("");
  const cmp = useMutation({
    mutationFn: () => xrd.compare({ dataset: datasetId, file, structure: model, bulk_modulus_GPa: b0 ? Number(b0) : undefined }),
    onSuccess: (r) => onProfile(r),
  });
  const ident = useMutation({ mutationFn: () => xrd.identify({ dataset: datasetId, file }) });
  const r = cmp.data;
  return (
    <div className="space-y-3 border-t border-line px-3 py-3 text-xs">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-semibold">Theory vs experiment</span>
        <select className={cn(small, "max-w-64")} value={model} onChange={(e) => setModel(e.target.value)}>
          <option value="">model structure…</option>
          {structures.map((d) => <option key={d.id} value={`dataset:${d.id}`}>{d.id}</option>)}
        </select>
        <input className={cn(small, "w-28 font-mono")} placeholder="or mp-149" onChange={(e) => e.target.value.trim() && setModel(`mp:${e.target.value.trim().replace(/^mp:/, "")}`)} />
        <input className={cn(small, "w-24 font-mono")} placeholder="B₀ (GPa)" value={b0} onChange={(e) => setB0(e.target.value)}
          title="Bulk modulus for the equivalent pressure; taken from the structure if it came from a DFT equation of state" />
        <Button size="sm" variant="primary" disabled={!model || cmp.isPending} onClick={() => cmp.mutate()}>{cmp.isPending ? "Fitting…" : "Compare"}</Button>
        <span className="mx-1 text-faint">|</span>
        <Button size="sm" variant="secondary" disabled={ident.isPending} onClick={() => ident.mutate()}>
          <Search size={12} /> {ident.isPending ? "Scoring polymorphs…" : "Identify phase"}</Button>
      </div>
      {cmp.isError && <p className="text-bad">{String(cmp.error instanceof Error ? cmp.error.message : cmp.error)}</p>}
      {r && (
        <div className="space-y-2 rounded-md border border-line p-2.5">
          <div className="grid grid-cols-4 gap-2">
            <Stat label="Peaks matched" value={`${r.n_matched} / ${r.n_measured}`} sub={`within ${r.tol_deg}° after the fit`} />
            <Stat label="Lattice: experiment / model" value={r.lattice_scale.toFixed(6)}
              sub={`${r.linear_strain_percent >= 0 ? "+" : ""}${r.linear_strain_percent.toFixed(3)} % linear`} />
            <Stat label="Implied lattice (Å)" value={r.implied_lattice_A.slice(0, 3).map((v) => v.toFixed(5)).filter((v, i, a) => a.indexOf(v) === i).join(" / ")}
              sub={`model ${r.model_lattice_A.map((v) => v.toFixed(4)).filter((v, i, a) => a.indexOf(v) === i).join(" / ")}`} />
            <Stat label="Equivalent pressure" value={r.pressure_equivalent_GPa != null ? `${r.pressure_equivalent_GPa.toFixed(2)} GPa` : "—"}
              sub={r.bulk_modulus_source ? `B₀ from ${r.bulk_modulus_source}` : "give B₀ to compute"} />
          </div>
          <p className="text-[11px] text-muted">Zero shift {r.zero_shift_deg.toFixed(4)}°, residual RMS {r.rms_residual_deg != null ? (r.rms_residual_deg * 1000).toFixed(1) : "—"} mdeg.
            {r.pressure_note ? ` Pressure: ${r.pressure_note}.` : ""} Dashed curve: fitted model with the measured peak width.</p>
          <div className="max-h-56 overflow-auto rounded border border-line">
            <table className="tabular w-full text-[11px]">
              <thead className="sticky top-0 bg-subtle text-left text-muted"><tr><th className="px-2 py-1">hkl</th><th>2θ obs</th><th>2θ model</th>
                <th>obs − model</th><th>after fit</th><th>I obs</th><th>I model</th></tr></thead>
              <tbody className="divide-y divide-line font-mono">{r.matched.map((m) => (
                <tr key={m.hkl + m.two_theta_obs}><td className="px-2 py-0.5 font-sans">({m.hkl.replaceAll(" ", "")})</td>
                  <td>{m.two_theta_obs.toFixed(4)}</td><td>{m.two_theta_model.toFixed(4)}</td>
                  <td className={Math.abs(m.delta_model_deg) > 0.1 ? "text-warn" : ""}>{m.delta_model_deg >= 0 ? "+" : ""}{m.delta_model_deg.toFixed(4)}</td>
                  <td>{(m.residual_deg * 1000).toFixed(1)} m°</td><td>{m.rel_intensity_obs.toFixed(0)}</td><td>{m.rel_intensity_model.toFixed(0)}</td></tr>))}
              </tbody>
            </table>
          </div>
          {r.unmatched_measured.length > 0 && <p className="text-warn">Measured peaks not explained by the model: {r.unmatched_measured.map((t) => t.toFixed(2)).join(", ")}°</p>}
        </div>
      )}
      {ident.isError && <p className="text-bad">{String(ident.error instanceof Error ? ident.error.message : ident.error)}</p>}
      {ident.data && (
        <div className="rounded-md border border-line">
          <div className="border-b border-line px-2.5 py-1.5 text-[11px] text-muted">
            {ident.data.formula}: Materials Project polymorphs scored against {ident.data.n_peaks} measured peaks (explained strong peaks,
            minus strong model lines absent from the scan, minus lattice mismatch)</div>
          <ul className="divide-y divide-line">{ident.data.ranked.map((c, i) => (
            <li key={c.candidate} className="flex items-center gap-2 px-2.5 py-1.5">
              <span className="w-4 text-faint">{i + 1}</span>
              <span className="w-24 font-mono">{c.candidate}</span>
              <span className="w-32 truncate">{c.material.spacegroup}</span>
              <Tag tone={c.explained_fraction >= 0.9 && !c.strong_model_lines_missing.length ? "ok" : c.explained_fraction >= 0.6 ? "warn" : "neutral"}>
                {c.n_matched}/{c.n_strong} peaks</Tag>
              <span className="text-muted">scale {c.lattice_scale.toFixed(4)}</span>
              {c.strong_model_lines_missing.length > 0 && <span className="text-warn">{c.strong_model_lines_missing.length} strong lines missing</span>}
              <span className="text-muted">{c.material.stable ? "stable" : `+${num(c.material.e_above_hull_eV, 3)} eV/at`}</span>
              <Button size="sm" variant="ghost" className="ml-auto" onClick={() => xrd.simulate({ structure: `mp:${c.candidate}`, wavelength_A: wavelength })
                .then((s) => onOverlay({ label: c.candidate, color: "#7c3aed", peaks: s.peaks }))}>overlay</Button>
            </li>))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded border border-line bg-subtle/50 px-2 py-1.5">
      <div className="text-[10.5px] text-muted">{label}</div>
      <div className="tabular font-mono text-[13px] font-medium">{value}</div>
      {sub && <div className="text-[10.5px] text-muted">{sub}</div>}
    </div>
  );
}
