import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev server runs inside the `frontend` container. host:true binds 0.0.0.0
// so it is reachable from the host; port 8080 matches FRONTEND_PORT / CORS.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port: 8080,
  },
});
