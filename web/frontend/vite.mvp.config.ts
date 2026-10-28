import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Explicit local build; never loads repository .env or demo fixtures.
export default defineConfig({
  envDir: false,
  plugins: [react()],
  define: {
    'import.meta.env.VITE_LOCAL_PLANNER_MVP': JSON.stringify('1'),
    'import.meta.env.VITE_API_URL': JSON.stringify('/api/v1'),
  },
  build: { outDir: 'dist-mvp', sourcemap: false },
  server: { host: '127.0.0.1', strictPort: true },
})
