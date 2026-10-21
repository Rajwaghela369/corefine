import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleDashed, Download, ExternalLink, Upload, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api, dft, type DftJob } from "../api/client";
import { Quadrants } from "../components/Quadrants";
import { Button, Empty, Field, PanelHeader, Tag, clock, cn, inputCls, num } from "../components/ui";
import { RunsPane, livePollInterval } from "./DftRuns";

type SourceKind = "storage" | "mp" | "cod" | "upload";
const SOURCE_TABS: { id: SourceKind; label: string }[] = [
  { id: "storage", label: "Storage" }, { id: "mp", label: "Materials Project" }, { id: "cod", label: "COD" }, { id: "upload", label: "Upload CIF" },
];

export function DftView({ jobId, setJobId }: { jobId: string | null; setJobId: (id: string) => void }) {
  return (
    <div className="grid h-full min-h-0 grid-cols-[360px_1fr]">
      <div className="min-h-0 border-r border-line"><DftForm onCreated={setJobId} selected={jobId} onSelect={setJobId} /></div>
      <div className="flex min-h-0 flex-col">
        {jobId ? <JobWorkspace id={jobId} /> : (
          <Empty title="No input set selected">
            Choose a structure and settings on the left. CoRefine writes inputs for the all-electron codes
            (exciting, Questaal), reads each one back as the code would, and checks they describe the same crystal.
          </Empty>
        )}
      </div>
    </div>
  );
}

