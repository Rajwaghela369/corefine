import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, FileText, Plus, RefreshCw, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { api, type DatasetNode, type ScanPreview } from "../api/client";
import { Button, Dialog, Empty, Field, PanelHeader, cn, inputCls, num } from "../components/ui";
import { XrdInspector } from "./XrdInspector";
import { xrd } from "../api/client";

const GROUPS = [
  { role: "measured_pattern", title: "Measured patterns" },
  { role: "reference_structure", title: "Reference structures" },
  { role: "reference_value", title: "Reference values" },
];
const ROLE_LABEL: Record<string, string> = {
  measured_pattern: "Measured pattern", reference_structure: "Reference structure", reference_value: "Reference value",
};

/** Storage: everything in the bucket, grouped by role; upload, inspect and edit manifests. */
export function StorageView() {
  const qc = useQueryClient();
  const tree = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const rescan = useMutation({ mutationFn: api.rescan, onSuccess: () => qc.invalidateQueries({ queryKey: ["datasets"] }) });
  const [openId, setOpenId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [scanning, setScanning] = useState(false);
  const data = tree.data ?? [];
  const current = data.find((d) => d.id === openId) ?? data.find((d) => d.role === "measured_pattern") ?? data.find((d) => d.valid) ?? null;
  const invalid = data.filter((d) => !d.valid);

  return (
    <div className="grid h-full min-h-0 grid-cols-[320px_1fr]">
      <aside className="flex min-h-0 flex-col border-r border-line bg-surface">
        <PanelHeader title="Datasets" meta={data.length ? String(data.length) : undefined} actions={<>
          <Button variant="ghost" size="sm" title="Re-index manifests" onClick={() => rescan.mutate()}>
            <RefreshCw size={13} className={cn(rescan.isPending && "animate-spin")} /></Button>
          <Button variant="secondary" size="sm" onClick={() => setScanning(true)} title="Import your own powder scan (.xy, .xye, .csv, .dat)">
            <Upload size={13} /> Scan</Button>
          <Button variant="secondary" size="sm" onClick={() => setImporting(true)} title="Import a structure from Materials Project">MP</Button>
          <Button variant="primary" size="sm" onClick={() => setAdding(true)}><Plus size={13} /> Add dataset</Button>
        </>} />
        <div className="min-h-0 flex-1 overflow-auto pb-4">
          {tree.isError && <p className="m-3 rounded-md bg-bad-soft p-2.5 text-xs text-bad">{String(tree.error)}</p>}
          {!tree.isLoading && !data.length && <Empty title="Storage is empty">Add a dataset, or run <code>scripts/setup.py</code> to load the NIST seed data.</Empty>}
          {GROUPS.map(({ role, title }) => {
            const rows = data.filter((d) => d.valid && d.role === role);
            if (!rows.length) return null;
            return (
              <section key={role} className="mt-3">
                <h3 className="px-4 pb-1 text-[11px] font-medium uppercase tracking-wider text-faint">{title}</h3>
                {rows.map((d) => <ListRow key={d.id} d={d} active={current?.id === d.id} onClick={() => setOpenId(d.id)} />)}
              </section>
            );
          })}
          {invalid.length > 0 && (
            <section className="mt-3">
              <h3 className="px-4 pb-1 text-[11px] font-medium uppercase tracking-wider text-faint">Needs a manifest</h3>
              {invalid.map((d) => <ListRow key={d.id} d={d} active={current?.id === d.id} onClick={() => setOpenId(d.id)} />)}
            </section>
          )}
        </div>
      </aside>
      <section className="min-h-0 overflow-auto">
        {current ? <DatasetDetail key={current.id} d={current} /> : <Empty title="No dataset selected" />}
      </section>
      <Dialog title="Import from Materials Project" open={importing} onClose={() => setImporting(false)}>
        <ImportMp onDone={(id) => { setImporting(false); setOpenId(id); qc.invalidateQueries({ queryKey: ["datasets"] }); }} />
      </Dialog>
      <Dialog title="Import your own scan" open={scanning} onClose={() => setScanning(false)}>
        <ImportScan onDone={(id) => { setScanning(false); setOpenId(id); qc.invalidateQueries({ queryKey: ["datasets"] }); }} />
      </Dialog>
      <Dialog title="Add dataset" open={adding} onClose={() => setAdding(false)}>
        <AddDataset onDone={(id) => { setAdding(false); setOpenId(id); qc.invalidateQueries({ queryKey: ["datasets"] }); }} />
      </Dialog>
    </div>
  );
}

function ListRow({ d, active, onClick }: { d: DatasetNode; active: boolean; onClick: () => void }) {
  const files = d.files.filter((f) => f.startsWith("raw/"));
  return (
    <button onClick={onClick} className={cn("mx-2 flex w-[calc(100%-1rem)] items-center gap-2.5 rounded-md px-2.5 py-2 text-left",
      active ? "bg-accent-soft" : "hover:bg-subtle")}>
      {d.valid ? <FileText size={14} className={active ? "text-accent" : "text-faint"} /> : <AlertTriangle size={14} className="text-warn" />}
      <div className="min-w-0">
        <div className="truncate font-mono text-[12px] font-medium">{d.id}</div>
        <div className="text-[11px] text-muted">{d.valid ? `${files.length} file${files.length === 1 ? "" : "s"}` : "not usable in runs"}</div>
      </div>
    </button>
  );
}

function DatasetDetail({ d }: { d: DatasetNode }) {
  const qc = useQueryClient();
  const m = useQuery({ queryKey: ["manifest", d.id], queryFn: () => api.manifest(d.id), enabled: d.valid });
  const [text, setText] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const save = useMutation({
    mutationFn: () => api.saveManifest(d.id, JSON.parse(text ?? "{}")),
    onSuccess: () => { setText(null); qc.invalidateQueries({ queryKey: ["manifest", d.id] }); },
  });
  const upload = useMutation({
    mutationFn: (files: File[]) => api.upload(d.id, files),
    onSuccess: () => { setUploadError(null); qc.invalidateQueries({ queryKey: ["datasets"] }); },
    onError: (e) => setUploadError(String(e instanceof Error ? e.message : e)),
  });
  const man = (m.data ?? {}) as Record<string, any>;
  const inst = (man.instrument ?? {}) as Record<string, any>;
  const files = d.files.filter((f) => f !== "dataset.yaml");
  const info: [string, unknown][] = [
    ["Role", ROLE_LABEL[d.role ?? ""] ?? "—"], ["Technique", man.technique], ["Material", man.material], ["Format", man.format],
    ["Radiation", inst.radiation], ["Wavelength", inst.wavelength_A != null ? `${num(inst.wavelength_A, 10)} Å` : undefined],
    ["Wavelength source", inst.wavelength_source], ["Source", man.source],
  ];

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-6">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-wider text-faint">Dataset</div>
          <h1 className="mt-0.5 font-mono text-lg font-semibold">{d.id}</h1>
        </div>
        {d.valid && <Button variant="secondary" onClick={() => input.current?.click()} disabled={upload.isPending}>
          <Upload size={14} /> {upload.isPending ? "Uploading…" : "Upload files"}</Button>}
        <input ref={input} type="file" multiple hidden onChange={(e) => { const f = Array.from(e.target.files ?? []); if (f.length) upload.mutate(f); e.target.value = ""; }} />
      </div>

      {!d.valid && <div className="rounded-md border border-warn/25 bg-warn-soft p-3 text-xs text-warn"><b>Not usable in runs.</b> {d.problem}</div>}
      {uploadError && <div className="rounded-md border border-bad/20 bg-bad-soft p-3 text-xs text-bad"><b>Upload rejected.</b> {uploadError}</div>}

      {d.valid && (
        <dl className="grid grid-cols-4 gap-px overflow-hidden rounded-lg border border-line bg-line">
          {info.map(([k, v]) => (
            <div key={k} className="bg-surface px-3 py-2.5">
              <dt className="text-[11px] text-muted">{k}</dt>
              <dd className="mt-0.5 truncate text-[13px]" title={String(v ?? "")}>
                {typeof v === "string" && v.startsWith("http") ? <a className="text-accent hover:underline" href={v} target="_blank" rel="noreferrer">{v}</a> : (v as string) ?? "—"}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {d.valid && (d.role === "measured_pattern" || d.role === "reference_structure") &&
        <XrdInspector key={d.id} datasetId={d.id} measured={d.role === "measured_pattern"} />}
      {man.computed && <div className="rounded-lg border border-line bg-surface p-3 text-xs">
        <div className="mb-1 font-semibold">Computed structure</div>
        <dl className="grid grid-cols-[140px_1fr] gap-y-1 font-mono text-[11px]">
          {Object.entries(man.computed as Record<string, unknown>).map(([k, v]) => <div key={k} className="contents">
            <dt className="font-sans text-muted">{k}</dt><dd>{typeof v === "number" ? num(v) : String(v)}</dd></div>)}
        </dl>
      </div>}

      <div className="grid grid-cols-[1fr_1fr] gap-5">
        <div className="rounded-lg border border-line bg-surface">
          <div className="flex h-10 items-center justify-between border-b border-line px-3">
            <span className="text-xs font-semibold">Files</span><span className="text-[11px] text-muted">{files.length}</span>
          </div>
          <ul className="max-h-96 divide-y divide-line overflow-auto">
            {files.map((f) => <li key={f} className="truncate px-3 py-1.5 font-mono text-[11px] text-ink-2" title={f}>{f}</li>)}
          </ul>
        </div>
        {d.valid && (
          <div className="flex flex-col rounded-lg border border-line bg-surface">
            <div className="flex h-10 items-center justify-between border-b border-line px-3">
              <span className="text-xs font-semibold">Manifest <span className="font-normal text-muted">dataset.yaml</span></span>
              <div className="flex gap-1">
                {text !== null && <Button size="sm" variant="ghost" onClick={() => setText(null)}>Discard</Button>}
                <Button size="sm" variant="secondary" disabled={text === null || save.isPending} onClick={() => save.mutate()}>Save</Button>
              </div>
            </div>
            <textarea className="min-h-80 flex-1 resize-none p-3 font-mono text-[11px] leading-4 outline-none"
              value={text ?? (m.data ? JSON.stringify(m.data, null, 2) : "")} onChange={(e) => setText(e.target.value)} spellCheck={false} />
            {save.isError && <p className="border-t border-line px-3 py-2 text-[11px] text-bad">{String(save.error)}</p>}
          </div>
        )}
      </div>
    </div>
  );
}

function AddDataset({ onDone }: { onDone: (id: string) => void }) {
  const [f, setF] = useState({ id: "", role: "measured_pattern", technique: "xrd_powder", material: "Si",
    format: "pdcif", radiation: "CuKa1", wavelength: "", source: "", readme: "" });
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const measured = f.role === "measured_pattern";

  async function submit() {
    setError(null); setBusy(true);
    try {
      const manifest: Record<string, unknown> = { id: f.id, role: f.role, technique: f.technique, material: f.material,
        format: f.format, files: ["raw/*"], ...(f.source ? { source: f.source } : {}) };
      if (measured) manifest.instrument = { radiation: f.radiation, wavelength_A: f.wavelength ? Number(f.wavelength) : null };
      await api.createDataset(manifest, f.readme || undefined);
      if (files.length) await api.upload(f.id, files);
      onDone(f.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  return (
    <div className="space-y-3">
      <Field label="Dataset ID" hint="Lowercase letters, digits and hyphens. Becomes the folder name.">
        <input className={cn(inputCls, "font-mono")} placeholder="si-scan-2026-10" value={f.id} onChange={set("id")} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Role">
          <select className={inputCls} value={f.role} onChange={set("role")}>
            <option value="measured_pattern">Measured pattern</option>
            <option value="reference_structure">Reference structure</option>
            <option value="reference_value">Reference value</option>
          </select>
        </Field>
        <Field label="Format">
          <select className={inputCls} value={f.format} onChange={set("format")}>
            <option value="pdcif">Powder CIF (pdCIF)</option><option value="cif">Structure CIF</option>
            <option value="xy">XY</option><option value="csv">CSV</option>
          </select>
        </Field>
        <Field label="Technique"><input className={inputCls} value={f.technique} onChange={set("technique")} /></Field>
        <Field label="Material"><input className={inputCls} value={f.material} onChange={set("material")} /></Field>
        {measured && <>
          <Field label="Radiation"><input className={inputCls} value={f.radiation} onChange={set("radiation")} /></Field>
          <Field label="Wavelength (Å)" hint="Leave blank if unknown; runs stop rather than guess.">
            <input className={cn(inputCls, "font-mono")} placeholder="1.5405929" value={f.wavelength} onChange={set("wavelength")} />
          </Field>
        </>}
      </div>
      <Field label="Source"><input className={inputCls} placeholder="DOI or URL" value={f.source} onChange={set("source")} /></Field>
      <Field label="Notes"><textarea className={cn(inputCls, "h-16 py-1.5")} placeholder="Provenance, licence, anything an analyst should know"
        value={f.readme} onChange={set("readme")} /></Field>
      <Field label="Files">
        <input type="file" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
          className="block w-full text-xs text-muted file:mr-3 file:rounded-md file:border file:border-line-strong file:bg-surface file:px-2.5 file:py-1 file:text-xs file:font-medium file:text-ink" />
      </Field>
      {error && <div className="rounded-md border border-bad/20 bg-bad-soft p-2.5 text-xs text-bad"><b>Rejected.</b> {error}</div>}
      <div className="flex justify-end border-t border-line pt-3">
        <Button variant="primary" disabled={!f.id || busy} onClick={submit}>{busy ? "Validating…" : "Create dataset"}</Button>
      </div>
    </div>
  );
}


function ImportMp({ onDone }: { onDone: (id: string) => void }) {
  const [id, setId] = useState("mp-149");
  const imp = useMutation({ mutationFn: () => xrd.importMp(id.trim()), onSuccess: (r) => onDone(r.dataset) });
  return (
    <div className="space-y-3">
      <Field label="Materials Project id" hint="Stored as a reference structure (symmetrized CIF): use it in XRD refinements, overlays and DFT.">
        <input className={cn(inputCls, "font-mono")} value={id} onChange={(e) => setId(e.target.value)} />
      </Field>
      {imp.isError && <p className="text-xs text-bad">{String(imp.error instanceof Error ? imp.error.message : imp.error)}</p>}
      <div className="flex justify-end"><Button variant="primary" disabled={!id.trim() || imp.isPending} onClick={() => imp.mutate()}>
        {imp.isPending ? "Importing…" : "Import"}</Button></div>
    </div>
  );
}

/** Drop in a text pattern: CoRefine reads it, shows what it found, and asks only for what the file does not say. */
function ImportScan({ onDone }: { onDone: (id: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [form, setForm] = useState({ material: "", wavelength_A: "", radiation: "", ka2: "", dataset_id: "" });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const prev = useMutation({
    mutationFn: (f: File) => api.scanPreview(f),
    onSuccess: (r) => setForm((f) => ({ ...f, dataset_id: r.suggested_id, wavelength_A: r.wavelength_A ? String(r.wavelength_A) : "" })),
  });
  const imp = useMutation({ mutationFn: () => api.scanImport(file!, form), onSuccess: (r) => onDone(r.id) });
  const p: ScanPreview | undefined = prev.data;
  const err = (e: unknown) => String(e instanceof Error ? e.message : e);
  return (
    <div className="space-y-3">
      <input ref={input} type="file" accept=".xy,.xye,.csv,.dat,.txt" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) { setFile(f); prev.mutate(f); } }} />
      <Button variant="secondary" onClick={() => input.current?.click()}><Upload size={13} /> {file ? file.name : "Choose a scan file"}</Button>
      <p className="text-[11px] text-muted">A text file with 2θ (degrees) and intensity per line; a header line and a third σ column are fine.
        Nothing leaves your computer.</p>
      {prev.isPending && <p className="text-xs text-muted">Reading…</p>}
      {prev.isError && <p className="text-xs text-bad">{err(prev.error)}</p>}
      {p && <>
        <div className="rounded-md border border-line bg-subtle p-2.5 text-[12px]">
          <div className="font-medium">Found {p.n_points} points, 2θ {p.two_theta_min.toFixed(2)}° to {p.two_theta_max.toFixed(2)}°, step {p.step_deg.toFixed(3)}°</div>
          <div className="text-muted">{p.wavelength_A ? `Wavelength ${p.wavelength_A} Å and anode ${p.anode ?? "?"} read from the file header.`
            : "The file does not give a wavelength; enter it below."}</div>
          {p.notes.map((n) => <div key={n} className="text-warn">{n}</div>)}
        </div>
        <Field label="Sample (formula or elements)" hint="For example Cu2O or Cu,C,O. Needed to identify the phase; leave empty to just view and fit peaks.">
          <input className={inputCls} value={form.material} onChange={set("material")} placeholder="Cu,C,O" /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Wavelength (Å)" hint={p.wavelength_A ? "from the file header" : "required: ask who measured it"}>
            <input className={cn(inputCls, "font-mono")} value={form.wavelength_A} onChange={set("wavelength_A")} /></Field>
          <Field label="Kα2 still in the data?" hint="Cu tube without a monochromator: yes">
            <select className={inputCls} value={form.ka2} onChange={set("ka2")}>
              <option value="">I don't know</option><option value="true">Yes</option><option value="false">No</option></select></Field>
        </div>
        <Field label="Dataset id"><input className={cn(inputCls, "font-mono")} value={form.dataset_id} onChange={set("dataset_id")} /></Field>
        {imp.isError && <p className="text-xs text-bad">{err(imp.error)}</p>}
        <div className="flex justify-end"><Button variant="primary" disabled={imp.isPending || !form.wavelength_A} onClick={() => imp.mutate()}>
          {imp.isPending ? "Importing…" : "Import and open"}</Button></div>
      </>}
    </div>
  );
}
