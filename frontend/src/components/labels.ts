// Plain-language wording for researchers: metric names, units, verdicts, errors and titles.
// Numbers shown here are only ever read from run metrics; nothing is computed into a new claim.
import type { DatasetNode, Metric, RunDetail, RunListItem } from "../api/client";
import type { Tone } from "./ui";

// --- metrics ---------------------------------------------------------------

interface MetricInfo { label: string; help?: string; key?: boolean }

const METRICS: Record<string, MetricInfo> = {
  a_refined: { label: "Refined lattice parameter a", help: "The cubic cell edge this run measured.", key: true },
  a_certified: { label: "Certified lattice parameter", help: "The value on the reference material's certificate.", key: true },
  difference_from_certified: { label: "Difference from certified value", help: "Refined minus certified.", key: true },
  difference_relative_percent: { label: "Difference (percent)", key: true },
  difference_in_sigma: { label: "Difference ÷ fit uncertainty",
    help: "How many times larger the difference is than the fit's own statistical uncertainty." },
  success_target: { label: "Allowed difference (target)", key: true },
  within_target: { label: "Within the target?", key: true },
  zero_shift: { label: "Zero-point shift of the instrument", help: "A constant 2θ offset fitted together with a.", key: true },
  wavelength: { label: "X-ray wavelength", key: true },
  scan_temperature: { label: "Temperature during the scan", key: true },
  scan_file: { label: "Scan file used", key: true },
  n_scans_available: { label: "Scans available in the dataset" },
  n_points: { label: "Data points in the scan" },
  n_points_raw: { label: "Data points in the scan" },
  n_points_clean: { label: "Data points after cleaning" },
  two_theta_min: { label: "Scan start angle (2θ)" },
  two_theta_max: { label: "Scan end angle (2θ)" },
  two_theta_step: { label: "Angle step (2θ)" },
  max_intensity: { label: "Highest intensity" },
  reference_a: { label: "Reference-structure a (COD)" },
  a_reference_cod: { label: "Reference-structure a (COD)" },
  n_expected_reflections: { label: "Peaks expected from the structure" },
  n_peaks_fitted: { label: "Peaks fitted", key: true },
  n_peaks: { label: "Peaks used in the refinement", key: true },
  n_peaks_failed: { label: "Peaks that could not be fitted", key: true },
  median_fwhm: { label: "Typical peak width (FWHM)" },
  median_centre_error: { label: "Typical peak-position uncertainty" },
  median_center_uncertainty: { label: "Typical peak-position uncertainty" },
  reduced_chi2_refinement: { label: "Goodness of fit (reduced χ²)", help: "Near 1 means the residuals match the error bars.", key: true },
  residual_slope: { label: "Trend in residuals with angle", help: "Near zero means no angle-dependent error is left." },
};

