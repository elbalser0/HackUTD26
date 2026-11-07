import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // mobile.test.ts reads App.css as text; vitest otherwise stubs CSS to "".
  test: { css: { include: /.+/ } },
  server: {
    // Local API proxy; backend port per docs/API.md (assumed 8000 until confirmed)
    proxy: { "/api": process.env.API_TARGET ?? "http://127.0.0.1:8000" },
  },
});
