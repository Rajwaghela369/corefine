import { type ReactNode, createContext, useContext } from "react";
import type { View } from "./Sidebar";

const Ctx = createContext<(v: View) => void>(() => {});

/** Lets any page send the person to another one (e.g. "set up in Software") without threading props. */
export function NavProvider({ go, children }: { go: (v: View) => void; children: ReactNode }) {
  return <Ctx.Provider value={go}>{children}</Ctx.Provider>;
}

export function useGo(): (v: View) => void {
  return useContext(Ctx);
}
