import { ArrowRight } from "lucide-react";

// A diffraction trace across the page in the logo's colours: sharp Bragg peaks on a flat background.
const PEAKS = [[90, 70], [150, 140], [205, 55], [262, 190], [330, 80], [372, 120], [440, 60], [505, 230], [560, 95],
  [622, 150], [690, 70], [748, 110], [820, 260], [880, 85], [944, 130], [1010, 65], [1075, 175], [1130, 90]];
const TRACE = (() => {
  const base = 300, pts: string[] = [];
  for (let x = 0; x <= 1200; x += 2) {
    let y = 0;
    for (const [c, h] of PEAKS) y += h / (1 + ((x - c) / 3.2) ** 2);
    pts.push(`${x},${(base - y).toFixed(1)}`);
  }
  return `M${pts.join(" L")}`;
})();

/** The front door: the logo and one way in. */
export function Landing({ onEnter }: { onEnter: () => void }) {
  return (
    <main className="landing relative flex min-h-full flex-col items-center justify-center overflow-hidden px-4">
      <div aria-hidden className="landing-glow pointer-events-none absolute inset-0" />
      <div aria-hidden className="landing-grid pointer-events-none absolute inset-0" />
      <svg aria-hidden viewBox="0 0 1200 320" preserveAspectRatio="none"
        className="pointer-events-none absolute inset-x-0 bottom-[3vh] h-[16vh] w-full opacity-60">
        <defs>
          <linearGradient id="trace" x1="0" x2="1">
            <stop offset="0" stopColor="#ff7a1a" /><stop offset="0.45" stopColor="#e23ad8" />
            <stop offset="0.65" stopColor="#7b4dff" /><stop offset="1" stopColor="#22b8ff" />
          </linearGradient>
          <filter id="soft"><feGaussianBlur stdDeviation="2.2" /></filter>
        </defs>
        <path d={TRACE} fill="none" stroke="url(#trace)" strokeWidth="4" filter="url(#soft)" opacity="0.5" />
        <path d={TRACE} className="landing-trace" fill="none" stroke="url(#trace)" strokeWidth="1.6" pathLength={1} />
      </svg>

      <img src="/logo.webp" alt="CoRefine" width={1400} height={840}
        className="landing-logo relative w-[min(86vw,760px)] select-none" draggable={false} />

      <button onClick={onEnter} className="landing-enter group relative mt-[6vh] rounded-full p-px">
        <span className="flex items-center gap-2 rounded-full bg-[#0b0d18]/90 px-7 py-3 text-[15px] font-medium text-white backdrop-blur">
          Go to app <ArrowRight size={17} className="transition group-hover:translate-x-0.5" />
        </span>
      </button>
    </main>
  );
}
