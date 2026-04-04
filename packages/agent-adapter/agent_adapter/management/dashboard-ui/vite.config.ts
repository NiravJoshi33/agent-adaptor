import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  base: "/dashboard/",
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: "../dashboard-dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/manage": "http://127.0.0.1:8080",
      "/webhooks": "http://127.0.0.1:8080",
    },
  },
});
