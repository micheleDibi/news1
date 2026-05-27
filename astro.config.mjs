import { defineConfig } from "astro/config";
import tailwind from "@astrojs/tailwind";
import react from "@astrojs/react";

import node from "@astrojs/node";

export default defineConfig({
  integrations: [tailwind(), react()],
  output: "server", // This enables both static and server rendering
  adapter: node({
    mode: "standalone",
  }),
  devToolbar: {
    enabled: false, // This disables the Astro mini menu
  },
  // Disabilita CSRF check di Astro: dietro Cloudflare + nginx il confronto
  // Origin/Host fallisce (Astro vede Host=127.0.0.1:4000 e blocca POST come
  // "Cross-site POST form submissions are forbidden"). Le rotte admin sono
  // gia' protette da auth Supabase, quindi il check e' ridondante.
  security: {
    checkOrigin: false,
  },
  server: {
    host: "0.0.0.0", // Bind to all interfaces to allow external access
    port: 80, // Listen on port 80
  },
  vite: {
    optimizeDeps: {
      exclude: [".git"],
    },
    server: {
      fs: {
        deny: [".git"],
      },
    },
    build: {
      serverEntry: "entry.mjs",
    },
  },
});
