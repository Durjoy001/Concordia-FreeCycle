import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      // Keeps photo <img src="/uploads/..."> working in dev without CORS.
      '/uploads': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
