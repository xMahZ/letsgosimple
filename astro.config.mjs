import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";
import sitemap from "@astrojs/sitemap";

export default defineConfig({
  site: "https://letsgosimple.app",
  redirects: {
    // Atajos de desarrollo (no canónicos)
    "/uf-a-clp": "/cl/finanzas/uf-a-clp",
    "/dolar-a-clp": "/cl/finanzas/dolar-a-clp",
    "/algo-mas": "/cl/otra-seccion/pagina",
  },
  vite: {
    plugins: [tailwindcss()],
  },
  integrations: [sitemap()],
});
