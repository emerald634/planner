import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';

// No proxy to the planner API. This server is a local visual preview only.
export default defineConfig(({ mode }) => ({
  root: fileURLToPath(new URL('.', import.meta.url)),
  envDir: false,
  server: { host: '127.0.0.1', port: 5174, strictPort: true },
  preview: { host: '127.0.0.1', port: 5175, strictPort: true },
  build: { outDir: 'dist', sourcemap: false, emptyOutDir: true },
  plugins: [{
    name: 'isolated-desktop-preview',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = (request.url || '').split('?')[0];
        const localHost = /^(127\.0\.0\.1|localhost)(:\d+)?$/.test(request.headers.host || '');
        if (!localHost || path.startsWith('/api') || (mode !== 'desktop-demo' && /demo|fixtures|App\.tsx/.test(path))) {
          response.statusCode = 403; response.end('Unavailable in isolated desktop preview'); return;
        }
        next();
      });
    },
  }],
}));
