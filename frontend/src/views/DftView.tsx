import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleDashed, Download, ExternalLink, Upload, X, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api, dft, type DftJob, type MpMaterial } from "../api/client";
import { Button, Empty, Field, PanelHeader, Status, Tag, clock, cn, inputCls, num } from "../components/ui";
import { RunsPane, livePollInterval, runIsLive } from "./DftRuns";
import { ConvergencePane } from "./DftStudies";
import { Dot, Sections } from "../components/Sections";
import { Atom, FileCode, LayoutDashboard, Play, Search, ShieldCheck, Sigma, TrendingDown } from "lucide-react";
import { Welcome, WelcomeSection } from "../components/Welcome";
import { useGo } from "../components/nav";

type SourceKind = "find" | "storage" | "mp" | "cod" | "upload";
const SOURCE_TABS: { id: SourceKind; label: string }[] = [
  { id: "find", label: "Find material" }, { id: "storage", label: "Storage" }, { id: "mp", label: "MP id" },
  { id: "cod", label: "COD" }, { id: "upload", label: "CIF" },
];

export function DftView({ jobId, setJobId }: { jobId: string | null; setJobId: (id: string | null) => void }) {
  // a ?study= link opens that tab once; read it before the address bar is rewritten
  const [study] = useState(() => new URLSearchParams(window.location.search).get("study") ?? undefined);
  return (
    <div className="grid h-full min-h-0 grid-cols-[360px_1fr]">
      <div className="min-h-0 border-r border-line"><DftForm onCreated={setJobId} selected={jobId} onSelect={setJobId} /></div>
      <div className="flex min-h-0 flex-col">
        {jobId ? <JobWorkspace id={jobId} study={study} onClose={() => setJobId(null)} /> : <DftWelcome onOpen={setJobId} />}
      </div>
    </div>
  );
}

function DftWelcome({ onOpen }: { onOpen: (id: string) => void }) {
  const cfg = useQuery({ queryKey: ["dft-config"], queryFn: dft.config });
  const targets = useQuery({ queryKey: ["dft-targets"], queryFn: dft.targets });
  const jobs = useQuery({ queryKey: ["dft-jobs"], queryFn: dft.jobs });
  const runnable = new Set((targets.data ?? []).filter((t) => t.kind === "local").flatMap((t) => t.codes));
  return (
    <Welcome title="Theory: DFT for any material"
      intro="Pick a material from Materials Project. CoRefine plans the calculation, writes inputs for every code below, checks that they all
        describe the same crystal, runs the codes installed on this machine and shows what each code finds (band gap, convergence)."
      steps={[
        { icon: Search, title: "Pick a material", text: "Search by formula or elements on the left; the stable phase is listed first." },
        { icon: Play, title: "Plan and run", text: "The plan and its reasons are shown, inputs are checked, and installed codes run one after another." },
        { icon: Sigma, title: "Read the results", text: "Band gap and convergence per code, next to Materials Project." },
      ]}>
      <WelcomeSection title={`Programs ready to use (${(cfg.data?.codes ?? []).filter((c) => c.available).length})`}>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {(cfg.data?.codes ?? []).filter((c) => c.available).map((c) => (
            <div key={c.name} className="rounded-lg border border-line bg-surface px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-semibold">{c.label}</span>
                {runnable.has(c.name) ? <Tag tone="ok">runs here</Tag> : c.available ? <Tag>inputs only</Tag> : <Tag tone="warn">install</Tag>}
              </div>
              <div className="mt-0.5 text-[11.5px] text-muted">{c.method}</div>
            </div>
          ))}
        </div>
        {(cfg.data?.codes ?? []).some((c) => !c.available) && <details className="mt-2 rounded-lg border border-line bg-surface">
          <summary className="cursor-pointer px-3 py-2 text-[12.5px] text-ink-2">
            {(cfg.data?.codes ?? []).filter((c) => !c.available).length} more programs need setup before they can be used</summary>
          <ul className="divide-y divide-line border-t border-line">
            {(cfg.data?.codes ?? []).filter((c) => !c.available).map((c) => (
              <li key={c.name} className="px-3 py-2 text-[12px]"><span className="font-medium">{c.label}</span>
                <span className="text-muted"> · {c.method}</span><div className="text-[11.5px] text-muted">{c.reason}</div></li>))}
          </ul>
        </details>}
      </WelcomeSection>
      {(jobs.data?.length ?? 0) > 0 && <WelcomeSection title="Recent sets">
        <div className="grid gap-2 sm:grid-cols-2">
          {jobs.data!.slice(0, 6).map((j) => (
            <button key={j.id} onClick={() => onOpen(j.id)} className="rounded-lg border border-line bg-surface px-3 py-2.5 text-left hover:border-accent">
              <div className="flex items-center gap-2"><span className="text-[13px] font-semibold">{j.formula}</span>
                <span className="text-[11.5px] text-muted">{j.functional} · k {j.kmesh.join("×")} · {j.codes.length} codes</span>
                <span className="ml-auto">{j.passed ? <Tag tone="ok">checks passed</Tag> : <Tag tone="bad">{j.n_failed} failed</Tag>}</span></div>
              <div className="mt-0.5 font-mono text-[11px] text-faint">{j.structure.split("/").pop()} · {clock(j.created)}</div>
            </button>
          ))}
        </div>
      </WelcomeSection>}
    </Welcome>
  );
}

