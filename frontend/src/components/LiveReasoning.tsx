import { Check, ChevronRight } from "lucide-react";
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { type LiveFeed, type LiveItem, jsonStrings } from "../useLiveFeed";
import { ACTOR, type Actor } from "./Flow";
import { useDetailed } from "./prefs";
import { cn } from "./ui";

const ACTOR_OF: Record<string, Actor> = {
  planner: "llm", coder: "llm", analyst: "llm", sandbox: "program", gsas2: "program", maud: "program",
};
const WHO: Record<string, string> = {
  planner: "AI planner", coder: "AI coder", analyst: "AI analyst", sandbox: "sandbox", checker: "automatic check",
  claim_checker: "number check", orchestrator: "CoRefine", gsas2: "GSAS-II", maud: "MAUD",
};
const LLM = new Set(["planner", "coder", "analyst"]);

export function useNow(active: boolean, ms = 1000): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now() / 1000), ms);
    return () => clearInterval(t);
  }, [active, ms]);
  return now;
}

export function clockSpan(s: number): string {
  s = Math.max(0, Math.round(s));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

const startTs = (t?: string | null) => (t ? Date.parse(t.endsWith("Z") || t.includes("+") ? t : t + "Z") / 1000 : null);

/** One line for the header of a running analysis: what is happening now, and for how long. */
export function LiveStatus({ feed, startedAt }: { feed: LiveFeed; startedAt?: string | null }) {
  const live = !feed.finished && feed.status !== "done" && feed.status !== "failed";
  const now = useNow(live);
  const cur = feed.items.at(-1);
  const t0 = startTs(startedAt) ?? feed.first;
  return (
    <div className="flex items-center gap-2.5">
      <span className="relative flex size-2.5 shrink-0">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent opacity-50" />
        <span className="relative inline-flex size-2.5 rounded-full bg-accent" />
      </span>
      <span className="shimmer min-w-0 truncate text-[13.5px] font-semibold">{cur ? cur.text : "Starting the analysis"}…</span>
      {t0 != null && <span className="tabular ml-auto shrink-0 font-mono text-[12px] text-muted">{clockSpan(now - t0)}</span>}
    </div>
  );
}

/** The run told as it happens: each activity appears when it starts, the active one stays open with whatever the
 *  AI is writing, and finished ones fold into a line with how long they took. */
export function LiveReasoning({ feed, startedAt, title }: { feed: LiveFeed; startedAt?: string | null; title?: ReactNode }) {
  const live = !feed.finished && feed.status !== "done" && feed.status !== "failed";
  const now = useNow(live);
  const box = useRef<HTMLDivElement>(null);
  const [follow, setFollow] = useState(true);
  useLayoutEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [feed, follow]);
  const onScroll = () => {
    const el = box.current;
    if (el) setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 60);
  };
  const total = (feed.last ?? now) - (feed.first ?? now);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-line px-4 py-2.5">
        {title}
        {live ? <div className="flex items-center gap-2 text-[12.5px] text-ink-2">
            <span className="relative flex size-2"><span className="absolute inline-flex size-full animate-ping rounded-full bg-accent opacity-50" />
              <span className="relative inline-flex size-2 rounded-full bg-accent" /></span>
            Working live · step {feed.items.length}
            <span className="tabular ml-auto font-mono text-[12px] text-muted">{clockSpan(now - (startTs(startedAt) ?? feed.first ?? now))}</span></div>
          : <div className="flex items-center gap-2 text-[13px] font-medium">
              <span className={cn("flex size-5 items-center justify-center rounded-full text-white", feed.status === "failed" ? "bg-bad" : "bg-ok")}>
                <Check size={12} strokeWidth={3} /></span>
              {feed.status === "failed" ? "Stopped" : "Finished"} after {clockSpan(total)} · {feed.items.length} steps</div>}
      </div>
      <div ref={box} onScroll={onScroll} className="relative min-h-0 flex-1 overflow-auto px-4 py-3">
        <ol>
          {feed.items.map((it, i) => <Row key={it.id} it={it} active={live && i === feed.items.length - 1} now={now}
            last={i === feed.items.length - 1} />)}
        </ol>
        {live && !follow && <button onClick={() => setFollow(true)}
          className="sticky bottom-2 left-full ml-auto block rounded-full bg-ink px-3 py-1 text-[11.5px] text-white shadow-lg">Jump to live ↓</button>}
      </div>
    </div>
  );
}

