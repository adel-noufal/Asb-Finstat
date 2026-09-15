import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Frontend talks to ws://localhost:5173/ws, Vite proxies to the FastAPI backend
      '/ws': { target: 'ws://localhost:8000', ws: true },
      '/artifacts': { target: 'http://localhost:8000' },
    },
  },
})
