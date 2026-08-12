import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#b57a00",
          fg: "#ffffff",
        },
        surface: {
          bg: "#f7f6f3",
          fg: "#1a1d23",
          muted: "#5f6773",
          panel: "#ffffff",
          border: "#e2e0da",
        },
        status: {
          ok: "#1e7a45",
          "ok-bg": "#e1f2e7",
          problem: "#b91c1c",
          "problem-bg": "#fbe9e7",
          running: "#1a5dc7",
          "running-bg": "#e8f0fe",
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
