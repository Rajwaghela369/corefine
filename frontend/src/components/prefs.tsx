import { type ReactNode, createContext, useContext, useState } from "react";
import { cn } from "./ui";

export type Detail = "simple" | "detailed";
const KEY = "corefine-detail";

const Ctx = createContext<{ detail: Detail; setDetail: (d: Detail) => void }>({ detail: "simple", setDetail: () => {} });

function load(): Detail {
  try { return localStorage.getItem(KEY) === "detailed" ? "detailed" : "simple"; } catch { return "simple"; }
}

export function DetailProvider({ children }: { children: ReactNode }) {
  const [detail, set] = useState<Detail>(load);
  const setDetail = (d: Detail) => { set(d); try { localStorage.setItem(KEY, d); } catch { /* private window */ } };
  return <Ctx.Provider value={{ detail, setDetail }}>{children}</Ctx.Provider>;
}

/** True when the person asked for technical detail (IDs, raw names, code, source files). */
export function useDetailed(): boolean {
  return useContext(Ctx).detail === "detailed";
}

export function DetailToggle() {
  const { detail, setDetail } = useContext(Ctx);
  return (
    <div className="flex rounded-md border border-line-strong p-0.5" role="radiogroup" aria-label="Level of detail">
      {(["simple", "detailed"] as const).map((d) => (
        <button key={d} role="radio" aria-checked={detail === d} onClick={() => setDetail(d)}
          title={d === "simple" ? "Plain-language view: results and what they mean" : "Everything: IDs, raw metric names, code, logs and source files"}
          className={cn("rounded px-2.5 py-0.5 text-xs", detail === d ? "bg-ink font-medium text-white" : "text-muted hover:text-ink")}>
          {d === "simple" ? "Simple" : "Detailed"}</button>
      ))}
    </div>
  );
}
