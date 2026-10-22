import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, Search } from "lucide-react";
import { type MouseEvent, useState } from "react";
import { api, type RunListItem } from "../api/client";
import { friendlyError, runTitle } from "../components/labels";
import { useDetailed } from "../components/prefs";
import { Empty, Status, clock, cn, fixed, inputCls } from "../components/ui";

type Filter = "all" | "done" | "failed" | "archived";
const ENGINE: Record<string, string> = { gsas2: "GSAS-II", maud: "MAUD" };

export function useRuns() {
  return useQuery({
    queryKey: ["runs"], queryFn: api.runs,
    refetchInterval: (q) => (q.state.data?.some((r) => !["done", "failed"].includes(r.status)) ? 3000 : false),
  });
}

/** Every analysis, newest first. Archived runs are hidden unless asked for; nothing is ever deleted. */
export function RunsList({ selected, onSelect, searchable }: { selected: string | null; onSelect: (id: string) => void; searchable?: boolean }) {
  const runs = useRuns();
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const all = runs.data ?? [];
  const archivedCount = all.filter((r) => r.archived).length;
  const shown = all.filter((r) => (filter === "archived" ? r.archived : !r.archived))
    .filter((r) => filter === "done" ? r.status === "done" : filter === "failed" ? r.status === "failed" : true)
    .filter((r) => !q.trim() || `${runTitle(r)} ${r.prompt} ${r.id} ${r.dataset_ids.join(" ")}`.toLowerCase().includes(q.trim().toLowerCase()));
  const tabs: [Filter, string][] = [["all", "All"], ["done", "Completed"], ["failed", "Failed"],
    ...(archivedCount ? [["archived", `Archived (${archivedCount})`] as [Filter, string]] : [])];

  if (runs.data && all.length === 0) return <Empty title="No analyses yet">Start one and it will be listed here.</Empty>;
  return (
    <div>
      <div className="sticky top-0 z-10 space-y-2 border-b border-line bg-surface px-4 py-2">
        {searchable && <div className="relative">
          <Search size={13} className="absolute left-2.5 top-2.5 text-faint" />
          <input className={cn(inputCls, "pl-7")} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by title, question or dataset" />
        </div>}
        <div className="flex flex-wrap gap-1">
          {tabs.map(([f, label]) => (
            <button key={f} onClick={() => setFilter(f)} className={cn("rounded-full px-2.5 py-0.5 text-[11.5px]",
              filter === f ? "bg-ink text-white" : "text-muted hover:bg-subtle hover:text-ink")}>{label}</button>
          ))}
        </div>
      </div>
      {shown.length === 0 ? <p className="px-4 py-6 text-xs text-muted">Nothing here.</p> : (
        <ul className="divide-y divide-line">
          {shown.map((r) => <RunItem key={r.id} r={r} selected={selected === r.id} onSelect={() => onSelect(r.id)} />)}
        </ul>
      )}
    </div>
  );
}

function RunItem({ r, selected, onSelect }: { r: RunListItem; selected: boolean; onSelect: () => void }) {
  const detailed = useDetailed();
  const qc = useQueryClient();
  const archive = async (e: MouseEvent) => {
    e.stopPropagation();
    await api.archiveRun(r.id, !r.archived);
    qc.invalidateQueries({ queryKey: ["runs"] });
  };
  return (
    <li className="group relative">
      <button onClick={onSelect}
        className={cn("w-full px-4 py-2.5 pr-10 text-left hover:bg-subtle", selected && "bg-accent-soft hover:bg-accent-soft")}>
        <div className="flex items-start gap-2">
          <span className="line-clamp-2 text-[12.5px] font-medium leading-5 text-ink">{runTitle(r)}</span>
          <span className="ml-auto shrink-0 pt-0.5"><Status status={r.status} /></span>
        </div>
        {r.status === "failed" && <p className="mt-0.5 line-clamp-1 text-[11.5px] text-bad">{friendlyError(r.error).title}</p>}
        {r.headline && <p className="tabular mt-0.5 text-[11.5px] text-ink-2">a = <span className="font-mono">{fixed(r.headline.a_refined)} Å</span></p>}
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-muted">
          <span>{clock(r.started_at)}</span>
          {r.engine && ENGINE[r.engine] && <span>{ENGINE[r.engine]}</span>}
          {r.group_id && <span>engines compared</span>}
          {r.parent_run_id && <span>follow-up</span>}
          {detailed && <span className="font-mono">{r.id}</span>}
        </div>
      </button>
      <button onClick={archive} title={r.archived ? "Restore to the list" : "Archive (hide from the list; nothing is deleted)"}
        aria-label={r.archived ? "Restore" : "Archive"}
        className="absolute right-2 top-2.5 rounded p-1 text-faint opacity-0 hover:bg-line hover:text-ink focus:opacity-100 group-hover:opacity-100">
        {r.archived ? <ArchiveRestore size={14} /> : <Archive size={14} />}
      </button>
    </li>
  );
}
