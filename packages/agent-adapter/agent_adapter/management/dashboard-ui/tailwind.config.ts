import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        text: {
          DEFAULT: "#111111",
          2: "#444444",
          3: "#888888",
          4: "#bbbbbb",
        },
        rose: {
          accent: "#d97059",
        },
        card: "#ffffff",
        input: "#f0ebe4",
        node: {
          active: "#1a1410",
          demo: "#888888",
        },
        track: "#1a1410",
        success: {
          bg: "#dcfce7",
          fg: "#16a34a",
        },
      },
      fontFamily: {
        sans: [
          "degular-variable",
          "degular",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "SF Mono",
          "Consolas",
          "Liberation Mono",
          "Menlo",
          "monospace",
        ],
      },
      borderColor: {
        DEFAULT: "rgba(0, 0, 0, 0.1)",
        mid: "rgba(0, 0, 0, 0.15)",
        strong: "rgba(0, 0, 0, 0.22)",
      },
      boxShadow: {
        subtle: "0 1px 3px #0000000f",
        button: "0 1px 3px #0000001f",
        elevated: "0 1px 3px #0000000f, 0 1px 2px #0000000a",
        card: "0 2px 12px #0000000f, 0 1px 3px #0000000a",
        "hover-elevated":
          "0 4px 14px #00000014, 0 1px 3px #0000000d",
        "button-hover":
          "0 4px 14px #0000001f, 0 1px 4px #0000000f",
        "focus-form":
          "0 4px 24px #0000001a, 0 1px 4px #0000000d",
        "focus-ring": "0 0 0 3px #0000000f",
      },
      borderRadius: {
        DEFAULT: "10px",
      },
      maxWidth: {
        container: "1320px",
      },
      keyframes: {
        fadeUp: {
          "0%": { opacity: "0", transform: "translateY(18px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
      },
      animation: {
        "fade-up": "fadeUp 0.55s cubic-bezier(.22,1,.36,1) both",
        "fade-in": "fadeIn 0.5s ease both",
      },
    },
  },
  plugins: [],
} satisfies Config;