function DftForm({ onCreated, selected, onSelect }: { onCreated: (id: string) => void; selected: string | null; onSelect: (id: string) => void }) {
  const qc = useQueryClient();
  const cfg = useQuery({ queryKey: ["dft-config"], queryFn: dft.config });
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const structures = (datasets.data ?? []).filter((d) => d.valid && d.role === "reference_structure");
  const [kind, setKind] = useState<SourceKind>("find");
  const [picked, setPicked] = useState<MpMaterial | null>(null);
  const [kTouched, setKTouched] = useState(false);
  const [goal, setGoal] = useState("");
  const [ds, setDs] = useState("");
  const [mp, setMp] = useState("mp-149");
  const [cod, setCod] = useState("9008565");
  const [uploaded, setUploaded] = useState<{ structure: string; name: string; summary: string } | null>(null);
  const [xc, setXc] = useState("PBE");
  const [k, setK] = useState([2, 2, 2]);
  const preview = useQuery({ queryKey: ["plan-preview", picked?.id, xc], enabled: kind === "find" && !!picked,
    queryFn: () => dft.planPreview(picked!.id, xc) });
  const plannedK = (preview.data?.plan.request.kmesh as number[] | undefined) ?? null;
  // show the mesh the planner will use; keep the person's own mesh once they type one
  useEffect(() => { if (plannedK && !kTouched) setK(plannedK); }, [plannedK?.join(","), kTouched]);  // eslint-disable-line react-hooks/exhaustive-deps
  const [codes, setCodes] = useState<string[]>([]);
  const registry = cfg.data?.codes ?? [];
  // default: every code that is usable on this server
  useEffect(() => { if (cfg.data) setCodes(cfg.data.codes.filter((c) => c.available).map((c) => c.name)); }, [cfg.data]);
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);

  const source = kind === "find" ? (picked ? `mp:${picked.id}` : "") : kind === "storage" ? (ds || structures[0]?.id ? `dataset:${ds || structures[0]?.id}` : "")
    : kind === "mp" ? (mp.trim() ? `mp:${mp.trim().replace(/^mp:/, "")}` : "")
    : kind === "cod" ? (cod.trim() ? `cod:${cod.trim().replace(/^cod:/, "")}` : "")
    : uploaded?.structure ?? "";

  const wf = useMutation({
    mutationFn: () => dft.workflow({ material: picked!.id, functional: xc, kmesh: kTouched ? k : null, codes,
      goal: goal.trim() || undefined }),
    onSuccess: (r) => { setError(null); qc.invalidateQueries({ queryKey: ["dft-jobs"] }); onCreated(r.id); },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  });
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
          <div className="mb-2 grid grid-cols-5 rounded-md border border-line-strong p-0.5">
            {SOURCE_TABS.map((t) => (
              <button key={t.id} onClick={() => setKind(t.id)} className={cn("rounded px-1 py-1 text-[11px]",
                kind === t.id ? "bg-ink text-white" : "text-muted hover:text-ink")}>{t.label}</button>
            ))}
          </div>
          {kind === "find" && <MaterialSearch picked={picked} onPick={(m) => { setPicked(m); setKTouched(false); }} />}
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
          <Field label="k-mesh (Γ-centred)">
            <div className="grid grid-cols-3 gap-1">
              {k.map((v, i) => <input key={i} type="number" min={1} max={24} className={cn(inputCls, "px-1.5 text-center font-mono",
                kind === "find" && !kTouched && "text-muted")} value={kind === "find" && !picked && !kTouched ? "" : v} placeholder="–"
                onChange={(e) => { setKTouched(true); setK(k.map((x, j) => (j === i ? Math.max(1, Number(e.target.value) || 1) : x))); }} />)}
            </div>
            {kind === "find" && <div className="mt-1 text-[10.5px] leading-4 text-muted">
              {!picked ? "pick a material to see the planned mesh" : preview.isFetching ? "planning…"
                : kTouched ? <>your mesh is used · <button className="text-accent hover:underline" onClick={() => { setKTouched(false); if (plannedK) setK(plannedK); }}>use planned</button></>
                : "planned from a 0.3 Å⁻¹ k-point spacing; type to override"}</div>}
          </Field>
        </div>
        <div>
          <div className="mb-1.5 flex items-baseline justify-between">
            <span className="text-xs font-medium text-ink-2">Programs</span>
            <span className="text-[11px] text-muted">{registry.filter((c) => c.available).length} of {registry.length} ready</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {registry.filter((c) => c.available).map((c) => (
              <button key={c.name} onClick={() => toggleCode(c.name)} disabled={!c.available} title={c.reason}
                className={cn("rounded-md border px-2.5 py-1.5 text-left text-xs disabled:opacity-40",
                  codes.includes(c.name) ? "border-accent bg-accent-soft text-accent" : "border-line-strong text-ink-2")}>
                <div className="font-medium">{c.label}</div>
                <div className="text-[10.5px] text-muted">{c.method}</div>
              </button>
            ))}
          </div>
          <CodeInstaller />
        </div>
        <p className="text-[11px] leading-4 text-muted">Everything else stays at each code's documented defaults; the generated set lists them.</p>
        {kind === "find" ? <>
          <textarea className={cn(inputCls, "h-12 py-1.5")} value={goal} onChange={(e) => setGoal(e.target.value)}
            placeholder="Goal for the planning agent (optional), e.g. quick check of the band gap" />
          <Button variant="primary" className="w-full" disabled={!picked || !codes.length || wf.isPending} onClick={() => wf.mutate()}>
            {wf.isPending ? "Planning and writing inputs…" : picked ? `Plan and run ${picked.formula} (${picked.id})` : "Pick a material first"}
          </Button>
          <p className="text-[11px] leading-4 text-muted">Plans the calculation, writes and checks inputs for every selected code,
            then runs each code that is installed here, one after another.</p>
        </> : <Button variant="primary" className="w-full" disabled={!source || !codes.length || create.isPending} onClick={() => create.mutate(false)}>
          {create.isPending ? "Generating and checking…" : "Generate inputs"}
        </Button>}

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