function DftForm({ onCreated, selected, onSelect }: { onCreated: (id: string) => void; selected: string | null; onSelect: (id: string) => void }) {
  const qc = useQueryClient();
  const cfg = useQuery({ queryKey: ["dft-config"], queryFn: dft.config });
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const structures = (datasets.data ?? []).filter((d) => d.valid && d.role === "reference_structure");
  const [kind, setKind] = useState<SourceKind>("storage");
  const [ds, setDs] = useState("");
  const [mp, setMp] = useState("mp-149");
  const [cod, setCod] = useState("9008565");
  const [uploaded, setUploaded] = useState<{ structure: string; name: string; summary: string } | null>(null);
  const [xc, setXc] = useState("PBE");
  const [k, setK] = useState([2, 2, 2]);
  const [codes, setCodes] = useState<string[]>([]);
  const registry = cfg.data?.codes ?? [];
  // default: every code that is usable on this server
  useEffect(() => { if (cfg.data) setCodes(cfg.data.codes.filter((c) => c.available).map((c) => c.name)); }, [cfg.data]);
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);

  const source = kind === "storage" ? (ds || structures[0]?.id ? `dataset:${ds || structures[0]?.id}` : "")
    : kind === "mp" ? (mp.trim() ? `mp:${mp.trim().replace(/^mp:/, "")}` : "")
    : kind === "cod" ? (cod.trim() ? `cod:${cod.trim().replace(/^cod:/, "")}` : "")
    : uploaded?.structure ?? "";

  const create = useMutation({
    mutationFn: (usePrompt: boolean) => dft.create(usePrompt ? { prompt } : { structure: source, functional: xc, kmesh: k, codes }),
    onSuccess: (r) => { setError(null); qc.invalidateQueries({ queryKey: ["dft-jobs"] }); onCreated(r.id); },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  });
  const upload = useMutation({
    mutationFn: dft.upload,
    onSuccess: (r) => { setError(null); setUploaded({ structure: r.structure, name: r.name,
      summary: `${r.cell.formula} · ${r.cell.spacegroup} · ${r.cell.natoms} atoms` }); },
    onError: (e) => { setUploaded(null); setError(e instanceof Error ? e.message : String(e)); },
  });

  const toggleCode = (c: string) => setCodes((cs) => (cs.includes(c) ? cs.filter((x) => x !== c) : [...cs, c]));

  return (
    <div className="flex h-full flex-col bg-surface">
      <PanelHeader title="New DFT input set" meta="ground state" />
      <div className="space-y-4 overflow-auto border-b border-line p-4">
        <div>
          <div className="mb-1.5 text-xs font-medium text-ink-2">Structure</div>
          <div className="mb-2 grid grid-cols-4 rounded-md border border-line-strong p-0.5">
            {SOURCE_TABS.map((t) => (
              <button key={t.id} onClick={() => setKind(t.id)} className={cn("rounded px-1 py-1 text-[11px]",
                kind === t.id ? "bg-ink text-white" : "text-muted hover:text-ink")}>{t.label}</button>
            ))}
          </div>
          {kind === "storage" && (structures.length
            ? <select className={inputCls} value={ds || structures[0].id} onChange={(e) => setDs(e.target.value)}>
                {structures.map((d) => <option key={d.id} value={d.id}>{d.id}</option>)}</select>
            : <p className="text-[11px] text-muted">No reference-structure datasets in Storage yet.</p>)}
          {kind === "mp" && <><input className={cn(inputCls, "font-mono")} value={mp} onChange={(e) => setMp(e.target.value)} placeholder="mp-149" />
            <p className="mt-1 text-[11px] text-muted">Read from the public OPTIMADE endpoint; no API key needed. MP cells are PBE-relaxed.</p></>}
          {kind === "cod" && <input className={cn(inputCls, "font-mono")} value={cod} onChange={(e) => setCod(e.target.value)} placeholder="9008565" />}
          {kind === "upload" && (
            <div>
              <label className={cn("flex cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed border-line-strong px-3 py-3 text-xs text-muted hover:border-accent hover:text-accent",
                upload.isPending && "opacity-60")}>
                <Upload size={14} /> {upload.isPending ? "Reading…" : uploaded ? uploaded.name : "Choose a .cif file"}
                <input type="file" accept=".cif" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
              </label>
              {uploaded && <p className="mt-1 text-[11px] text-ok">{uploaded.summary}</p>}
            </div>
          )}
        </div>
        <div className="grid grid-cols-[1fr_1.4fr] gap-3">
          <Field label="Functional">
            <select className={inputCls} value={xc} onChange={(e) => setXc(e.target.value)}>
              <option>PBE</option><option>PBEsol</option><option>LDA</option>
            </select>
          </Field>
          <Field label="k-mesh">
            <div className="grid grid-cols-3 gap-1">
              {k.map((v, i) => <input key={i} type="number" min={1} max={24} className={cn(inputCls, "px-1.5 text-center font-mono")} value={v}
                onChange={(e) => setK(k.map((x, j) => (j === i ? Math.max(1, Number(e.target.value) || 1) : x)))} />)}
            </div>
          </Field>
        </div>
        <div>
          <div className="mb-1.5 flex items-baseline justify-between">
            <span className="text-xs font-medium text-ink-2">Codes</span>
            <span className="text-[11px] text-muted">{registry.filter((c) => c.available).length} of {registry.length} available here</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {registry.map((c) => (
              <button key={c.name} onClick={() => toggleCode(c.name)} disabled={!c.available} title={c.reason}
                className={cn("rounded-md border px-2.5 py-1.5 text-left text-xs disabled:opacity-40",
                  codes.includes(c.name) ? "border-accent bg-accent-soft text-accent" : "border-line-strong text-ink-2")}>
                <div className="font-medium">{c.label}</div>
                <div className="text-[10.5px] text-muted">{c.method}</div>
              </button>
            ))}
          </div>
        </div>
        <p className="text-[11px] leading-4 text-muted">Everything else stays at each code's documented defaults; the generated set lists them.</p>
        <Button variant="primary" className="w-full" disabled={!source || !codes.length || create.isPending} onClick={() => create.mutate(false)}>
          {create.isPending ? "Generating and checking…" : "Generate inputs"}
        </Button>

        <details className="rounded-md border border-line">
          <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-ink-2">Or describe it in words</summary>
          <div className="space-y-2 border-t border-line p-3">
            <textarea className={cn(inputCls, "h-16 py-1.5")} value={prompt} onChange={(e) => setPrompt(e.target.value)}
              placeholder="Do DFT PBE for Si (mp-149) with a simple 2×2×2 k-mesh, normal inputs" />
            {!cfg.data?.prompt && <p className="text-[11px] text-warn">Needs the language model (no Anthropic API key on the server yet).</p>}
            <Button size="sm" variant="secondary" disabled={!prompt.trim() || !cfg.data?.prompt || create.isPending} onClick={() => create.mutate(true)}>
              Interpret and generate</Button>
          </div>
        </details>
        {error && <div className="rounded-md border border-bad/20 bg-bad-soft p-2.5 text-xs text-bad"><b>Refused.</b> {error}</div>}
      </div>
      <div className="flex h-9 shrink-0 items-center border-b border-line px-4 text-xs font-medium">Generated sets</div>
      <div className="min-h-0 flex-1 overflow-auto"><JobList selected={selected} onSelect={onSelect} /></div>
    </div>
  );
}

function JobList({ selected, onSelect }: { selected: string | null; onSelect: (id: string) => void }) {
  const jobs = useQuery({ queryKey: ["dft-jobs"], queryFn: dft.jobs });
  if (jobs.data?.length === 0) return <Empty title="Nothing generated yet" />;
  return (
    <ul className="divide-y divide-line">
      {jobs.data?.map((j) => (
        <li key={j.id}>
          <button onClick={() => onSelect(j.id)} className={cn("w-full px-4 py-2.5 text-left hover:bg-subtle", selected === j.id && "bg-accent-soft hover:bg-accent-soft")}>
            <div className="flex items-center gap-2">
              <span className="text-[12.5px] font-medium">{j.formula}</span>
              <span className="text-[11px] text-muted">{j.functional} · k {j.kmesh.join("×")}</span>
              <span className="ml-auto">{j.passed ? <Tag tone="ok">{j.n_checks} checks passed</Tag> : <Tag tone="bad">{j.n_failed} failed</Tag>}</span>
            </div>
            <div className="mt-0.5 flex gap-3 text-[11px] text-muted"><span className="font-mono">{j.structure.split("/").pop()}</span><span>{clock(j.created)}</span></div>
          </button>
        </li>
      ))}
    </ul>
  );
}

