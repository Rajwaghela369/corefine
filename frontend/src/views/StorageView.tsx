import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, FileText, Plus, RefreshCw, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { api, type DatasetNode, type FileFacts, type ScanPreview, xrd } from "../api/client";
import { radiationLabel } from "../components/labels";
import { useDetailed } from "../components/prefs";
import { Button, Dialog, Empty, Field, PanelHeader, Tag, cn, inputCls, num } from "../components/ui";
import { XrdInspector } from "./XrdInspector";

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
  const detailed = useDetailed();
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
    ["Radiation type", radiationLabel(inst.radiation)], ["Radiation source", inst.radiation_source], ["Wavelength", inst.wavelength_A != null ? `${num(inst.wavelength_A, 10)} Å` : undefined],
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
        <dl className="grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-line bg-line">
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

      <details key={String(detailed)} open={detailed} className="group rounded-lg border border-line bg-surface">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-xs font-semibold">
          <ChevronRight size={14} className="text-muted transition group-open:rotate-90" />
          Files and manifest <span className="font-normal text-muted">{files.length} file{files.length === 1 ? "" : "s"} · dataset.yaml (for editing the record by hand)</span>
        </summary>
      <div className="grid grid-cols-[1fr_1fr] gap-5 border-t border-line p-3">
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
            <textarea className="min-h-80 flex-1 resize-y p-3 font-mono text-[11px] leading-4 outline-none"
              value={text ?? (m.data ? JSON.stringify(m.data, null, 2) : "")} onChange={(e) => setText(e.target.value)} spellCheck={false} />
            {save.isError && <p className="border-t border-line px-3 py-2 text-[11px] text-bad">{String(save.error)}</p>}
          </div>
        )}
      </div>
      </details>
    </div>
  );
}

type Origin = "files" | "mp" | "cod";
const ORIGINS: { id: Origin; label: string; hint: string }[] = [
  { id: "files", label: "Upload files", hint: "A scan or structure from your computer" },
  { id: "mp", label: "Materials Project", hint: "A computed structure, by mp- id" },
  { id: "cod", label: "Crystallography Open Database", hint: "A published structure, by COD number" },
];
// coreCIF _diffrn_source examples
const SOURCES = ["sealed X-ray tube", "rotating-anode X-ray tube", "synchrotron", "nuclear reactor", "spallation source", "electron microscope"];

/** The one way in for data: upload files, or bring a structure from Materials Project or COD. */
function AddDataset({ onDone }: { onDone: (id: string) => void }) {
  const [origin, setOrigin] = useState<Origin>("files");
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Where the data comes from">
        {ORIGINS.map((o) => (
          <button key={o.id} role="radio" aria-checked={origin === o.id} onClick={() => setOrigin(o.id)}
            className={cn("rounded-md border px-2.5 py-2 text-left", origin === o.id ? "border-accent bg-accent-soft/60" : "border-line hover:border-line-strong")}>
            <span className="block text-[12.5px] font-medium">{o.label}</span>
            <span className="block text-[11px] leading-4 text-muted">{o.hint}</span>
          </button>
        ))}
      </div>
      {origin === "files" ? <UploadDataset onDone={onDone} /> : <ImportStructure key={origin} origin={origin} onDone={onDone} />}
    </div>
  );
}

const slug = (s: string) => s.toLowerCase().replace(/\.[a-z0-9]+$/, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);