function MaterialSearch({ picked, onPick }: { picked: MpMaterial | null; onPick: (m: MpMaterial) => void }) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const res = useQuery({ queryKey: ["mp-search", query], queryFn: () => dft.searchMaterials(query), enabled: !!query });
  return (
    <div>
      <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()); }}>
        <input className={cn(inputCls, "font-mono")} value={q} onChange={(e) => setQ(e.target.value)} placeholder="GaAs, TiO2, or Ga,As" />
        <Button size="md" variant="secondary" type="submit">Search</Button>
      </form>
      <p className="mt-1 text-[10.5px] text-muted">Materials Project, stable phases first. Formula or elements.</p>
      {res.isFetching && <p className="mt-2 text-[11px] text-muted">Searching…</p>}
      {res.isError && <p className="mt-2 text-[11px] text-bad">{String(res.error instanceof Error ? res.error.message : res.error)}</p>}
      {res.data && <ul className="mt-2 max-h-56 divide-y divide-line overflow-auto rounded-md border border-line">
        {res.data.length === 0 && <li className="px-2.5 py-2 text-[11px] text-muted">No match.</li>}
        {res.data.map((m) => (
          <li key={m.id}>
            <button onClick={() => onPick(m)} className={cn("flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:bg-subtle",
              picked?.id === m.id && "bg-accent-soft hover:bg-accent-soft")}>
              <span className="w-[74px] shrink-0 font-mono text-[11px]">{m.id}</span>
              <span className="min-w-0 flex-1 truncate text-[11.5px]">{m.formula} <span className="text-muted">{m.spacegroup}</span></span>
              <span className="shrink-0 text-[10.5px] text-muted">{m.nsites} at.</span>
              {m.stable ? <Tag tone="ok">stable</Tag>
                : <span className="w-[62px] shrink-0 text-right font-mono text-[10.5px] text-muted" title="energy above hull (eV/atom)">
                  +{m.e_above_hull_eV?.toFixed(3)}</span>}
            </button>
          </li>
        ))}
      </ul>}
    </div>
  );
}