function JobWorkspace({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["dft-job", id], queryFn: () => dft.job(id),
    refetchInterval: (query) => livePollInterval(query.state.data) });
  if (q.isError) return <Empty title="Could not load this input set">{String(q.error)}</Empty>;
  if (!q.data) return <Empty title="Loading…" />;
  const job = q.data;
  const p = job.provenance;
  const failed = job.checks.results.filter((r) => r.ok === false).length;
  const done = job.checks.results.filter((r) => r.ok !== null).length;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-line bg-surface">
        <div className="flex items-center gap-3 px-5 pb-2 pt-3">
          <h1 className="text-[15px] font-semibold">{p.cell.formula} <span className="font-normal text-muted">· {p.request.functional} ground state · k {p.request.kmesh.join("×")}</span></h1>
          {job.checks.passed ? <Tag tone="ok"><CheckCircle2 size={11} /> {done} sanity checks passed</Tag>
            : <Tag tone="bad"><XCircle size={11} /> {failed} of {job.checks.results.length} checks failed</Tag>}
          <a href={dft.archiveUrl(id)} className="ml-auto"><Button size="sm" variant="secondary"><Download size={13} /> Download set (.zip)</Button></a>
        </div>
        <div className="grid grid-cols-4 border-t border-line">
          <Cellv label="Space group" value={p.cell.spacegroup} />
          <Cellv label="Atoms in primitive cell" value={String(p.cell.natoms)} />
          <Cellv label="Volume per atom" value={`${num(p.cell.volume_per_atom_A3)} Å³`} mono />
          <Cellv label="Nearest neighbour" value={`${num(p.cell.nearest_neighbour_A)} Å`} mono />
        </div>
      </div>
      <Quadrants panes={[
        { key: "structure", title: "Structure", body: <StructurePane job={job} /> },
        { key: "checks", title: "Sanity checks", body: <ChecksPane job={job} /> },
        { key: "inputs", title: "Inputs", body: <InputsPane job={job} /> },
        { key: "runs", title: "Runs & results", body: <RunsPane job={job} /> },
      ]} />
    </div>
  );
}

function Cellv({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="border-l border-line px-5 py-2.5 first:border-l-0">
      <div className="text-[11px] text-muted">{label}</div>
      <div className={cn("mt-0.5 text-[15px] font-medium", mono && "tabular font-mono")}>{value}</div>
    </div>
  );
}

