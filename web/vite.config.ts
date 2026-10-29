import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // FastAPI: uv run uvicorn smartlading.api:app --port 8000
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
