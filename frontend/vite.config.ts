import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: Number(process.env.VITE_PORT ?? 3100),
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.CA_API_PROXY ?? "http://127.0.0.1:8100",
        changeOrigin: true,
      },
      "/mcp": {
        target: process.env.CA_API_PROXY ?? "http://127.0.0.1:8100",
        changeOrigin: true,
      },
    },
  },
});
