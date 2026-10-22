import { useSyncExternalStore } from "react";
import { API } from "./api/client";

/** One thing the run did, from the moment it started until the next one began. */
export interface LiveItem {
  id: number; agent: string; text: string; step: number | null; attempt: number | null;
  start: number; end: number | null;
  notes: { ts: number; agent: string; note: string }[];
  draft: string; drafting: boolean;
}
export interface LiveFeed { items: LiveItem[]; status: string | null; finished: boolean; first: number | null; last: number | null }

const EMPTY: LiveFeed = { items: [], status: null, finished: false, first: null, last: null };

// seen: events already applied; a reconnect replays the run's events from the start, so that many are skipped
interface Entry { feed: LiveFeed; listeners: Set<() => void>; es: EventSource | null; users: number; seen: number }
const feeds = new Map<string, Entry>();

function apply(f: LiveFeed, ev: any): LiveFeed {
  const ts: number = ev.ts ?? Date.now() / 1000;
  const items = f.items.slice();
  const closeLast = () => { const l = items.at(-1); if (l && l.end == null) items[items.length - 1] = { ...l, end: ts, drafting: false }; };
  const base = { ...f, first: f.first ?? ts, last: ts };
  switch (ev.type) {
    case "activity":
      closeLast();
      items.push({ id: items.length, agent: ev.agent, text: ev.text, step: ev.step ?? null, attempt: ev.attempt ?? null,
        start: ts, end: null, notes: [], draft: "", drafting: false });
      return { ...base, items };
    case "log": {
      const l = items.at(-1);
      if (!l) return base;
      items[items.length - 1] = { ...l, notes: [...l.notes, { ts, agent: ev.agent, note: ev.note }] };
      return { ...base, items };
    }
    case "draft":
    case "draft_done": {
      for (let i = items.length - 1; i >= 0; i--) {
        const it = items[i];
        if (it.agent === ev.agent && (it.step ?? null) === (ev.step ?? null) && (it.attempt ?? null) === (ev.attempt ?? null)) {
          items[i] = ev.type === "draft" ? { ...it, draft: it.draft + ev.delta, drafting: true } : { ...it, drafting: false };
          break;
        }
      }
      return { ...base, items };
    }
    case "run_status":
      if (ev.status === "done" || ev.status === "failed") closeLast();
      return { ...base, items, status: ev.status };
    case "run_finished":
      closeLast();
      return { ...base, items, finished: true };
    default:
      return base;
  }
}

function entry(runId: string): Entry {
  let e = feeds.get(runId);
  if (!e) { e = { feed: EMPTY, listeners: new Set(), es: null, users: 0, seen: 0 }; feeds.set(runId, e); }
  return e;
}

function open(runId: string, e: Entry) {
  if (e.es || e.feed.finished) return;
  const es = new EventSource(`${API}/runs/${runId}/events`);
  // events arrive in bursts (a replay, or a draft every quarter second); render once per frame
  let pending: any[] = [], scheduled = false, replayed = 0;
  const skip = e.seen;
  const flush = () => {
    scheduled = false;
    let f = e.feed;
    for (const ev of pending) f = apply(f, ev);
    pending = [];
    e.feed = f;
    e.listeners.forEach((l) => l());
    if (f.finished) { es.close(); e.es = null; }
  };
  const handle = (m: MessageEvent) => {
    if (replayed++ < skip) return;
    e.seen++;
    pending.push(JSON.parse(m.data));
    if (!scheduled) { scheduled = true; requestAnimationFrame(flush); }
  };
  ["activity", "log", "draft", "draft_done", "run_status", "run_finished"].forEach((t) => es.addEventListener(t, handle));
  es.onerror = () => { es.close(); e.es = null; };
  e.es = es;
}

/** The live timeline of a run, shared by every component that shows it (one connection per run). */
export function useLiveFeed(runId: string | null): LiveFeed {
  return useSyncExternalStore(
    (cb) => {
      if (!runId) return () => {};
      const e = entry(runId);
      e.listeners.add(cb);
      e.users++;
      open(runId, e);
      return () => {
        e.listeners.delete(cb);
        if (--e.users === 0 && e.es) { e.es.close(); e.es = null; }
      };
    },
    () => (runId ? entry(runId).feed : EMPTY),
  );
}

// --- the structured answer as it streams: pull string fields out of incomplete JSON ---------------------------

function decodeFrom(s: string, i: number): { value: string; done: boolean; end: number } {
  let out = "";
  while (i < s.length) {
    const c = s[i];
    if (c === '"') return { value: out, done: true, end: i + 1 };
    if (c !== "\\") { out += c; i++; continue; }
    const n = s[i + 1];
    if (n === undefined) break;
    if (n === "u") {
      const hex = s.slice(i + 2, i + 6);
      if (hex.length < 4) break;
      out += String.fromCharCode(parseInt(hex, 16));
      i += 6;
      continue;
    }
    out += ({ n: "\n", t: "\t", r: "\r", b: "\b", f: "\f" } as Record<string, string>)[n] ?? n;
    i += 2;
  }
  return { value: out, done: false, end: s.length };
}

/** Every value of a string field, in order; the last one may still be being written. */
export function jsonStrings(json: string, field: string): { value: string; done: boolean }[] {
  const out: { value: string; done: boolean }[] = [];
  const re = new RegExp(`"${field}"\\s*:\\s*"`, "g");
  let m: RegExpExecArray | null;
  while ((m = re.exec(json))) {
    const d = decodeFrom(json, m.index + m[0].length);
    out.push({ value: d.value, done: d.done });
    re.lastIndex = d.end;
  }
  return out;
}
