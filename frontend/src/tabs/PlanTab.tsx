import { Background, type Edge, type Node, ReactFlow } from "@xyflow/react";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, type RunDetail } from "../api/client";
import { Badge, STATUS_TONE, STEP_COLOURS } from "../components/ui";

export function PlanTab({ run }: { run: RunDetail }) {
  const [sel, setSel] = useState<number | null>(null);
  const steps = run.plan?.steps ?? [];
  const status = new Map(run.steps.map((s) => [s.idx, s]));
  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = steps.map((s, i) => {
      const st = status.get(s.idx);
      return {
        id: String(s.idx), position: { x: 0, y: i * 110 }, draggable: false,
        data: { label: <div className="text-left"><div className="text-xs font-semibold">{s.idx}. {s.name}</div>
          <div className="text-[10px] text-gray-600">{st?.status ?? "pending"}{st && st.attempts > 1 ? ` · attempt ${st.attempts}` : ""}</div></div> },
        style: { background: STEP_COLOURS[st?.status ?? "pending"], width: 260, borderRadius: 8, border: "1px solid #d1d5db" },
      };
    });
    const edges: Edge[] = steps.slice(1).map((s, i) => ({ id: `e${i}`, source: String(steps[i].idx), target: String(s.idx) }));
    return { nodes, edges };
  }, [run]);

  if (!run.plan) return <p className="p-4 text-sm text-muted">{run.status === "failed" ? run.error : "Planning…"}</p>;
  const step = steps.find((s) => s.idx === sel);
  const st = sel != null ? status.get(sel) : undefined;
  return (
    <div className="flex h-full min-h-0">
      <div className="h-full min-w-0 flex-1">
        <div className="border-b border-line p-3 text-sm"><b>{run.plan.title}</b> — {run.plan.summary}</div>
        <div className="h-[calc(100%-3rem)]">
          <ReactFlow nodes={nodes} edges={edges} fitView fitViewOptions={{ maxZoom: 1 }} nodesConnectable={false} elementsSelectable
            onNodeClick={(_, n) => setSel(Number(n.id))} proOptions={{ hideAttribution: true }}>
            <Background gap={16} />
          </ReactFlow>
        </div>
      </div>
      {step && (
        <aside className="w-1/2 overflow-auto border-l border-line p-3 text-xs">
          <div className="mb-2 flex items-center gap-2"><b className="text-sm">{step.idx}. {step.name}</b>
            <Badge tone={STATUS_TONE[st?.status ?? "pending"]}>{st?.status}</Badge></div>
          <p className="mb-2">{step.goal}</p>
          <p className="text-muted">writes: {step.outputs.join(", ")} · skill: {step.skill}</p>
          {st?.error && <pre className="mt-2 whitespace-pre-wrap rounded bg-red-50 p-2 text-red-800">{st.error}</pre>}
          {st?.code_key && <FileView runId={run.id} path={st.code_key} title="code" />}
          {st?.stdout_key && <FileView runId={run.id} path={st.stdout_key} title="stdout" />}
          {st?.stdout_key && <FileView runId={run.id} path={st.stdout_key.replace(/\.stdout$/, ".stderr")} title="stderr" />}
        </aside>
      )}
    </div>
  );
}

function FileView({ runId, path, title }: { runId: string; path: string; title: string }) {
  const q = useQuery({ queryKey: ["file", runId, path], queryFn: () => api.artifactText(runId, path) });
  return (
    <details className="mt-2" open={title === "code"}>
      <summary className="cursor-pointer font-medium">{title} <span className="font-mono text-muted">{path}</span></summary>
      <pre className="mt-1 max-h-96 overflow-auto rounded bg-panel p-2 font-mono text-[11px]">{q.data || "(empty)"}</pre>
    </details>
  );
}
