import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // mobile.test.ts reads App.css as text; vitest otherwise stubs CSS to "".
  test: {
    css: { include: /.+/ },
    // Tests never depend on a developer's .env.local: Firebase sign-in is off
    // unless a test injects a fake auth client (setAuthClient).
    env: {
      VITE_FIREBASE_API_KEY: "",
      VITE_FIREBASE_AUTH_DOMAIN: "",
      VITE_FIREBASE_PROJECT_ID: "",
      VITE_FIREBASE_APP_ID: "",
    },
  },
  server: {
    // Local API proxy; backend port per docs/API.md (assumed 8000 until confirmed)
    proxy: { "/api": process.env.API_TARGET ?? "http://127.0.0.1:8000" },
  },
});
