import path from "path";
import { defineConfig } from "vitest/config";

// Mirrors the `paths` block of tsconfig.json. The most specific prefixes must come first.
export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
  },
  resolve: {
    alias: [
      { find: /^@\/app\/(.*)/, replacement: path.resolve(__dirname, "./app/$1") },
      { find: /^@\/helpers\/(.*)/, replacement: path.resolve(__dirname, "./helpers/$1") },
      { find: /^@\/styles\/(.*)/, replacement: path.resolve(__dirname, "./styles/$1") },
      { find: /^@\/(.*)/, replacement: path.resolve(__dirname, "./core/$1") },
    ],
  },
});
