import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, FolderOpen, RefreshCw, Upload } from "lucide-react";
import { useState } from "react";
import { api, type DatasetNode } from "../api/client";
import { Badge, Button, Section, cn } from "../components/ui";

const ROLE_LABEL: Record<string, string> = {
  measured_pattern: "measured", reference_structure: "structure", reference_value: "reference",
};

export function DataPanel({ selected, onToggle }: { selected: Set<string>; onToggle: (id: string) => void }) {
  const qc = useQueryClient();
  const tree = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const rescan = useMutation({ mutationFn: api.rescan, onSuccess: () => qc.invalidateQueries({ queryKey: ["datasets"] }) });
  const [open, setOpen] = useState<string | null>(null);
  const [showUpload, setShowUpload] = useState(false);

  return (
    <Section title="Data" right={
      <div className="flex gap-1">
        <Button variant="ghost" title="Rescan manifests" onClick={() => rescan.mutate()}><RefreshCw size={14} /></Button>
        <Button variant="ghost" title="Upload" onClick={() => setShowUpload((v) => !v)}><Upload size={14} /></Button>
      </div>}>
      {showUpload && <UploadForm onDone={() => { setShowUpload(false); qc.invalidateQueries({ queryKey: ["datasets"] }); }} />}
      {tree.isError && <p className="p-3 text-sm text-red-700">{String(tree.error)}</p>}
      <ul className="divide-y divide-line">
        {tree.data?.map((d) => (
          <DatasetRow key={d.id} d={d} checked={selected.has(d.id)} onToggle={() => onToggle(d.id)}
            open={open === d.id} onOpen={() => setOpen(open === d.id ? null : d.id)} />
        ))}
      </ul>
      {tree.data?.length === 0 && <p className="p-3 text-sm text-muted">No datasets yet. Run scripts/setup.py or upload one.</p>}
    </Section>
  );
}

function DatasetRow({ d, checked, onToggle, open, onOpen }:
  { d: DatasetNode; checked: boolean; onToggle: () => void; open: boolean; onOpen: () => void }) {
  return (
    <li className="px-3 py-2">
      <div className="flex items-center gap-2">
        <input type="checkbox" disabled={!d.valid} checked={checked} onChange={onToggle}
          title={d.valid ? "Use in run" : d.problem ?? ""} />
        <button className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-sm" onClick={onOpen}>
          <FolderOpen size={14} className="shrink-0 text-muted" />
          <span className="truncate font-medium">{d.id}</span>
        </button>
        {d.valid ? <Badge tone="info">{ROLE_LABEL[d.role ?? ""] ?? d.role}</Badge>
          : <Badge tone="warn"><AlertTriangle size={11} className="mr-1" />no manifest</Badge>}
      </div>
      {!d.valid && <p className="mt-1 text-xs text-amber-800">{d.problem}</p>}
      {open && (
        <div className="mt-2 space-y-2">
          <ul className="max-h-32 overflow-auto rounded bg-panel p-2 font-mono text-[11px] text-muted">
            {d.files.map((f) => <li key={f} className="truncate">{f}</li>)}
          </ul>
          {d.valid && <ManifestEditor id={d.id} />}
        </div>
      )}
    </li>
  );
}

function ManifestEditor({ id }: { id: string }) {
  const qc = useQueryClient();
  const m = useQuery({ queryKey: ["manifest", id], queryFn: () => api.manifest(id) });
  const [text, setText] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => api.saveManifest(id, JSON.parse(text ?? "{}")),
    onSuccess: () => { setText(null); qc.invalidateQueries({ queryKey: ["manifest", id] }); },
  });
  const value = text ?? (m.data ? JSON.stringify(m.data, null, 2) : "");
  return (
    <div>
      <textarea className="h-40 w-full rounded border border-line p-2 font-mono text-[11px]" value={value}
        onChange={(e) => setText(e.target.value)} spellCheck={false} />
      <div className="flex items-center gap-2">
        <Button variant="outline" disabled={text === null || save.isPending} onClick={() => save.mutate()}>Save manifest</Button>
        {save.isError && <span className="text-xs text-red-700">{String(save.error)}</span>}
      </div>
    </div>
  );
}

function UploadForm({ onDone }: { onDone: () => void }) {
  const [f, setF] = useState({ id: "", role: "measured_pattern", technique: "xrd_powder", material: "Si",
    format: "pdcif", radiation: "CuKa1", wavelength: "", readme: "" });
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  async function submit() {
    setError(null); setBusy(true);
    try {
      const manifest: Record<string, unknown> = { id: f.id, role: f.role, technique: f.technique, material: f.material,
        format: f.format, files: ["raw/*"] };
      if (f.role === "measured_pattern")
        manifest.instrument = { radiation: f.radiation, wavelength_A: f.wavelength ? Number(f.wavelength) : null };
      await api.createDataset(manifest, f.readme || undefined);
      if (files.length) await api.upload(f.id, files);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  const input = "w-full rounded border border-line px-2 py-1 text-sm";
  return (
    <div className="space-y-2 border-b border-line bg-panel p-3 text-sm">
      <input className={input} placeholder="dataset id (e.g. my-si-scan)" value={f.id} onChange={set("id")} />
      <div className="grid grid-cols-2 gap-2">
        <select className={input} value={f.role} onChange={set("role")}>
          <option value="measured_pattern">measured pattern</option>
          <option value="reference_structure">reference structure</option>
          <option value="reference_value">reference value</option>
        </select>
        <select className={input} value={f.format} onChange={set("format")}>
          {["pdcif", "cif", "xy", "csv"].map((x) => <option key={x}>{x}</option>)}
        </select>
        <input className={input} placeholder="technique" value={f.technique} onChange={set("technique")} />
        <input className={input} placeholder="material" value={f.material} onChange={set("material")} />
        {f.role === "measured_pattern" && <>
          <input className={input} placeholder="radiation" value={f.radiation} onChange={set("radiation")} />
          <input className={input} placeholder="wavelength Å (blank = unknown)" value={f.wavelength} onChange={set("wavelength")} />
        </>}
      </div>
      <textarea className={cn(input, "h-14")} placeholder="README: source, licence, notes" value={f.readme} onChange={set("readme")} />
      <input type="file" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))} className="text-xs" />
      {error && <p className="rounded bg-red-50 p-2 text-xs text-red-700">Refused: {error}</p>}
      <Button disabled={!f.id || busy} onClick={submit}>{busy ? "Uploading…" : "Create dataset"}</Button>
    </div>
  );
}
