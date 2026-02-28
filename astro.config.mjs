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
