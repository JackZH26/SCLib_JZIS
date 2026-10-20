import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

/* SCLib owns this sage palette. The slate aliases preserve existing data UI. */
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Existing data components use these sage aliases.
        slate: {
          50:  "#f7f5ef", // --bg         page background
          100: "#e8eddf", // --surface    section-alt, code bg
          200: "#d8ded2", // --border     default borders
          300: "#bed3be", // stronger borders / input rings
          400: "#9aaf9a", // disabled / plot grid
          500: "#637166", // --text-tertiary
          600: "#536257", // --text-secondary
          700: "#3f4f3f", // button hover (lightens toward accent)
          800: "#2d654f", // --accent     buttons use this for hover
          900: "#204B3C", // --accent-deep  primary button bg + strong text
        },
        // Semantic aliases for the few places we want to reach directly
        // (gradient endpoints, accent links, badge backgrounds).
        sage: {
          bg:      "#f7f5ef",
          surface: "#e8eddf",
          card:    "#ffffff",
          border:  "#d8ded2",
          ink:     "#192720",
          muted:   "#536257",
          tertiary:"#637166",
        },
        accent: {
          DEFAULT: "#2d654f",
          deep:    "#204B3C",
          light:   "#4ea27a",
        },
      },
      fontFamily: {
        sans: [
          "var(--font-manrope)",
          "-apple-system",
          "BlinkMacSystemFont",
          "Inter",
          "Segoe UI",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "SF Mono",
          "Menlo",
          "Monaco",
          "Courier New",
          "monospace",
        ],
      },
      boxShadow: {
        sage:      "0 2px 8px rgba(36, 80, 58, 0.06)",
        "sage-lg": "0 8px 24px rgba(36, 80, 58, 0.14)",
      },
      backgroundImage: {
        "sage-gradient":      "linear-gradient(135deg, #2d654f, #204B3C)",
        "sage-gradient-text": "linear-gradient(135deg, #2d654f, #204B3C)",
      },
    },
  },
  plugins: [typography],
};
export default config;