function Row({ it, active, now, last }: { it: LiveItem; active: boolean; now: number; last: boolean }) {
  const [open, setOpen] = useState(false);
  const A = ACTOR[ACTOR_OF[it.agent] ?? "code"];
  const took = (it.end ?? now) - it.start;
  const expanded = active || open;
  const hasMore = it.notes.length > 0 || it.draft.length > 0;
  return (
    <li className="live-in relative flex gap-3 pb-3">
      {!last && <span className="absolute bottom-0 left-[13px] top-7 w-px bg-line-strong" />}
      <span className={cn("z-10 flex size-7 shrink-0 items-center justify-center rounded-full border-2 bg-surface", A.ring,
        active && "ring-4 ring-accent/15")}>
        {active ? <span className="size-3 animate-spin rounded-full border-2 border-current border-t-transparent" /> : <A.icon size={13} />}
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        <button disabled={active || !hasMore} onClick={() => setOpen((o) => !o)} className="flex w-full items-start gap-2 text-left">
          <span className={cn("min-w-0 flex-1 text-[13px] leading-5", active ? "shimmer font-medium" : "text-ink-2")}>{it.text}</span>
          <span className="shrink-0 pt-px text-[11px] text-faint">{WHO[it.agent] ?? it.agent}</span>
          <span className="tabular w-10 shrink-0 pt-px text-right font-mono text-[11px] text-muted">{clockSpan(took)}</span>
          {!active && hasMore && <ChevronRight size={14} className={cn("mt-0.5 shrink-0 text-faint transition", open && "rotate-90")} />}
        </button>
        {expanded && <div className="mt-1.5 space-y-1.5">
          {active && LLM.has(it.agent) && !it.draft && <p className="flex items-center gap-1.5 text-[12px] text-muted">
            <Dots /> Thinking</p>}
          {it.draft && <Draft agent={it.agent} text={it.draft} writing={it.drafting} />}
          {it.notes.map((n, k) => <p key={k} className="live-in text-[12px] leading-5 text-ink-2">
            <span className="mr-1.5 font-mono text-[10.5px] text-faint">+{clockSpan(n.ts - it.start)}</span>{n.note}</p>)}
        </div>}
      </div>
    </li>
  );
}

function Dots() {
  return <span className="inline-flex gap-0.5">{[0, 1, 2].map((i) => <span key={i} className="size-1 animate-bounce rounded-full bg-muted"
    style={{ animationDelay: `${i * 0.15}s` }} />)}</span>;
}

/** What the AI is writing, shown as it streams: the plan's steps, the step's code, or the report. */
function Draft({ agent, text, writing }: { agent: string; text: string; writing: boolean }) {
  const detailed = useDetailed();
  const box = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => { if (writing && box.current) box.current.scrollTop = box.current.scrollHeight; }, [text, writing]);
  const caret = writing ? <span className="caret" /> : null;

  if (agent === "coder") {
    const code = jsonStrings(text, "code")[0]?.value ?? "";
    const notes = jsonStrings(text, "notes")[0]?.value;
    const lines = code ? code.split("\n").length : 0;
    return (
      <div className="min-w-0 overflow-hidden rounded-md border border-line">
        <div className="flex items-center gap-2 border-b border-line bg-subtle px-2.5 py-1 text-[11px] text-muted">
          <span className="shrink-0 whitespace-nowrap font-medium text-ink-2">{writing ? "Writing Python" : "Python script"}</span>
          <span className="tabular shrink-0 whitespace-nowrap">{lines} lines</span>
          {notes && <span className="min-w-0 truncate" title={notes}>· {notes}</span>}
        </div>
        <div ref={box} className={cn("overflow-auto bg-[#0f1420] px-3 py-2", detailed ? "max-h-80" : "max-h-48")}>
          <pre className="font-mono text-[11px] leading-[1.45] text-[#d6deeb]">{code}{caret}</pre>
        </div>
      </div>
    );
  }
  if (agent === "planner") {
    const title = jsonStrings(text, "title")[0]?.value;
    const goals = jsonStrings(text, "goal");
    return (
      <div className="rounded-md border border-line bg-surface px-3 py-2 text-[12.5px] leading-5">
        {title && <p className="font-medium">{title}{!goals.length && caret}</p>}
        {goals.length > 0 && <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-ink-2">
          {goals.map((g, i) => <li key={i} className="live-in">{g.value}{i === goals.length - 1 && caret}</li>)}</ol>}
        {!title && !goals.length && <span className="text-muted">Drafting the plan{caret}</span>}
      </div>
    );
  }
  const report = jsonStrings(text, "report_markdown")[0]?.value ?? "";
  return (
    <div ref={box} className="max-h-72 overflow-auto rounded-md border border-line bg-surface px-3 py-2">
      {report ? <div className="doc"><Markdown remarkPlugins={[remarkGfm]}>{report}</Markdown>{caret}</div>
        : <span className="text-[12px] text-muted">Deciding on the classification{caret}</span>}
    </div>
  );
}
