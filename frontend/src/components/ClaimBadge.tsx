import { ShieldAlert, ShieldCheck } from "lucide-react";
import type { ClaimCheck } from "../api/client";
import { Tag } from "./ui";

export function ClaimBadge({ c }: { c: ClaimCheck | null | undefined }) {
  if (!c) return null;
  if (c.passed) {
    return c.checked
      ? <Tag tone="ok" title="Every number with decimals was matched against the run's output files or dataset descriptions.">
          <ShieldCheck size={11} /> All {c.checked} numbers verified</Tag>
      : null;
  }
  return <Tag tone="bad" title={c.untraced.map((u) => u.context).join("\n")}>
    <ShieldAlert size={11} /> {c.untraced.length} number{c.untraced.length > 1 ? "s" : ""} could not be checked: {c.untraced.map((u) => u.number).join(", ")}</Tag>;
}
