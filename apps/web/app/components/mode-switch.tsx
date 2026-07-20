"use client";

/**
 * Phase 8 mode toggle selector.
 *
 * Toggles between Fast (⚡) and Reasoning (🧠) modes, visually updating and
 * firing callbacks to save mode updates.
 */

interface ModeSwitchProps {
  mode: "fast" | "reasoning";
  onChange: (mode: "fast" | "reasoning") => void;
  disabled?: boolean | undefined;
}

export function ModeSwitch({ mode, onChange, disabled }: ModeSwitchProps) {
  return (
    <div className="inline-flex rounded-xl bg-[#0d1916] p-1 border border-[#28433b]/60">
      <button
        type="button"
        disabled={disabled}
        onClick={() => onChange("fast")}
        className={`flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed ${
          mode === "fast"
            ? "bg-emerald-300/10 text-emerald-300 border border-emerald-300/25"
            : "text-slate-400 hover:text-slate-200"
        }`}
      >
        <span>⚡</span>
        <span>Fast</span>
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={() => onChange("reasoning")}
        className={`flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed ${
          mode === "reasoning"
            ? "bg-emerald-300/10 text-emerald-300 border border-emerald-300/25"
            : "text-slate-400 hover:text-slate-200"
        }`}
      >
        <span>🧠</span>
        <span>Reasoning</span>
      </button>
    </div>
  );
}
