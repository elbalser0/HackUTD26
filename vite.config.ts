import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Local API proxy; backend port per docs/API.md (assumed 8000 until confirmed)
    proxy: { "/api": process.env.API_TARGET ?? "http://127.0.0.1:8000" },
  },
});
