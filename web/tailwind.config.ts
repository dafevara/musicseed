import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "var(--ms-accent)",
          fg: "var(--ms-text)",
        },
        surface: {
          bg: "var(--ms-canvas)",
          fg: "var(--ms-text)",
          muted: "var(--ms-text-muted)",
          panel: "var(--ms-surface)",
          border: "var(--ms-border)",
        },
        status: {
          ok: "var(--ms-success)",
          "ok-bg": "var(--ms-success-soft)",
          problem: "var(--ms-danger)",
          "problem-bg": "var(--ms-danger-soft)",
          running: "var(--ms-info)",
          "running-bg": "var(--ms-info-soft)",
        },
      },
      fontSize: {
        xs: "0.72rem",
        sm: "0.85rem",
        base: "0.95rem",
        lg: "1.1rem",
        xl: "1.25rem",
        "2xl": "1.5rem",
      },
    },
  },
  plugins: [],
} satisfies Config;
