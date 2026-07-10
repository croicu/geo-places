import { defineConfig } from "vite";

// Local dev-only static server for out/ — the exact deploy artifact `cd.yaml` publishes
// to Cloudflare Pages via wrangler. Lets geo-browser's own dev server fetch from a
// separate local origin (http://localhost:5174) instead of geo-places.croicu.com,
// mirroring the real two-origin production topology. Never built/bundled — out/ is
// served as-is; run `npm run serve` after `build.sh` has populated out/.
export default defineConfig({
  root: "out",
  publicDir: false,
  server: {
    port: 5174,
    strictPort: true,
    cors: true,
  },
});
