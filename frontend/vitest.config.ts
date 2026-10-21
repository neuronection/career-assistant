import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config";

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      globals: true,
      environment: "jsdom",
      setupFiles: ["./src/tests/setup.ts"],
      css: false,
      coverage: {
        provider: "v8",
        reportsDirectory: "./coverage",
        include: ["src/**/*.{ts,tsx}"],
        exclude: ["src/tests/**", "src/types/**"],
        thresholds: {
          statements: 70,
          branches: 66,
          functions: 64,
          lines: 71,
        },
      },
    },
  })
);
