import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type Metric, type RunDetail } from "../api/client";
import { Badge, fmt } from "../components/ui";
import { ClaimBadge } from "../panels/ChatPanel";

const latest = (run: RunDetail, ext: string) =>
  run.artifacts.filter((a) => a.path.startsWith("outputs/") && a.path.endsWith(ext));

export function PlotsTab({ run }: { run: RunDetail }) {
  const pngs = latest(run, ".png");
  if (!pngs.length) return <p className="p-4 text-sm text-muted">No plots yet.</p>;
  return (
    <div className="space-y-4 p-4">
      {pngs.map((a) => (
        <figure key={a.path}>
          <a href={api.artifactUrl(run.id, a.path)} target="_blank" rel="noreferrer">
            <img src={api.artifactUrl(run.id, a.path)} alt={a.path} className="w-full rounded border border-line" />
          </a>
          <figcaption className="mt-1 font-mono text-[11px] text-muted">{a.path} · sha256 {a.sha256.slice(0, 12)}…</figcaption>
        </figure>
      ))}
    </div>
  );
}

type SortKey = keyof Pick<Metric, "name" | "source">;

export function DataTab({ run }: { run: RunDetail }) {
  const [sort, setSort] = useState<SortKey>("source");
  const rows = [...run.metrics].sort((a, b) => String(a[sort]).localeCompare(String(b[sort])));
  const csvs = latest(run, ".csv");
  return (
    <div className="space-y-4 p-4">
      <table className="w-full text-xs [&_td]:pr-3 [&_th]:pr-3">
        <thead className="text-left text-muted">
          <tr>{(["name", "value", "unit", "uncertainty", "source"] as const).map((h) => (
            <th key={h} className="cursor-pointer border-b border-line py-1 font-medium"
              onClick={() => (h === "name" || h === "source") && setSort(h)}>{h}</th>))}</tr>
        </thead>
        <tbody>
          {rows.map((m, i) => (
            <tr key={i} className="border-b border-line" title={m.method ?? ""}>
              <td className="py-1 font-mono">{m.name}</td>
              <td className="font-mono">{fmt(m.value as number | string, 7)}</td>
              <td>{m.unit ?? ""}</td>
              <td className="font-mono">{fmt(m.uncertainty)}</td>
              <td className="font-mono text-muted">{m.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {csvs.map((a) => <CsvPreview key={a.path} runId={run.id} path={a.path} />)}
    </div>
  );
}

function CsvPreview({ runId, path }: { runId: string; path: string }) {
  const q = useQuery({ queryKey: ["file", runId, path], queryFn: () => api.artifactText(runId, path) });
  const lines = (q.data ?? "").trim().split("\n").slice(0, 30).map((l) => l.split(","));
  return (
    <div>
      <div className="mb-1 flex items-center gap-2 text-xs font-medium">{path}
        <a href={api.artifactUrl(runId, path)} download className="text-accent"><Download size={12} /></a></div>
      <div className="overflow-auto rounded border border-line">
        <table className="text-[11px]">
          <tbody>{lines.map((cells, i) => (
            <tr key={i} className={i === 0 ? "bg-panel font-medium" : "border-t border-line"}>
              {cells.map((c, j) => <td key={j} className="whitespace-nowrap px-2 py-0.5 font-mono">{c}</td>)}</tr>))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const CLASS_TONE: Record<string, "good" | "warn" | "bad" | "info"> = {
  agreement: "good", missing_geometric_correction: "warn", metadata_issue: "warn",
  weak_or_overlapping_peaks: "warn", unexplained: "bad",
};

export function ReportTab({ run }: { run: RunDetail }) {
  const has = run.artifacts.some((a) => a.path === "report.md");
  const q = useQuery({ queryKey: ["file", run.id, "report.md", run.status], queryFn: () => api.artifactText(run.id, "report.md"),
    enabled: has });
  if (!has) return <p className="p-4 text-sm text-muted">{run.status === "failed" ? `Run failed: ${run.error}` : "No report yet."}</p>;
  return (
    <div className="p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {run.classification && <Badge tone={CLASS_TONE[run.classification] ?? "info"}>{run.classification.replaceAll("_", " ")}</Badge>}
        <ClaimBadge c={run.claim_check} />
        <a href={api.artifactUrl(run.id, "report.md")} download className="ml-auto text-xs text-accent">download</a>
      </div>
      <article className="prose-report"><Markdown remarkPlugins={[remarkGfm]}>{q.data ?? ""}</Markdown></article>
    </div>
  );
}
