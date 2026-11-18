// Vite: `npm run dev` serves the app on :5173 and forwards /api and /ops to FastAPI on :8000.
// `npm run build` writes frontend/dist, which FastAPI serves in production (backend/api/spa.py).
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://localhost:8000", "/ops": "http://localhost:8000" },
  },
  test: { environment: "jsdom", setupFiles: ["./src/test/setup.js"] },
});
