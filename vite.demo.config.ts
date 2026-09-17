import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",
  plugins: [react(), {
    name: "demo-root-entry",
    enforce: "post",
    generateBundle(_options, bundle) {
      const entry = bundle["demo.html"];
      if (entry) { entry.fileName = "index.html"; bundle["index.html"] = entry; delete bundle["demo.html"]; }
    },
  }],
  build: {
    outDir: "demo-dist",
    emptyOutDir: true,
    rollupOptions: { input: "demo.html" },
  },
});
