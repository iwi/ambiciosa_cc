/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The build goes into the Python package so `ambiciosa serve` can serve it.
// During development, `npm run dev` proxies /api to a running `ambiciosa serve`.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../ambiciosa/web_dist", emptyOutDir: true },
  server: { proxy: { "/api": "http://localhost:8000" } },
  test: { environment: "jsdom" },
});
