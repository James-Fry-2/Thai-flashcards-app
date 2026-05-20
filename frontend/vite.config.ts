import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  build: {
    // Outputs to /app/static inside Docker (the Dockerfile copies from /app/dist)
    // Use 'dist' for Docker compatibility; the Dockerfile COPY handles the rename
    outDir: 'dist',
    emptyOutDir: true,
  },
})
