import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiTarget = process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": apiTarget,
      "/health": apiTarget,
    },
  },
});