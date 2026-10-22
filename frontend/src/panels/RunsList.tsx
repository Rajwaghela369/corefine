import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { Empty, Status, clock, cn, fixed } from "../components/ui";

export function RunsList({ selected, onSelect }: { selected: string | null; onSelect: (id: string) => void }) {
  const runs = useQuery({
    queryKey: ["runs"], queryFn: api.runs,
    refetchInterval: (q) => (q.state.data?.some((r) => !["done", "failed"].includes(r.status)) ? 3000 : false),
  });
  if (runs.data?.length === 0) return <Empty title="No analyses yet">Start one above; it will be listed here.</Empty>;
  return (
    <ul className="divide-y divide-line">
      {runs.data?.map((r) => (
        <li key={r.id}>
          <button onClick={() => onSelect(r.id)}
            className={cn("w-full px-4 py-2.5 text-left hover:bg-subtle", selected === r.id && "bg-accent-soft hover:bg-accent-soft")}>
            <div className="flex items-center gap-2">
              <span className="font-mono text-[11.5px] font-medium">{r.id}</span>
              {r.engine && r.engine !== "agents" && <span className="rounded bg-subtle px-1 text-[10.5px] text-ink-2">{r.engine === "gsas2" ? "GSAS-II" : "MAUD"}</span>}
              {r.group_id && <span className="text-[10.5px] text-muted" title={r.group_id}>compared</span>}
              <span className="ml-auto"><Status status={r.status} /></span>
            </div>
            <p className="mt-0.5 line-clamp-1 text-xs text-ink-2">{r.prompt}</p>
            <div className="mt-1 flex items-center gap-3 text-[11px] text-muted">
              <span>{clock(r.started_at)}</span>
              {r.headline && <span className="tabular font-mono text-ink-2">a = {fixed(r.headline.a_refined)} Å</span>}
              {r.parent_run_id && <span>follow-up of <span className="font-mono">{r.parent_run_id}</span></span>}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}
