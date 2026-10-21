import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Send, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { api, chatStream, type ChatMessage, type ClaimCheck, type ProposedRun } from "../api/client";
import { Badge, Button, STATUS_TONE, Section } from "../components/ui";
import { useRunEvents } from "../useRunEvents";

export function ChatPanel({ session, datasets, onRunStarted, selectedRun }:
  { session: string; datasets: string[]; onRunStarted: (id: string) => void; selectedRun: string | null }) {
  // History loads once; everything after that is appended locally (answers keep their claim badge)
  const history = useQuery({ queryKey: ["chat", session], queryFn: () => api.chatHistory(session), staleTime: Infinity });
  const [local, setLocal] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runIds, setRunIds] = useState<string[]>([]);
  const end = useRef<HTMLDivElement>(null);
  const qc = useQueryClient();

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [history.data, local]);

  async function send() {
    const message = text.trim();
    if (!message) return;
    setText(""); setBusy(true); setError(null);
    setLocal((l) => [...l, { role: "user", content: message }, { role: "assistant", content: "", tools: [] }]);
    try {
      for await (const ev of chatStream(session, message, datasets)) {
        if (ev.event === "tool_call") setLocal((l) => patchLast(l, (m) => ({ ...m, tools: [...(m.tools ?? []), ev.data.name] })));
        if (ev.event === "answer") setLocal((l) => patchLast(l, (m) => ({ ...m, content: ev.data.content,
          claim_check: ev.data.claim_check, proposed_run: ev.data.proposed_run })));
        if (ev.event === "error") throw new Error(ev.data.message);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  async function runNow(p: ProposedRun) {
    setError(null);
    try {
      const { id } = await api.startRun({ ...p, session_id: session });
      setRunIds((r) => [...r, id]);
      onRunStarted(id);
      qc.invalidateQueries({ queryKey: ["runs"] });
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }

  const shown: ChatMessage[] = [...(history.data ?? []), ...local];
  const onSummary = (content: string, run_id: string) => setLocal((l) => [...l, { role: "assistant", content, run_id }]);

  return (
    <Section title="Conversation" className="h-full">
      <div className="space-y-3 p-3">
        {shown.length === 0 && (
          <div className="rounded-lg border border-dashed border-line p-4 text-sm text-muted">
            Tick the datasets to use on the left, then describe the experiment, for example:
            <em className="mt-1 block text-ink">“Refine silicon's lattice parameter from the 640f scan and compare it with the certified value.”</em>
            Use <b>Run</b> to start it directly, or <b>Ask</b> to talk it through with the co-pilot first.
          </div>
        )}
        {shown.map((m, i) => <Bubble key={i} m={m} onConfirm={runNow} datasets={datasets} />)}
        {runIds.map((id) => <RunCard key={id} id={id} session={session} selected={selectedRun === id}
          onOpen={() => onRunStarted(id)} onSummary={onSummary} />)}
        {error && <p className="rounded bg-red-50 p-2 text-sm text-red-700">{error}</p>}
        <div ref={end} />
      </div>
      <div className="sticky bottom-0 border-t border-line bg-white p-3">
        <textarea className="h-20 w-full resize-none rounded-md border border-line p-2 text-sm" value={text}
          placeholder={datasets.length ? `Datasets: ${datasets.join(", ")}` : "Select datasets on the left first"}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
        <div className="mt-2 flex justify-end gap-2">
          <Button variant="outline" disabled={busy || !text.trim() || !datasets.length}
            title="Start a run with this prompt and the selected datasets"
            onClick={() => { const p = text.trim(); setText(""); runNow({ prompt: p, dataset_ids: datasets, parent_run_id: null }); }}>
            <Play size={14} /> Run
          </Button>
          <Button disabled={busy || !text.trim()} onClick={send}><Send size={14} /> {busy ? "Thinking…" : "Ask"}</Button>
        </div>
      </div>
    </Section>
  );
}

function patchLast(l: ChatMessage[], f: (m: ChatMessage) => ChatMessage) {
  return [...l.slice(0, -1), f(l[l.length - 1])];
}

export function ClaimBadge({ c }: { c: ClaimCheck | null | undefined }) {
  if (!c) return null;
  return c.passed ? <Badge tone="good">all {c.checked} numbers traced</Badge>
    : <Badge tone="bad" className="whitespace-normal">untraced: {c.untraced.map((u) => u.number).join(", ")}</Badge>;
}

function Bubble({ m, onConfirm, datasets }: { m: ChatMessage; onConfirm: (p: ProposedRun) => void; datasets: string[] }) {
  if (m.role === "user") return <div className="ml-8 rounded-lg bg-ink px-3 py-2 text-sm text-white">{m.content}</div>;
  return (
    <div className="mr-8 space-y-1.5 rounded-lg border border-line bg-panel px-3 py-2 text-sm">
      {!!m.tools?.length && <div className="flex flex-wrap gap-1">{m.tools.map((t, i) =>
        <Badge key={i}><Wrench size={10} className="mr-1" />{t}</Badge>)}</div>}
      {m.content ? <div className="prose-report"><Markdown>{m.content}</Markdown></div>
        : <span className="text-muted">…</span>}
      {m.run_id && <Badge tone="info">about {m.run_id}</Badge>}
      <ClaimBadge c={m.claim_check} />
      {m.proposed_run && (
        <div className="rounded border border-sky-200 bg-white p-2 text-xs">
          <p className="font-medium">Proposed run{m.proposed_run.parent_run_id ? ` (follow-up of ${m.proposed_run.parent_run_id})` : ""}</p>
          <p className="my-1 text-muted">{m.proposed_run.prompt}</p>
          <p className="mb-2 text-muted">datasets: {(m.proposed_run.dataset_ids.length ? m.proposed_run.dataset_ids : datasets).join(", ")}</p>
          <Button onClick={() => onConfirm({ ...m.proposed_run!, dataset_ids: m.proposed_run!.dataset_ids.length
            ? m.proposed_run!.dataset_ids : datasets })}><Play size={12} /> Confirm and start</Button>
        </div>
      )}
    </div>
  );
}

function RunCard({ id, session, selected, onOpen, onSummary }: { id: string; session: string; selected: boolean;
  onOpen: () => void; onSummary: (content: string, runId: string) => void }) {
  const run = useQuery({ queryKey: ["run", id], queryFn: () => api.run(id) });
  useRunEvents(id, (ev) => { if (ev.type === "chat_message" && ev.session_id === session) onSummary(ev.content, id); });
  const r = run.data;
  return (
    <button onClick={onOpen} className={`block w-full rounded-lg border px-3 py-2 text-left text-sm ${selected ? "border-accent" : "border-line"}`}>
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs">{id}</span>
        <Badge tone={STATUS_TONE[r?.status ?? "queued"]}>{r?.status ?? "queued"}</Badge>
      </div>
      <div className="mt-1 flex gap-1">
        {r?.steps.map((s) => <span key={s.idx} title={`${s.name}: ${s.status}`}
          className="h-1.5 flex-1 rounded" style={{ background: { pending: "#e5e7eb", running: "#38bdf8",
            retrying: "#f59e0b", done: "#22c55e", failed: "#ef4444" }[s.status] }} />)}
      </div>
    </button>
  );
}
