// @ts-check
import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  redirects: {
    // Atajos de desarrollo (no canónicos)
    "/uf-a-clp": "/cl/finanzas/uf-a-clp",
    "/dolar-a-clp": "/cl/finanzas/dolar-a-clp",
    "/algo-mas": "/cl/otra-seccion/pagina",
  },
  vite: {
    plugins: [tailwindcss()],
  },
});
