import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Bot, Lightbulb, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, chatStream, type ChatMessage, type ProposedRun } from "../api/client";
import { ClaimBadge } from "../components/ClaimBadge";
import { knownError, runTitle, toolLabel } from "../components/labels";
import { useDetailed } from "../components/prefs";
import { Button } from "../components/ui";
import { useRunEvents } from "../useRunEvents";

interface Props {
  session: string; open: boolean; onClose: () => void;
  runId: string | null; datasets: string[];
  /** a question queued by another part of the page ("Ask about this result") */
  pending: string | null; onPendingTaken: () => void;
  onRunStarted: (id: string) => void;
}

/** The assistant answers from your data and runs; each number in an answer is checked against what its tools returned. */
export function Assistant({ session, open, onClose, runId, datasets, pending, onPendingTaken, onRunStarted }: Props) {
  const detailed = useDetailed();
  const qc = useQueryClient();
  const history = useQuery({ queryKey: ["chat", session], queryFn: () => api.chatHistory(session), staleTime: Infinity });
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId!), enabled: !!runId });
  const [local, setLocal] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [watching, setWatching] = useState<string[]>([]);
  const end = useRef<HTMLDivElement>(null);
  const shown = [...(history.data ?? []), ...local];

  useEffect(() => { if (open) end.current?.scrollIntoView({ block: "end" }); }, [open, history.data, local]);
  useEffect(() => {
    if (pending && open && !busy) { onPendingTaken(); ask(pending); }
  }, [pending, open]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function ask(message: string) {
    message = message.trim();
    if (!message || busy) return;
    setText(""); setBusy(true); setError(null);
    setLocal((l) => [...l, { role: "user", content: message }, { role: "assistant", content: "", tools: [] }]);
    try {
      for await (const ev of chatStream(session, message, datasets, runId)) {
        if (ev.event === "tool_call") setLocal((l) => patchLast(l, (m) => ({ ...m, tools: [...(m.tools ?? []), ev.data.name] })));
        if (ev.event === "answer") setLocal((l) => patchLast(l, (m) => ({ ...m, content: ev.data.content,
          claim_check: ev.data.claim_check, proposed_run: ev.data.proposed_run })));
        if (ev.event === "error") throw new Error(ev.data.message);
      }
    } catch (e) {
      setLocal((l) => (l.at(-1)?.content === "" ? l.slice(0, -1) : l));
      const m = e instanceof Error ? e.message : String(e);
      setError(knownError(m)?.title ?? m);
    } finally { setBusy(false); }
  }

  async function confirm(p: ProposedRun) {
    setError(null);
    try {
      const { id } = await api.startRun({ ...p, dataset_ids: p.dataset_ids.length ? p.dataset_ids : datasets,
        engines: p.engines ?? ["agents"], session_id: session });
      setWatching((w) => [...w, id]);
      qc.invalidateQueries({ queryKey: ["runs"] });
      onRunStarted(id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }

  const r = run.data;
  const suggestions = !r ? ["What data do I have, and what can I do with it?", "Is the silicon 640f dataset well documented?",
      "Suggest an analysis for the data I selected."]
    : r.status === "failed" ? ["Why did this analysis fail?", "What should I change so it works?"]
    : r.status === "done" ? ["Explain this result in plain words.", "Is the difference from the certified value a problem?",
      "What limits the accuracy of this result?"]
    : ["What is this analysis doing right now?"];

  if (!open) return null;
  return (
    <aside className="flex h-full w-[400px] shrink-0 flex-col border-l border-line bg-surface" aria-label="Assistant">
      {watching.map((id) => <SummaryWatcher key={id} id={id} session={session}
        onSummary={(content) => setLocal((l) => [...l, { role: "assistant", content, run_id: id }])} />)}
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-4">
        <span className="flex size-7 items-center justify-center rounded-full bg-accent-soft text-accent"><Bot size={15} /></span>
        <div className="min-w-0">
          <h2 className="text-[13px] font-semibold leading-4">Assistant</h2>
          <p className="truncate text-[11px] text-muted">Answers from your data and analyses</p>
        </div>
        <button onClick={onClose} className="ml-auto rounded p-1 text-muted hover:bg-subtle hover:text-ink" aria-label="Close the assistant"><X size={16} /></button>
      </div>
      <div className="border-b border-line bg-subtle/60 px-4 py-2 text-[11.5px] text-muted">
        {r ? <>Talking about: <span className="font-medium text-ink-2">{runTitle({ title: r.plan?.title, prompt: r.prompt })}</span>{detailed && <span className="font-mono"> ({r.id})</span>}</>
          : datasets.length ? <>Selected data: <span className="font-medium text-ink-2">{datasets.join(", ")}</span></>
          : "Open an analysis or select data and the assistant will use it as context."}
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {shown.length === 0 && <div className="px-4 py-5 text-[12.5px] leading-5 text-muted">
          Ask about your datasets, a result, or what to try next. It can also suggest an analysis; nothing starts until you confirm.
          Every number in an answer is checked against what it looked up.</div>}
        <ol className="space-y-3 px-4 py-3">
          {shown.map((m, i) => <Message key={i} m={m} onConfirm={confirm} datasets={datasets} live={busy && i === shown.length - 1} />)}
        </ol>
        <div ref={end} />
      </div>

      <div className="border-t border-line p-3">
        {!busy && <div className="mb-2 flex flex-wrap gap-1.5">
          {suggestions.map((s) => <button key={s} onClick={() => ask(s)}
            className="inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-left text-[11.5px] text-ink-2 hover:border-accent hover:text-accent">
            <Lightbulb size={11} className="shrink-0 text-faint" />{s}</button>)}
        </div>}
        {error && <p className="mb-2 rounded-md border border-bad/20 bg-bad-soft px-2.5 py-2 text-xs text-bad">{error}</p>}
        <form className="flex items-end gap-2 rounded-lg border border-line-strong p-1.5 focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/15"
          onSubmit={(e) => { e.preventDefault(); ask(text); }}>
          <textarea rows={2} className="max-h-32 min-h-[40px] flex-1 resize-none bg-transparent px-1.5 py-1 text-[13px] leading-5 outline-none placeholder:text-faint"
            value={text} placeholder="Ask a question…" onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(text); } }} />
          <Button type="submit" variant="primary" size="sm" disabled={busy || !text.trim()} aria-label="Send"><ArrowUp size={14} /></Button>
        </form>
        <p className="mt-1 text-[10.5px] text-faint">Enter to send · Shift+Enter for a new line</p>
      </div>
    </aside>
  );
}

