import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],
  optimizeDeps: { exclude: ["@neuronection/assistant-ui"] },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 3100,
    proxy: {
      "/api": { target: "http://127.0.0.1:8100", changeOrigin: true },
    },
  },
});
