import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  envDir: false,
  build: { sourcemap: false },
  plugins: [react()],
  server: { port: 5173 },
})