function UploadDataset({ onDone }: { onDone: (id: string) => void }) {
  const [f, setF] = useState({ id: "", role: "measured_pattern", technique: "xrd_powder", material: "",
    format: "pdcif", radiation: "", radiation_source: "", probe: "x-ray", wavelength: "", wavelength_source: "", source: "", readme: "" });
  const [files, setFiles] = useState<File[]>([]);
  const [facts, setFacts] = useState<FileFacts["found"]>({});
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const measured = f.role === "measured_pattern";
  const fromFile = (k: keyof FileFacts["found"]) => facts[k] && <Tag tone="ok" className="shrink-0 whitespace-nowrap" title={`read from ${facts[k]!.tag} in the file`}>from file</Tag>;

  async function choose(list: File[]) {
    setFiles(list); setError(null);
    const cif = list.find((x) => x.name.toLowerCase().endsWith(".cif"));
    const next = { ...f, id: f.id || slug(list[0]?.name ?? "") };
    if (!cif) { setFacts({}); setF(next); return; }
    setReading(true);
    try {
      const r = await api.inspectFile(cif);
      const v = (k: keyof FileFacts["found"]) => r.found[k] != null ? String(r.found[k]!.value) : "";
      setFacts(r.found);
      setF({ ...next, ...(r.role ? { role: r.role, technique: r.role === "measured_pattern" ? "xrd_powder" : "structure" } : {}),
        ...(r.format ? { format: r.format } : {}), material: v("material").replace(/\s+/g, "") || next.material,
        radiation: v("radiation") ? radiationLabel(v("radiation"))! : next.radiation,
        radiation_source: v("radiation_source") || next.radiation_source, probe: v("probe") || next.probe,
        wavelength: v("wavelength_A") || next.wavelength,
        wavelength_source: r.found.wavelength_A ? `in the file: ${r.found.wavelength_A.tag}` : next.wavelength_source });
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setReading(false); }
  }

  async function submit() {
    setError(null); setBusy(true);
    try {
      const inst: Record<string, unknown> = { radiation: f.radiation || null, radiation_source: f.radiation_source || null,
        probe: f.probe || null, wavelength_A: f.wavelength ? Number(f.wavelength) : null, wavelength_source: f.wavelength_source || null };
      const manifest: Record<string, unknown> = { id: f.id, role: f.role, technique: f.technique, material: f.material,
        format: f.format, files: ["raw/*"], ...(f.source ? { source: f.source } : {}),
        ...(measured ? { instrument: Object.fromEntries(Object.entries(inst).filter(([, v]) => v != null)) } : {}) };
      await api.createDataset(manifest, f.readme || undefined);
      if (files.length) await api.upload(f.id, files);
      onDone(f.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  return (
    <div className="space-y-3">
      <Field label="Files" hint="A powder scan (.cif, .xy, .csv) or a crystal structure (.cif). What a CIF states about itself fills the form.">
        <input type="file" multiple onChange={(e) => choose(Array.from(e.target.files ?? []))}
          className="block w-full text-xs text-muted file:mr-3 file:rounded-md file:border file:border-line-strong file:bg-surface file:px-2.5 file:py-1 file:text-xs file:font-medium file:text-ink" />
      </Field>
      {reading && <p className="text-[11.5px] text-muted">Reading the file…</p>}
      <Field label="Dataset name" hint="Lowercase letters, digits and hyphens. Becomes the folder name.">
        <input className={cn(inputCls, "font-mono")} placeholder="si-scan-2026-10" value={f.id} onChange={set("id")} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="What it is">
          <select className={inputCls} value={f.role} onChange={set("role")}>
            <option value="measured_pattern">Measured scan</option>
            <option value="reference_structure">Reference structure</option>
            <option value="reference_value">Reference value</option>
          </select>
        </Field>
        <Field label="File format">
          <select className={inputCls} value={f.format} onChange={set("format")}>
            <option value="pdcif">Powder CIF (pdCIF)</option><option value="cif">Structure CIF</option>
            <option value="xy">XY</option><option value="csv">CSV</option>
          </select>
        </Field>
        <Field label="Material"><div className="flex items-center gap-2">
          <input className={inputCls} placeholder="e.g. Si" value={f.material} onChange={set("material")} />{fromFile("material")}</div></Field>
        <Field label="Technique"><input className={inputCls} value={f.technique} onChange={set("technique")} /></Field>
      </div>
      {measured && <fieldset className="space-y-3 rounded-md border border-line p-3">
        <legend className="px-1 text-[11.5px] font-medium text-ink-2">Instrument</legend>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Radiation type" hint="The emission line, as in CIF _diffrn_radiation_type: Cu Kα1, Cu Kα, Mo Kα …">
            <div className="flex items-center gap-2"><input className={inputCls} placeholder="Cu Kα1" value={f.radiation} onChange={set("radiation")} />
              {fromFile("radiation")}</div></Field>
          <Field label="Radiation source" hint="What produced it, as in CIF _diffrn_source.">
            <div className="flex items-center gap-2"><select className={inputCls} value={f.radiation_source} onChange={set("radiation_source")}>
              <option value="">Not stated</option>{SOURCES.map((x) => <option key={x} value={x}>{x}</option>)}
              {f.radiation_source && !SOURCES.includes(f.radiation_source) && <option value={f.radiation_source}>{f.radiation_source}</option>}
            </select>{fromFile("radiation_source")}</div></Field>
          <Field label="Wavelength (Å)" hint="Leave blank if unknown; analyses stop rather than guess.">
            <div className="flex items-center gap-2"><input className={cn(inputCls, "font-mono")} placeholder="1.5405929" value={f.wavelength}
              onChange={set("wavelength")} />{fromFile("wavelength_A")}</div></Field>
          <Field label="Where the wavelength comes from" hint="e.g. the instrument's calibration, or a certificate.">
            <input className={inputCls} value={f.wavelength_source} onChange={set("wavelength_source")} /></Field>
        </div>
        <Field label="Probe"><div className="flex items-center gap-2"><select className={inputCls} value={f.probe} onChange={set("probe")}>
          <option value="x-ray">X-ray</option><option value="neutron">Neutron</option><option value="electron">Electron</option>
          <option value="">Not stated</option></select>{fromFile("probe")}</div></Field>
      </fieldset>}
      <Field label="Source"><input className={inputCls} placeholder="DOI or URL" value={f.source} onChange={set("source")} /></Field>
      <Field label="Notes"><textarea className={cn(inputCls, "h-16 py-1.5")} placeholder="Provenance, licence, anything an analyst should know"
        value={f.readme} onChange={set("readme")} /></Field>
      {error && <div className="rounded-md border border-bad/20 bg-bad-soft p-2.5 text-xs text-bad"><b>Rejected.</b> {error}</div>}
      <div className="sticky -bottom-5 -mx-5 -mb-5 flex justify-end border-t border-line bg-surface px-5 py-3">
        <Button variant="primary" disabled={!f.id || !f.material || busy || reading} onClick={submit}>{busy ? "Validating…" : "Create dataset"}</Button>
      </div>
    </div>
  );
}

function ImportStructure({ origin, onDone }: { origin: "mp" | "cod"; onDone: (id: string) => void }) {
  const mp = origin === "mp";
  const [id, setId] = useState(mp ? "mp-149" : "");
  const imp = useMutation({ mutationFn: () => (mp ? xrd.importMp(id.trim()) : xrd.importCod(id.trim())), onSuccess: (r) => onDone(r.dataset) });
  return (
    <div className="space-y-3">
      <Field label={mp ? "Materials Project id" : "COD number"}
        hint={mp ? "Saved as a reference structure (symmetrized CIF), usable in analyses, comparisons and simulations."
          : "Saved as a reference structure with the CIF exactly as published, usable in analyses, comparisons and simulations."}>
        <input className={cn(inputCls, "font-mono")} placeholder={mp ? "mp-149" : "2300450"} value={id} onChange={(e) => setId(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && id.trim()) imp.mutate(); }} />
      </Field>
      {imp.isError && <p className="text-xs text-bad">{String(imp.error instanceof Error ? imp.error.message : imp.error)}</p>}
      <div className="flex justify-end border-t border-line pt-3"><Button variant="primary" disabled={!id.trim() || imp.isPending} onClick={() => imp.mutate()}>
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
