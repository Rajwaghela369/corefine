import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { Badge, STATUS_TONE, cn, fmt } from "../components/ui";

export function RunsList({ selected, onSelect }: { selected: string | null; onSelect: (id: string) => void }) {
  const runs = useQuery({
    queryKey: ["runs"], queryFn: api.runs,
    refetchInterval: (q) => (q.state.data?.some((r) => !["done", "failed"].includes(r.status)) ? 3000 : false),
  });
  return (
    <div className="max-h-48 overflow-auto border-b border-line">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-panel text-left text-muted">
          <tr><th className="px-3 py-1.5 font-medium">Run</th><th className="font-medium">Status</th>
            <th className="font-medium">Refined a (Å)</th><th className="font-medium">Parent</th></tr>
        </thead>
        <tbody>
          {runs.data?.map((r) => (
            <tr key={r.id} onClick={() => onSelect(r.id)}
              className={cn("cursor-pointer border-t border-line hover:bg-panel", selected === r.id && "bg-sky-50")}>
              <td className="px-3 py-1.5 font-mono" title={r.prompt}>{r.id}</td>
              <td><Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge></td>
              <td className="font-mono">{r.headline ? `${fmt(r.headline.a_refined)} ± ${fmt(r.headline.uncertainty)}` : "—"}</td>
              <td className="font-mono text-muted">{r.parent_run_id ?? ""}</td>
            </tr>
          ))}
          {runs.data?.length === 0 && <tr><td colSpan={4} className="px-3 py-3 text-muted">No runs yet.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
