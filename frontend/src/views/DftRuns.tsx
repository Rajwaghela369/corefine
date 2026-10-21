import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleDashed, Play, Upload, XCircle } from "lucide-react";
import { useRef, useState } from "react";
import { dft, type DftJob, type DftRun, type DftTarget } from "../api/client";
import { Button, Dialog, Status, cn, num } from "../components/ui";

const LIVE = ["queued", "staging", "submitted", "running"];
export const runIsLive = (r?: DftRun) => !!r && LIVE.includes(r.status);

const STATUS_MAP: Record<string, string> = { staging: "running", submitted: "queued", completed: "done", imported: "done" };

/** One row per code in the set: where to run it, live status, and the parsed results. */
export function RunsPane({ job }: { job: DftJob }) {
  const qc = useQueryClient();
  const targets = useQuery({ queryKey: ["dft-targets"], queryFn: dft.targets });
  const codes = Object.keys(job.provenance.generated);
  const [confirm, setConfirm] = useState<{ code: string; target: DftTarget } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: ({ code, target }: { code: string; target: string }) => dft.startRun(job.id, code, target),
    onSuccess: () => { setError(null); qc.invalidateQueries({ queryKey: ["dft-job", job.id] }); },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  });
  const run = (code: string, t: DftTarget) => (t.confirm ? setConfirm({ code, target: t }) : start.mutate({ code, target: t.name }));
  const anyTargets = (targets.data ?? []).length > 0;

  return (
    <div className="flex h-full flex-col">
      <ul className="min-h-0 flex-1 divide-y divide-line overflow-auto">
        {codes.map((code) => <Row key={code} job={job} code={code} targets={(targets.data ?? []).filter((t) => t.codes.includes(code))}
          onRun={(t) => run(code, t)} busy={start.isPending} />)}
      </ul>
      {error && <p className="m-3 rounded-md border border-bad/20 bg-bad-soft p-2 text-xs text-bad">{error}</p>}
      <div className="mt-auto border-t border-line px-3 py-2 text-[11px] leading-4 text-muted">
        {anyTargets ? "Targets come from your compute.yaml. " : "No compute targets configured: copy backend/compute.example.yaml to compute.yaml. "}
        Total energies of different codes use different reference energies and are not comparable; gaps and convergence are.
      </div>
      <Dialog title="Submit to a cluster?" open={!!confirm} onClose={() => setConfirm(null)}>
        {confirm && <div className="space-y-3 text-[13px]">
          <p>This copies the <b>{job.provenance.generated[confirm.code].label}</b> inputs to <span className="font-mono">{confirm.target.host}</span> and
            submits a Slurm job with your job-script template, using your account and allocation there.</p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirm(null)}>Cancel</Button>
            <Button variant="primary" onClick={() => { start.mutate({ code: confirm.code, target: confirm.target.name }); setConfirm(null); }}>Submit job</Button>
          </div>
        </div>}
      </Dialog>
    </div>
  );
}

function Row({ job, code, targets, onRun, busy }: { job: DftJob; code: string; targets: DftTarget[]; onRun: (t: DftTarget) => void; busy: boolean }) {
  const qc = useQueryClient();
  const g = job.provenance.generated[code];
  const r = job.runs?.[code];
  const res = r?.results;
  const [target, setTarget] = useState(targets[0]?.name ?? "");
  const chosen = targets.find((t) => t.name === (target || targets[0]?.name));
  const file = useRef<HTMLInputElement>(null);
  const imp = useMutation({
    mutationFn: (files: File[]) => dft.importResults(job.id, code, files),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dft-job", job.id] }),
  });
  const live = runIsLive(r);
  return (
    <li className="px-3 py-2.5">
      <div className="flex items-center gap-2">
        <div className="min-w-0">
          <span className="text-[12.5px] font-medium">{g.label}</span>
          <span className="ml-1.5 text-[11px] text-muted">{g.method}</span>
        </div>
        <div className="ml-auto flex items-center gap-1">
          {targets.length ? <select value={chosen?.name} onChange={(e) => setTarget(e.target.value)} disabled={live}
            className="h-7 rounded border border-line-strong bg-surface px-1.5 text-xs">{targets.map((t) =>
              <option key={t.name} value={t.name}>{t.name}{t.kind === "slurm" ? ` (${t.host})` : ""}</option>)}</select>
            : <span className="text-[11px] text-faint" title="Add a target for this code in compute.yaml">no compute target</span>}
          <Button size="sm" variant="secondary" disabled={!chosen || live || busy} onClick={() => chosen && onRun(chosen)}>
            <Play size={11} /> Run</Button>
          <Button size="sm" variant="ghost" title="Import output files of a run done elsewhere" onClick={() => file.current?.click()}>
            <Upload size={12} /></Button>
          <input ref={file} type="file" multiple hidden onChange={(e) => { const f = Array.from(e.target.files ?? []); if (f.length) imp.mutate(f); e.target.value = ""; }} />
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px]">
        {r ? <span className="inline-flex items-center gap-1.5"><Status status={STATUS_MAP[r.status] ?? r.status} />
          <span className="max-w-64 truncate text-muted" title={r.message}>{r.target === "imported" ? r.message : `on ${r.target}${r.message ? ` · ${r.message}` : ""}`}</span></span>
          : <span className="text-faint">not run yet</span>}
        {res && <>
          <span className={cn("inline-flex items-center gap-1", res.converged ? "text-ok" : res.converged === false ? "text-bad" : "text-muted")}>
            {res.converged ? <CheckCircle2 size={12} /> : res.converged === false ? <XCircle size={12} /> : <CircleDashed size={12} />}
            {res.converged ? "converged" : res.converged === false ? "not converged" : "convergence unknown"}
            {res.scf_iterations != null && ` · ${res.scf_iterations} SCF it.`}</span>
          <span className="tabular font-mono">gap {res.gap_eV != null ? `${res.gap_eV.toFixed(4)} eV` : "—"}</span>
          <span className="tabular font-mono text-muted" title="Not comparable across codes">E<sub>tot</sub> {res.total_energy_eV != null ? `${num(res.total_energy_eV, 10)} eV` : "—"}</span>
        </>}
      </div>
      {res?.warnings?.map((w) => <div key={w} className="mt-0.5 text-[10.5px] text-warn">{w}</div>)}
      {imp.isError && <div className="mt-1 text-[10.5px] text-bad">{String(imp.error instanceof Error ? imp.error.message : imp.error)}</div>}
    </li>
  );
}

export function livePollInterval(job?: DftJob) {
  return job && Object.values(job.runs ?? {}).some(runIsLive) ? 2000 : false;
}
