import { Check, ChevronDown, Search } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { cn } from "./ui";

export interface PickerOption { value: string; label: string; sub?: string; group?: string; disabled?: boolean; extra?: ReactNode }

/** A dropdown that shows two lines per option and, with many options, a search box. Single choice by default;
 *  `multiple` keeps it open and toggles. Keyboard: arrows move, Enter picks, Escape closes. */
export function Picker({ options, value, onChange, placeholder = "Choose…", multiple = false, searchable, empty, label }: {
  options: PickerOption[]; value: string[]; onChange: (v: string[]) => void; placeholder?: string; multiple?: boolean;
  searchable?: boolean; empty?: ReactNode; label: string;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [hi, setHi] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const id = useId();
  const search = searchable ?? options.length > 6;
  const shown = options.filter((o) => !q || `${o.label} ${o.sub ?? ""} ${o.value}`.toLowerCase().includes(q.toLowerCase()));
  const picked = options.filter((o) => value.includes(o.value));

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  useEffect(() => { if (!open) setQ(""); else setHi(Math.max(0, shown.findIndex((o) => value.includes(o.value)))); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { list.current?.querySelector(`[data-i="${hi}"]`)?.scrollIntoView({ block: "nearest" }); }, [hi]);

  const pick = (o: PickerOption) => {
    if (o.disabled) return;
    if (multiple) onChange(value.includes(o.value) ? value.filter((v) => v !== o.value) : [...value, o.value]);
    else { onChange([o.value]); setOpen(false); }
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { setOpen(false); return; }
    if (!open && (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ")) { e.preventDefault(); setOpen(true); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(shown.length - 1, h + 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(0, h - 1)); }
    if (e.key === "Enter" && shown[hi]) { e.preventDefault(); pick(shown[hi]); }
  };

  let lastGroup: string | undefined;
  return (
    <div ref={box} className="relative" onKeyDown={onKey}>
      <button type="button" aria-haspopup="listbox" aria-expanded={open} aria-controls={id} aria-label={label}
        onClick={() => setOpen((o) => !o)}
        className={cn("flex min-h-9 w-full items-center gap-2 rounded-md border bg-surface px-2.5 py-1.5 text-left outline-none",
          open ? "border-accent ring-2 ring-accent/15" : "border-line-strong hover:border-ink-2/40")}>
        <span className="min-w-0 flex-1">
          {!picked.length ? <span className="text-[13px] text-faint">{placeholder}</span>
            : multiple ? <span className="block truncate text-[13px]">{picked.map((o) => o.label).join(", ")}</span>
            : <><span className="block truncate text-[13px] font-medium">{picked[0].label}</span>
                {picked[0].sub && <span className="block truncate text-[11.5px] text-muted">{picked[0].sub}</span>}</>}
        </span>
        <ChevronDown size={15} className={cn("shrink-0 text-muted transition", open && "rotate-180")} />
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-full overflow-hidden rounded-md border border-line-strong bg-surface shadow-lg">
          {search && <div className="flex items-center gap-2 border-b border-line px-2.5">
            <Search size={13} className="text-faint" />
            <input autoFocus value={q} onChange={(e) => { setQ(e.target.value); setHi(0); }} placeholder="Search"
              className="h-8 w-full bg-transparent text-[12.5px] outline-none placeholder:text-faint" />
          </div>}
          <ul ref={list} id={id} role="listbox" aria-multiselectable={multiple} className="max-h-72 overflow-auto py-1">
            {!shown.length && <li className="px-3 py-2 text-[12px] text-muted">{empty ?? "Nothing matches."}</li>}
            {shown.map((o, i) => {
              const head = o.group && o.group !== lastGroup ? o.group : null;
              lastGroup = o.group;
              const on = value.includes(o.value);
              return (
                <li key={o.value} role="presentation">
                  {head && <div className="px-3 pb-0.5 pt-2 text-[10.5px] font-medium uppercase tracking-wider text-faint">{head}</div>}
                  <div role="option" aria-selected={on} aria-disabled={o.disabled} data-i={i}
                    onMouseEnter={() => setHi(i)} onClick={() => pick(o)}
                    className={cn("flex cursor-pointer items-start gap-2 px-3 py-1.5", i === hi && !o.disabled && "bg-subtle",
                      o.disabled && "cursor-default")}>
                    {multiple ? <span className={cn("mt-0.5 flex size-4 shrink-0 items-center justify-center rounded border",
                        on ? "border-accent bg-accent text-white" : "border-line-strong", o.disabled && "opacity-40")}>
                        {on && <Check size={11} strokeWidth={3} />}</span>
                      : <Check size={14} className={cn("mt-0.5 shrink-0 text-accent", !on && "invisible")} />}
                    <span className={cn("min-w-0 flex-1", o.disabled && "opacity-55")}>
                      <span className="block text-[12.5px] font-medium">{o.label}</span>
                      {o.sub && <span className="block text-[11.5px] leading-4 text-muted">{o.sub}</span>}
                    </span>
                    {o.extra}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
