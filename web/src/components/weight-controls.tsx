"use client";

const WEIGHT_LABELS: Record<string, string> = {
  sonic: "Sonic similarity",
  popularity: "Popularity match",
  style: "Style match",
  genre: "Genre match",
  era: "Era proximity",
  novelty: "Novelty / discovery",
};

export function WeightControls({
  weights,
  presets,
  preset,
  onPresetChange,
  onWeightChange,
}: {
  weights: Record<string, number>;
  presets: Record<string, Record<string, number>>;
  preset: string;
  onPresetChange: (name: string) => void;
  onWeightChange: (key: string, value: number) => void;
}) {
  return (
    <div>
      <div className="flex flex-wrap gap-2 mb-3">
        {Object.keys(presets).map((name) => (
          <button
            key={name}
            type="button"
            className={`text-xs px-2.5 py-1 rounded-full border font-medium cursor-pointer transition-colors ${
              preset === name
                ? "bg-[var(--brand)] text-white border-[var(--brand)]"
                : "bg-transparent text-[var(--muted)] border-[var(--border)] hover:border-[var(--brand)] hover:text-[var(--fg)]"
            }`}
            onClick={() => onPresetChange(name)}
          >
            {name.charAt(0).toUpperCase() + name.slice(1)}
          </button>
        ))}
      </div>

      <div className="grid gap-2.5 max-w-md">
        {(() => {
          const totalWeight = Object.values(weights).reduce((a, b) => a + b, 0) || 1;
          return Object.entries(WEIGHT_LABELS).map(([key, label]) => (
            <div key={key} className="flex items-center gap-3">
              <span className="text-sm text-[var(--muted)] w-32 flex-shrink-0">{label}</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={weights[key] ?? 0}
                onChange={(e) => onWeightChange(key, parseFloat(e.target.value))}
                className="flex-1"
                style={{ accentColor: "var(--brand)", height: 4 }}
              />
              <span className="text-xs text-[var(--muted)] w-8 text-right tabular-nums">
                {(((weights[key] ?? 0) / totalWeight) * 100).toFixed(0)}%
              </span>
            </div>
          ));
        })()}
      </div>
    </div>
  );
}