export function metricLabel(name: string): string {
  if (METRICS[name]) return METRICS[name].label;
  const s = name
    .replace(/^n_/, "number of ")
    .replace(/two_theta|2theta/g, "2θ")
    .replace(/chi2/g, "χ²")
    .replace(/fwhm/g, "FWHM")
    .replaceAll("_", " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export const metricHelp = (name: string) => METRICS[name]?.help;
export const isKeyMetric = (name: string) => !!METRICS[name]?.key;

const UNITS: Record<string, string> = {
  angstrom: "Å", degree: "°", degC: "°C", percent: "%", sigma: "σ", degree_per_degree: "° per °",
  count: "", dimensionless: "", counts: "counts",
};
export const unitLabel = (u: string | null | undefined) => (u == null ? "" : UNITS[u] ?? u);

/** Round a value to the precision its uncertainty supports (two significant digits of the uncertainty). */
export function formatValue(v: Metric["value"], u?: number | null): string {
  if (v === null || v === undefined || v === "") return "—";
  if (v === "true" || v === true as unknown) return "yes";
  if (v === "false" || v === false as unknown) return "no";
  const n = typeof v === "number" ? v : Number(v);
  if (typeof v === "string" && (v.trim() === "" || !Number.isFinite(n))) return v.replace(/^"|"$/g, "");
  if (Number.isInteger(n)) return String(n);
  if (u && u > 0) {
    const decimals = Math.max(0, Math.min(10, 1 - Math.floor(Math.log10(u))));
    return n.toFixed(decimals);
  }
  if (Math.abs(n) >= 1000) return n.toFixed(0);
  if (Math.abs(n) < 1e-4) return n.toExponential(2);
  return String(Number(n.toPrecision(8)));
}

export const formatUncertainty = (u: number | null | undefined) =>
  u && u > 0 ? Number(u.toPrecision(2)).toString() : null;

// --- runs ------------------------------------------------------------------

const asNum = (v: unknown) => (typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" && !isNaN(Number(v)) ? Number(v) : null);
// The code-run comparison is recorded after the agents' own metrics, and the Coder may log a placeholder under the same
// name ("a_certified: not provided in manifest", since it never sees the certificate): the last numeric entry wins.
const metric = (run: RunDetail, name: string) => {
  const all = run.metrics.filter((m) => m.name === name);
  return all.findLast((m) => asNum(m.value) != null) ?? all.at(-1);
};

export function runTitle(r: Pick<RunListItem, "title" | "prompt">): string {
  return r.title?.trim() || r.prompt.trim() || "Untitled analysis";
}

export const CLASS: Record<string, { label: string; tone: Tone; explain: string }> = {
  agreement: { label: "Agrees with the certificate", tone: "ok", explain: "" },
  missing_geometric_correction: { label: "Missing geometric correction", tone: "warn",
    explain: "The leftover errors change steadily with angle, which points to an uncorrected geometric effect such as sample height." },
  metadata_issue: { label: "Possible metadata problem", tone: "warn",
    explain: "Something in the file information (for example the wavelength) looks inconsistent." },
  weak_or_overlapping_peaks: { label: "Weak or overlapping peaks", tone: "warn",
    explain: "Some peaks were too weak or too close together to fit reliably." },
  unexplained: { label: "Needs review", tone: "bad",
    explain: "The automatic checks could not explain the difference; a person should look at it." },
};

export interface Verdict { tone: Tone; headline: string; details: string[] }

/** The plain-language answer for a run, built only from the run's own metrics. */
export function verdict(run: RunDetail): Verdict {
  if (run.status === "failed") {
    const e = friendlyError(run.error);
    return { tone: "bad", headline: e.title, details: [e.advice] };
  }
  if (run.status !== "done") {
    return { tone: "run", headline: "The analysis is running.", details: ["Results appear here as soon as each step finishes."] };
  }
  const a = metric(run, "a_refined"), cert = metric(run, "a_certified"), diff = metric(run, "difference_from_certified");
  const target = metric(run, "success_target"), within = metric(run, "within_target"), sigma = metric(run, "difference_in_sigma");
  const av = asNum(a?.value), cv = asNum(cert?.value), dv = asNum(diff?.value), tv = asNum(target?.value), sv = asNum(sigma?.value);
  const cls = run.classification ? CLASS[run.classification] : null;
  const details: string[] = [];
  if (av == null) {
    return { tone: cls?.tone ?? "neutral", headline: "The analysis finished but did not report a refined lattice parameter.",
      details: ["Open the Report or ask the assistant what the run found."] };
  }
  const aText = `${formatValue(av, a?.uncertainty)} Å`;
  if (cv == null || dv == null) {
    if (cls?.explain) details.push(cls.explain);
    details.push("No certified value was available, so the result was not compared with a certificate.");
    return { tone: cls?.tone ?? "neutral", headline: `The refined lattice parameter is ${aText}.`, details };
  }
  const ok = String(within?.value) === "true";
  const dText = `${Math.abs(dv).toFixed(6)} Å`;
  const headline = ok
    ? `The refined lattice parameter, ${aText}, agrees with the certified value of ${cv.toFixed(6)} Å.`
    : `The refined lattice parameter, ${aText}, is further from the certified value (${cv.toFixed(6)} Å) than the target allows.`;
  details.push(tv != null
    ? `They differ by ${dText}; the target for this check is ±${tv} Å${ok ? ", so the result passes." : "."}`
    : `They differ by ${dText}.`);
  if (sv != null && Math.abs(sv) >= 3 && a?.uncertainty) {
    details.push(`That difference is ${Math.abs(sv).toFixed(1)} times the fit's own uncertainty (±${formatUncertainty(a.uncertainty)} Å). ` +
      "The fit uncertainty only covers random scatter in the peak positions, not systematic effects such as instrument alignment, " +
      "so this ratio overstates the disagreement and does not by itself mean the result is wrong.");
  }
  if (cls?.explain) details.push(cls.explain);
  return { tone: ok ? (cls?.tone === "bad" ? "warn" : "ok") : "bad", headline, details };
}

// --- errors ----------------------------------------------------------------

export interface FriendlyError { title: string; advice: string }

const ERRORS: [RegExp, FriendlyError][] = [
  [/snapshot .* (is building|is pending|not ready)/i, { title: "The analysis computer was still being set up.",
    advice: "Wait a few minutes and start the analysis again." }],
  [/snapshot .* not found/i, { title: "The analysis computer is not set up.",
    advice: "An administrator needs to build the sandbox snapshot (scripts/setup.py --snapshot)." }],
  [/interrupted/i, { title: "The analysis was interrupted because the server restarted.", advice: "Start it again." }],
  [/API error 429|rate limit/i, { title: "The AI service is busy right now.", advice: "Wait a minute and try again." }],
  [/API error 40[13]|authentication|api[_ ]key/i, { title: "The AI service is not configured.",
    advice: "Ask an administrator to check the Anthropic API key on the server." }],
  [/could not reach the Anthropic API/i, { title: "Could not reach the AI service.", advice: "Check the server's internet connection, then try again." }],
  [/Streaming is required|API error 5\d\d|overloaded/i, { title: "The AI service had a temporary problem.", advice: "Try again in a few minutes." }],
  [/max_tokens/i, { title: "The AI's answer was too long and was cut off.", advice: "Try a narrower request." }],
  [/declined the request/i, { title: "The AI declined this request.", advice: "Rephrase what you want to find out." }],
  [/time limit|timed out/i, { title: "A step took longer than the time allowed.", advice: "Try a simpler analysis, or ask the assistant why it was slow." }],
  [/byte limit/i, { title: "A step produced more output than allowed.", advice: "Ask for fewer or smaller output files." }],
  [/measured_pattern/i, { title: "No measured scan was selected.", advice: "Choose at least one measured scan under 'Your data'." }],
  [/Failed to create sandbox|sandbox/i, { title: "The analysis computer could not be started.", advice: "Try again in a few minutes; if it keeps failing, ask an administrator." }],
];

/** The plain explanation for a known failure, or null when the message is not one we recognise. */
export function knownError(error: string): FriendlyError | null {
  return ERRORS.find(([re]) => re.test(error))?.[1] ?? null;
}

export function friendlyError(error: string | null | undefined): FriendlyError {
  if (!error) return { title: "The analysis stopped.", advice: "Ask the assistant why, or start it again." };
  const known = knownError(error);
  if (known) return known;
  return { title: "The analysis stopped with an error.", advice: "See the technical details below, or ask the assistant why it failed." };
}

// --- data & assistant ------------------------------------------------------

export const ROLE_LABEL: Record<string, string> = {
  measured_pattern: "Measured scan", reference_structure: "Reference structure", reference_value: "Reference value",
};

export function datasetLabel(d: Pick<DatasetNode, "id" | "material" | "role">): string {
  return d.material ? `${d.material} · ${ROLE_LABEL[d.role ?? ""]?.toLowerCase() ?? "dataset"}` : d.id;
}

const TOOLS: Record<string, string> = {
  list_datasets: "your datasets", get_dataset: "a dataset", check_dataset_metadata: "dataset documentation",
  list_runs: "past analyses", get_run: "an analysis", query_metrics: "measured values", compare_runs: "two analyses",
  read_artifact: "a result file", search_knowledge: "earlier reports and notes", start_run: "a new analysis",
  list_dft_sets: "simulations", get_dft_set: "a simulation",
  compare_pattern: "a pattern comparison", identify_phase: "phase identification",
};
export const toolLabel = (name: string) => TOOLS[name] ?? name.replaceAll("_", " ");

/** Radiation as people write it: CuKa1 and CIF's 'Cu K\a~1~' both read "Cu Kα1"; anything else is shown as given. */
export function radiationLabel(r?: string | null): string | null {
  if (!r) return null;
  const m = r.trim().replace(/^'|'$/g, "").match(/^([A-Z][a-z]?)\s*K\s*(?:\\a|a|α)\s*(?:~?([12])~?)?$/);
  return m ? `${m[1]} Kα${m[2] ?? ""}` : r;
}

/** One line telling scans apart: radiation type or source, and the wavelength. */
export function instrumentLine(i?: { radiation?: string | null; radiation_source?: string | null; wavelength_A?: number | null } | null): string {
  if (!i) return "";
  const what = [radiationLabel(i.radiation), i.radiation_source].filter(Boolean).join(", ");
  const parts = [what ? what.charAt(0).toUpperCase() + what.slice(1) : null, i.wavelength_A != null ? `λ ${i.wavelength_A} Å` : "wavelength unknown"];
  return parts.filter(Boolean).join(" · ");
}
