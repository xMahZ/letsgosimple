// @ts-check
import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  redirects: {
    // Atajos de desarrollo (no canónicos)
    "/uf-a-clp": "/cl/finanzas/uf-a-clp",
    "/otra-ruta": "/cl/finanzas/otra-pagina",
    "/algo-mas": "/cl/otra-seccion/pagina",
  },
  vite: {
    plugins: [tailwindcss()],
  },
});
