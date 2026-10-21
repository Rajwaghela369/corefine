import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, CornerDownLeft, Plus, ShieldAlert, ShieldCheck, X } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { api, chatStream, type ChatMessage, type ClaimCheck, type ProposedRun } from "../api/client";
import { Button, PanelHeader, Status, Tag, cn } from "../components/ui";
import { useRunEvents } from "../useRunEvents";

const EXAMPLE = "Refine silicon's lattice parameter from the 640f scan and compare it with the certified value.";

export function ChatPanel({ session, datasets, onRunStarted, selectedRun, onToggleDataset, history: historySlot }:
  { session: string; datasets: string[]; onRunStarted: (id: string) => void; selectedRun: string | null;
    onToggleDataset: (id: string) => void; history: ReactNode }) {
  // History loads once; everything after that is appended locally (answers keep their claim badge)
  const history = useQuery({ queryKey: ["chat", session], queryFn: () => api.chatHistory(session), staleTime: Infinity });
  const [local, setLocal] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runIds, setRunIds] = useState<string[]>([]);
  const [view, setView] = useState<"activity" | "history">("history");
  const [picking, setPicking] = useState(false);
  const all = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const available = (all.data ?? []).filter((d) => d.valid && !datasets.includes(d.id));
  const end = useRef<HTMLDivElement>(null);
  const qc = useQueryClient();
  const shown: ChatMessage[] = [...(history.data ?? []), ...local];

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [history.data, local, runIds]);

  async function ask() {
    const message = text.trim();
    if (!message) return;
    setText(""); setBusy(true); setError(null); setView("activity");
    setLocal((l) => [...l, { role: "user", content: message }, { role: "assistant", content: "", tools: [] }]);
    try {
      for await (const ev of chatStream(session, message, datasets)) {
        if (ev.event === "tool_call") setLocal((l) => patchLast(l, (m) => ({ ...m, tools: [...(m.tools ?? []), ev.data.name] })));
        if (ev.event === "answer") setLocal((l) => patchLast(l, (m) => ({ ...m, content: ev.data.content,
          claim_check: ev.data.claim_check, proposed_run: ev.data.proposed_run })));
        if (ev.event === "error") throw new Error(ev.data.message);
      }
    } catch (e) {
      setLocal((l) => (l.at(-1)?.content === "" ? l.slice(0, -1) : l));
      setError(friendly(e));
    } finally { setBusy(false); }
  }

  async function start(p: ProposedRun) {
    setError(null);
    try {
      const { id } = await api.startRun({ ...p, session_id: session });
      setRunIds((r) => [...r, id]);
      setView("activity");
      onRunStarted(id);
      qc.invalidateQueries({ queryKey: ["runs"] });
    } catch (e) { setError(friendly(e)); }
  }

  const onSummary = (content: string, run_id: string) => setLocal((l) => [...l, { role: "assistant", content, run_id }]);
  const canRun = !!text.trim() && datasets.length > 0;

  return (
    <div className="flex h-full flex-col bg-surface">
      <PanelHeader title="New analysis" />
      <div className="border-b border-line p-4">
        <div className="mb-2 flex min-h-6 flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-medium text-muted">Inputs</span>
          {datasets.map((d) => (
            <span key={d} className="inline-flex items-center gap-1 rounded border border-line bg-subtle py-px pl-1.5 pr-0.5 font-mono text-[11px] text-ink-2">
              {d}<button onClick={() => onToggleDataset(d)} className="rounded p-0.5 text-faint hover:text-ink" aria-label={`Remove ${d}`}><X size={10} /></button>
            </span>
          ))}
          <div className="relative">
            <button onClick={() => setPicking((v) => !v)} disabled={!available.length}
              className="inline-flex items-center gap-0.5 rounded border border-dashed border-line-strong px-1.5 py-px text-[11px] text-muted hover:border-accent hover:text-accent disabled:opacity-40">
              <Plus size={10} /> {datasets.length ? "Add" : "Select datasets"}</button>
            {picking && available.length > 0 && (
              <div className="absolute left-0 top-6 z-30 w-64 rounded-md border border-line bg-surface p-1 shadow-lg" onMouseLeave={() => setPicking(false)}>
                {available.map((d) => (
                  <button key={d.id} onClick={() => { onToggleDataset(d.id); setPicking(false); }}
                    className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left hover:bg-subtle">
                    <span className="font-mono text-[11.5px]">{d.id}</span>
                    <span className="text-[10.5px] text-muted">{d.role?.replace("_", " ")}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="rounded-md border border-line-strong focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/15">
          <textarea className="block h-24 w-full resize-none rounded-t-md bg-transparent p-2.5 text-[13px] leading-5 outline-none placeholder:text-faint"
            value={text} placeholder={`Describe the analysis, e.g. “${EXAMPLE}”`}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canRun) { e.preventDefault(); start({ prompt: text.trim(), dataset_ids: datasets, parent_run_id: null }); setText(""); }
            }} />
          <div className="flex items-center justify-between border-t border-line px-2 py-1.5">
            <button className="text-[11px] text-muted hover:text-ink" onClick={() => setText(EXAMPLE)}>Use example</button>
            <div className="flex gap-1.5">
              <Button size="sm" variant="ghost" disabled={busy || !text.trim()} onClick={ask}
                title="Discuss with the assistant without starting a run">{busy ? "Answering…" : "Ask assistant"}</Button>
              <Button size="sm" variant="primary" disabled={!canRun}
                title={datasets.length ? "Start the analysis (Ctrl+Enter)" : "Select at least one dataset first"}
                onClick={() => { start({ prompt: text.trim(), dataset_ids: datasets, parent_run_id: null }); setText(""); }}>
                Start analysis <CornerDownLeft size={12} className="opacity-70" />
              </Button>
            </div>
          </div>
        </div>
        {error && <p className="mt-2 rounded-md border border-bad/20 bg-bad-soft px-2.5 py-2 text-xs text-bad">{error}</p>}
      </div>

      <div className="flex h-9 shrink-0 items-center gap-4 border-b border-line px-4">
        {(["history", "activity"] as const).map((v) => (
          <button key={v} onClick={() => setView(v)} className={cn("-mb-px h-9 border-b-2 text-xs",
            view === v ? "border-accent font-medium text-ink" : "border-transparent text-muted hover:text-ink")}>
            {v === "history" ? "Run history" : "Activity"}</button>
        ))}
      </div>
      <div className={cn("min-h-0 flex-1 overflow-auto", view !== "history" && "hidden")}>{historySlot}</div>
      <div className={cn("min-h-0 flex-1 overflow-auto", view !== "activity" && "hidden")}>
        {shown.length === 0 && runIds.length === 0 && (
          <div className="px-4 py-6 text-xs leading-5 text-muted">
            Started analyses and assistant answers appear here. Every number the assistant states is checked against
            run outputs before it is shown.
          </div>
        )}
        <ol className="divide-y divide-line">
          {shown.map((m, i) => <Entry key={i} m={m} onConfirm={start} datasets={datasets} />)}
          {runIds.map((id) => <RunEntry key={id} id={id} session={session} selected={selectedRun === id}
            onOpen={() => onRunStarted(id)} onSummary={onSummary} />)}
        </ol>
        <div ref={end} />
      </div>
    </div>
  );
}

function friendly(e: unknown): string {
  const m = e instanceof Error ? e.message : String(e);
  if (/api[_ ]key|authentication|x-api-key|ANTHROPIC/i.test(m)) return "The assistant is not configured yet (no Anthropic API key on the server).";
  return m;
}

function patchLast(l: ChatMessage[], f: (m: ChatMessage) => ChatMessage) {
  return [...l.slice(0, -1), f(l[l.length - 1])];
}

export function ClaimBadge({ c }: { c: ClaimCheck | null | undefined }) {
  if (!c) return null;
  return c.passed
    ? <Tag tone="ok" title="Every decimal number matches a value in the run's output files or manifests"><ShieldCheck size={11} /> {c.checked} values verified</Tag>
    : <Tag tone="bad" title={c.untraced.map((u) => u.context).join("\n")}><ShieldAlert size={11} /> {c.untraced.length} unverified: {c.untraced.map((u) => u.number).join(", ")}</Tag>;
}

function Entry({ m, onConfirm, datasets }: { m: ChatMessage; onConfirm: (p: ProposedRun) => void; datasets: string[] }) {
  const user = m.role === "user";
  return (
    <li className="px-4 py-3">
      <div className="mb-1 flex items-center gap-2">
        <span className={cn("text-[11px] font-semibold", user ? "text-ink" : "text-accent")}>{user ? "You" : "Assistant"}</span>
        {m.run_id && <span className="font-mono text-[11px] text-muted">re {m.run_id}</span>}
        {!!m.tools?.length && <span className="text-[11px] text-faint">consulted {[...new Set(m.tools)].join(", ").replaceAll("_", " ")}</span>}
      </div>
      {m.content
        ? <div className={cn("doc", user && "[&_p]:text-ink")}><Markdown>{m.content}</Markdown></div>
        : <div className="h-4 w-24 animate-pulse rounded bg-subtle" />}
      {m.claim_check && <div className="mt-1.5"><ClaimBadge c={m.claim_check} /></div>}
      {m.proposed_run && (
        <div className="mt-2 rounded-md border border-line bg-subtle p-3">
          <div className="text-[11px] font-medium uppercase tracking-wider text-muted">
            Proposed analysis{m.proposed_run.parent_run_id ? ` · follow-up to ${m.proposed_run.parent_run_id}` : ""}</div>
          <p className="my-1.5 text-[13px]">{m.proposed_run.prompt}</p>
          <div className="flex items-center justify-between">
            <span className="font-mono text-[11px] text-muted">{(m.proposed_run.dataset_ids.length ? m.proposed_run.dataset_ids : datasets).join(", ")}</span>
            <Button size="sm" variant="primary" onClick={() => onConfirm({ ...m.proposed_run!,
              dataset_ids: m.proposed_run!.dataset_ids.length ? m.proposed_run!.dataset_ids : datasets })}>Confirm and start</Button>
          </div>
        </div>
      )}
    </li>
  );
}

const SEG: Record<string, string> = { pending: "bg-line", running: "bg-run", retrying: "bg-warn", done: "bg-ok", failed: "bg-bad" };

function RunEntry({ id, session, selected, onOpen, onSummary }: { id: string; session: string; selected: boolean;
  onOpen: () => void; onSummary: (content: string, runId: string) => void }) {
  const run = useQuery({ queryKey: ["run", id], queryFn: () => api.run(id) });
  useRunEvents(id, (ev) => { if (ev.type === "chat_message" && ev.session_id === session) onSummary(ev.content, id); });
  const r = run.data;
  return (
    <li className={cn("px-4 py-3", selected && "bg-accent-soft/50")}>
      <button onClick={onOpen} className="group w-full text-left">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold text-ink">Analysis started</span>
          <span className="font-mono text-[11px] text-muted">{id}</span>
          <ArrowUpRight size={12} className="text-faint group-hover:text-accent" />
          <span className="ml-auto"><Status status={r?.status ?? "queued"} /></span>
        </div>
        {r?.prompt && <p className="mt-1 line-clamp-2 text-xs text-ink-2">{r.prompt}</p>}
        {!!r?.steps.length && (
          <div className="mt-2 flex gap-0.5">
            {r.steps.map((s) => <span key={s.idx} title={`${s.idx}. ${s.name}: ${s.status}`} className={cn("h-1 flex-1 rounded-full", SEG[s.status])} />)}
          </div>
        )}
      </button>
    </li>
  );
}