function patchLast(l: ChatMessage[], f: (m: ChatMessage) => ChatMessage) {
  return [...l.slice(0, -1), f(l[l.length - 1])];
}

function Message({ m, onConfirm, datasets, live }: { m: ChatMessage; onConfirm: (p: ProposedRun) => void; datasets: string[]; live: boolean }) {
  const detailed = useDetailed();
  const tools = [...new Set(m.tools ?? [])];
  if (m.role === "user") {
    return <li className="ml-8 rounded-lg rounded-br-sm bg-accent px-3 py-2 text-[13px] leading-5 text-white">{m.content}</li>;
  }
  return (
    <li className="mr-4">
      {m.run_id && <div className="mb-1 text-[11px] font-medium text-muted">Analysis finished{detailed && <span className="font-mono"> · {m.run_id}</span>}</div>}
      <div className="rounded-lg rounded-bl-sm border border-line bg-surface px-3 py-2">
        {tools.length > 0 && <p className="mb-1 text-[11px] text-faint">{live && !m.content ? "Looking at " : "Looked at "}{tools.map(toolLabel).join(", ")}{live && !m.content ? "…" : ""}</p>}
        {m.content ? <div className="doc"><Markdown remarkPlugins={[remarkGfm]}>{m.content}</Markdown></div>
          : <div className="flex items-center gap-1.5 py-1 text-[12px] text-muted"><span className="size-1.5 animate-pulse rounded-full bg-accent" />Thinking…</div>}
        {m.claim_check && <div className="mt-1.5"><ClaimBadge c={m.claim_check} /></div>}
      </div>
      {m.proposed_run && (
        <div className="mt-2 rounded-lg border border-accent/30 bg-accent-soft/50 p-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-accent">Suggested analysis</div>
          <p className="my-1.5 text-[13px]">{m.proposed_run.prompt}</p>
          <p className="mb-2 text-[11px] text-muted">Data: {(m.proposed_run.dataset_ids.length ? m.proposed_run.dataset_ids : datasets).join(", ") || "none selected"}</p>
          <Button size="sm" variant="primary" onClick={() => onConfirm(m.proposed_run!)}>Confirm and start</Button>
        </div>
      )}
    </li>
  );
}

/** Runs started from the chat post a short summary when they finish; show it in the conversation. */
function SummaryWatcher({ id, session, onSummary }: { id: string; session: string; onSummary: (content: string) => void }) {
  useRunEvents(id, (ev) => { if (ev.type === "chat_message" && ev.session_id === session) onSummary(ev.content); });
  return null;
}