function StructurePane({ job }: { job: DftJob }) {
  const p = job.provenance;
  const ref = job.checks.reference;
  const codes = job.checks.codes as Record<string, any>;
  const rows: [string, string, (m: any) => string][] = [
    ["Formula", "formula", (m) => m.formula], ["Space group", "sg", (m) => `${m.spacegroup} (${m.spacegroup_number})`],
    ["Volume / atom (Å³)", "v", (m) => m.volume_per_atom_A3.toFixed(6)], ["Nearest neighbour (Å)", "nn", (m) => m.nearest_neighbour_A?.toFixed(6) ?? "—"],
  ];
  return (
    <div className="space-y-4 p-4 text-xs">
      <dl className="grid grid-cols-[120px_1fr] gap-y-1.5">
        <dt className="text-muted">Source</dt><dd className="font-mono">{p.source.source.split("/").pop()}</dd>
        {p.source.url && <><dt className="text-muted">URL</dt><dd className="truncate"><a className="text-accent hover:underline" href={p.source.url} target="_blank" rel="noreferrer">{p.source.url} <ExternalLink size={10} className="inline" /></a></dd></>}
        {p.source.sha256 && <><dt className="text-muted">SHA-256</dt><dd className="truncate font-mono text-[11px]">{p.source.sha256}</dd></>}
        <dt className="text-muted">Declared space group</dt><dd>{p.source.declared_spacegroup ?? "not stated"}</dd>
        <dt className="text-muted">Lattice lengths</dt><dd className="font-mono">{p.cell.lattice_lengths_A.map((x) => x.toFixed(6)).join(", ")} Å</dd>
      </dl>
      {p.source.notes.map((n) => <p key={n} className="rounded-md bg-warn-soft px-2.5 py-1.5 text-warn">{n}</p>)}
      <div>
        <div className="mb-1 font-medium text-ink-2">Each input read back as its code reads it</div>
        <table className="tabular w-full">
          <thead className="text-left text-[11px] text-muted"><tr><th className="py-1 font-medium" />
            <th className="font-medium">Source cell</th>{Object.keys(codes).map((c) => <th key={c} className="font-medium">{p.generated[c]?.label ?? c}</th>)}</tr></thead>
          <tbody className="divide-y divide-line">
            {rows.map(([label, key, f]) => (
              <tr key={key}><td className="py-1.5 text-muted">{label}</td><td className="font-mono">{f(ref)}</td>
                {Object.values(codes).map((m, i) => <td key={i} className="font-mono">{f(m)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ChecksPane({ job }: { job: DftJob }) {
  return (
    <ul className="divide-y divide-line">
      {job.checks.results.map((r) => (
        <li key={r.check} className="flex gap-2.5 px-4 py-2">
          {r.ok ? <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-ok" />
            : r.ok === null ? <CircleDashed size={14} className="mt-0.5 shrink-0 text-faint" />
            : <XCircle size={14} className="mt-0.5 shrink-0 text-bad" />}
          <div className="min-w-0">
            <div className="text-xs font-medium">{r.check}</div>
            <div className="truncate font-mono text-[11px] text-muted" title={r.detail}>{r.detail}</div>
          </div>
        </li>
      ))}
    </ul>
  );
}

function InputsPane({ job }: { job: DftJob }) {
  const codes = Object.entries(job.provenance.generated);
  const [code, setCode] = useState(codes[0]?.[0]);
  return (
    <div className="flex h-full flex-col">
      <div className="flex gap-1 border-b border-line bg-subtle/60 px-2 py-1">
        {codes.map(([c, g]) => <button key={c} onClick={() => setCode(c)} className={cn("rounded px-2 py-0.5 text-[11.5px]",
          c === code ? "bg-surface font-medium text-ink shadow-sm ring-1 ring-line" : "text-muted hover:text-ink")}>{g.label}</button>)}
      </div>
      <div className="min-h-0 flex-1">{code && <CodePane key={code} job={job} code={code} />}</div>
    </div>
  );
}

// Files a person reads; build artefacts (atm, basp0, log) stay in the download
const HIDDEN = [/^atm\./, /^basp0\./, /^log\./, /^mixm\./, /^rst\./, /^moms\.h5$/, /^wkp\./,
  /^(STATE|EVEC\w*|EVAL\w*|SYM\w*|EIGVAL|OCCSV|LINENGY|EQATOMS|KPOINTS|LATTICE|BONDLENGTH|RMSDVEFF|EFERMI|TOTENERGY)\.OUT$/i,
  /^(info|eigval|evalcore|atoms|geometry|\w+_scf)\.xml$/];
const order = (f: string, main: string) => (f.startsWith(main) ? 0 : f.startsWith("init.") ? 1 : /\.(in|log|out)$/.test(f) ? 3 : 2);

function CodePane({ job, code }: { job: DftJob; code: string }) {
  const g = job.provenance.generated[code];
  const files = job.files.filter((f) => f.startsWith(`${code}/`)).map((f) => f.slice(code.length + 1))
    .filter((f) => !HIDDEN.some((re) => re.test(f)))
    .sort((a, b) => order(a, g.main_file) - order(b, g.main_file) || a.localeCompare(b));
  const [tab, setTab] = useState(0);
  const path = files[Math.min(tab, files.length - 1)];
  const q = useQuery({ queryKey: ["dft-file", job.id, code, path], queryFn: () => dft.file(job.id, `${code}/${path}`), enabled: !!path });
  const defaults = Object.entries(g.defaults.values).map(([k, v]) => `${k}=${v}`).join(", ");
  return (
    <div className="flex h-full flex-col">
      <div className="flex gap-0.5 overflow-x-auto border-b border-line px-2">
        {files.map((f, i) => <button key={f} onClick={() => setTab(i)} className={cn("-mb-px shrink-0 border-b-2 px-2 py-1.5 font-mono text-[11px]",
          i === tab ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink")}>{f}</button>)}
      </div>
      <pre className="min-h-0 flex-1 overflow-auto bg-subtle/60 p-3 font-mono text-[11px] leading-[1.55]">{q.data ?? ""}</pre>
      <div className="border-t border-line px-3 py-2 text-[11px] leading-4 text-muted">
        <span className="font-medium text-ink-2">Set from your request:</span> {Object.entries(g.set_explicitly).map(([k, v]) => `${k} = ${v}`).join(" · ")}
        <br /><span className="font-medium text-ink-2">Code defaults</span> ({g.defaults.source}): {defaults}
      </div>
    </div>
  );
}
