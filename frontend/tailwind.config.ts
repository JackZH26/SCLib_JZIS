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
          50:  "#f0f5f0", // --bg         page background
          100: "#e8f0e8", // --surface    section-alt, code bg
          200: "#d4e4d4", // --border     default borders
          300: "#bed3be", // stronger borders / input rings
          400: "#9aaf9a", // disabled / plot grid
          500: "#6b7c6b", // --text-tertiary
          600: "#5a6b5a", // --text-secondary
          700: "#3f4f3f", // button hover (lightens toward accent)
          800: "#3A7D5C", // --accent     buttons use this for hover
          900: "#24503A", // --accent-deep  primary button bg + strong text
        },
        // Semantic aliases for the few places we want to reach directly
        // (gradient endpoints, accent links, badge backgrounds).
        sage: {
          bg:      "#f0f5f0",
          surface: "#e8f0e8",
          card:    "#ffffff",
          border:  "#d4e4d4",
          ink:     "#2d3b2d",
          muted:   "#5a6b5a",
          tertiary:"#6b7c6b",
        },
        accent: {
          DEFAULT: "#3A7D5C",
          deep:    "#24503A",
          light:   "#4ea27a",
        },
      },
      fontFamily: {
        sans: [
          "var(--font-inter)",
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
        "sage-gradient":      "linear-gradient(135deg, #3A7D5C, #24503A)",
        "sage-gradient-text": "linear-gradient(135deg, #3A7D5C, #24503A)",
      },
    },
  },
  plugins: [typography],
};
export default config;
