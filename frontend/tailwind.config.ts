import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0a0d14",
          900: "#111622",
          800: "#1a2131",
          700: "#26304360",
        },
      },
    },
  },
  plugins: [],
};

export default config;
