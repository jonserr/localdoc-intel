import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// The npm "test" script pins NODE_ENV=test. Vitest only defaults NODE_ENV to
// "test" when it is unset, and an inherited NODE_ENV=production makes React
// Testing Library resolve React's production build, which exports no act().

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
  },
});