/** Codes that are not usable here: one line pointing to the Software page, where everything is installed. */
function CodeInstaller() {
  const go = useGo();
  const cfg = useQuery({ queryKey: ["dft-config"], queryFn: dft.config });
  const missing = (cfg.data?.codes ?? []).filter((c) => !c.available);
  if (!missing.length) return null;
  return (
    <p className="mt-2 text-[11.5px] leading-4 text-muted">
      {missing.length} more program{missing.length > 1 ? "s" : ""} ({missing.map((c) => c.label).join(", ")}) not set up on this computer.{" "}
      <button className="text-accent hover:underline" onClick={() => go("software")}>Set up in Software →</button></p>
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
              <span className="ml-auto">{j.passed ? <Tag tone="ok">{j.n_passed ?? j.n_checks} checks passed</Tag> : <Tag tone="bad">{j.n_failed} failed</Tag>}</span>
            </div>
            <div className="mt-0.5 flex gap-3 text-[11px] text-muted"><span className="font-mono">{j.structure.split("/").pop()}</span><span>{clock(j.created)}</span></div>
          </button>
        </li>
      ))}
    </ul>
  );
}

function JobWorkspace({ id, study, onClose }: { id: string; study?: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ["dft-job", id], queryFn: () => dft.job(id),
    refetchInterval: (query) => livePollInterval(query.state.data) ||
      (studiesLive(query.state.data) ? 3000 : false) });
  if (q.isError) return <Empty title="Could not load this input set">{String(q.error)}</Empty>;
  if (!q.data) return <Empty title="Loading…" />;
  const job = q.data;
  const p = job.provenance;
  const failed = job.checks.results.filter((r) => r.ok === false).length;
  const done = job.checks.results.filter((r) => r.ok === true).length;
  const notRun = job.checks.results.filter((r) => r.ok === null).length;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-line bg-surface">
        <div className="flex items-center gap-3 px-5 pb-2 pt-3">
          <h1 className="text-[15px] font-semibold">{p.cell.formula} <span className="font-normal text-muted">· {p.request.functional} ground state · k {p.request.kmesh.join("×")}</span></h1>
          {job.checks.passed ? <Tag tone="ok" title={notRun ? `${notRun} could not run here (see Checks)` : undefined}>
            <CheckCircle2 size={11} /> {done} sanity checks passed{notRun ? ` · ${notRun} not run` : ""}</Tag>
            : <Tag tone="bad"><XCircle size={11} /> {failed} of {job.checks.results.length} checks failed</Tag>}
          <a href={dft.archiveUrl(id)} className="ml-auto"><Button size="sm" variant="secondary"><Download size={13} /> Download set (.zip)</Button></a>
          <button onClick={onClose} title="Close and go back to the start page" aria-label="Close"
            className="rounded p-1 text-muted hover:bg-subtle hover:text-ink"><X size={15} /></button>
        </div>
        <div className="grid grid-cols-4 border-t border-line">
          <Cellv label="Space group" value={p.cell.spacegroup} />
          <Cellv label="Atoms in primitive cell" value={String(p.cell.natoms)} />
          <Cellv label="Volume per atom" value={`${num(p.cell.volume_per_atom_A3)} Å³`} mono />
          <Cellv label="Nearest neighbour" value={`${num(p.cell.nearest_neighbour_A)} Å`} mono />
        </div>
      </div>
      <Sections key={id} initial={study} sections={[
        { key: "overview", label: "Overview", icon: LayoutDashboard, body: <DftOverview job={job} /> },
        { key: "structure", label: "Structure & plan", icon: Atom, body: <StructurePane job={job} /> },
        { key: "checks", label: "Checks", icon: ShieldCheck, body: <ChecksPane job={job} />,
          badge: <Dot tone={job.checks.passed ? "ok" : "bad"} /> },
        { key: "inputs", label: "Inputs", icon: FileCode, body: <InputsPane job={job} /> },
        { key: "runs", label: "Runs", icon: Play, body: <RunsPane job={job} />,
          badge: Object.values(job.runs ?? {}).some(runIsLive) ? <Dot tone="run" /> : undefined },
        { key: "convergence", label: "Convergence", icon: TrendingDown, body: <ConvergencePane job={job} />,
          badge: studyDot(job.studies?.convergence?.status) },
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

function PlanBlock({ job }: { job: DftJob }) {
  const plan = job.plan;
  if (!plan) return null;
  const tone = { user: "neutral", rule: "neutral", agent: "run", materials_project: "ok" } as const;
  return (
    <div>
      <div className="mb-1 flex items-center gap-2 font-medium text-ink-2">Plan
        <Tag tone={plan.planner === "agent" ? "run" : "neutral"}>{plan.planner === "agent" ? "planned with Claude" : "rule-based planner"}</Tag></div>
      {plan.goal && <p className="mb-1 text-muted">Goal: {plan.goal}</p>}
      <table className="w-full">
        <tbody className="divide-y divide-line">
          {plan.decisions.map((d, i) => (
            <tr key={i} className="align-top"><td className="w-24 py-1 text-muted">{d.field}</td>
              <td className="py-1"><span className="font-mono">{d.value}</span> <Tag tone={tone[d.source]}>{d.source.replace("_", " ")}</Tag>
                <div className="text-[11px] text-muted">{d.reason}</div></td></tr>
          ))}
        </tbody>
      </table>
      {plan.warnings.map((w) => <p key={w} className="mt-1 rounded bg-warn-soft px-2 py-1 text-warn">{w}</p>)}
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
      <PlanBlock job={job} />
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

function studiesLive(job?: DftJob) {
  const st = job?.studies;
  const all = [st?.convergence?.status];
  return all.some((x) => x === "running" || x === "queued");
}

function studyDot(status?: string) {
  if (!status) return undefined;
  return <Dot tone={status === "done" ? "ok" : status === "failed" ? "bad" : "run"} />;
}

function DftOverview({ job }: { job: DftJob }) {
  const p = job.provenance;
  const failed = job.checks.results.filter((r) => r.ok === false).length;
  return (
    <div className="grid h-full gap-4 overflow-auto p-4 text-[13px] md:grid-cols-2">
      <div className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-faint">Plan</h3>
        <ul className="space-y-1.5">{(job.plan?.decisions ?? []).map((d, i) => (
          <li key={i}><span className="text-muted">{d.field}</span> <span className="font-mono">{d.value}</span>
            <div className="text-[11.5px] text-faint">{d.reason}</div></li>))}
          {!job.plan && <li className="text-muted">Set made from explicit settings: {p.request.functional}, k {p.request.kmesh.join("×")}.</li>}
        </ul>
        {job.plan?.warnings.map((w) => <p key={w} className="rounded bg-warn-soft px-2 py-1 text-[12px] text-warn">{w}</p>)}
      </div>
      <div className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-faint">Checks</h3>
        <p>{failed ? <Tag tone="bad">{failed} failed</Tag> : <Tag tone="ok">all passed</Tag>} <span className="text-muted">
          {job.checks.results.filter((r) => r.ok === true).length} checks passed
          {job.checks.results.some((r) => r.ok === null) && `, ${job.checks.results.filter((r) => r.ok === null).length} not run`} across{" "}
          {Object.keys(p.generated).length} codes: each input read back as its code reads it.</span></p>
        <h3 className="pt-2 text-xs font-semibold uppercase tracking-wider text-faint">Runs</h3>
        <table className="tabular w-full text-[12.5px]"><tbody className="divide-y divide-line">
          {Object.entries(p.generated).map(([code, g]) => {
            const r = job.runs?.[code]; const res = r?.results;
            return <tr key={code}><td className="py-1 font-medium">{g.label}</td>
              <td>{r ? <Status status={r.status === "completed" ? "done" : r.status === "waiting" ? "queued" : r.status} /> : <span className="text-faint">not run</span>}</td>
              <td className="font-mono">{res?.gap_eV != null ? `${res.gap_eV.toFixed(3)} eV` : ""}</td>
              <td className="text-muted">{res ? (res.converged ? "converged" : "not converged") : ""}</td></tr>;
          })}
        </tbody></table>
        <h3 className="pt-2 text-xs font-semibold uppercase tracking-wider text-faint">Studies</h3>
        <p className="text-muted">Convergence: {job.studies?.convergence?.status ?? "not run"}</p>
      </div>
    </div>
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
