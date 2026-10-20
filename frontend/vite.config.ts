import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // Frontend configuration is public. Never read the backend's private .env.
  envDir: false,
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    fs: { strict: true, allow: ['.'] },
    proxy: { '/research': { target: 'http://127.0.0.1:8000' }, '/documents': { target: 'http://127.0.0.1:8000' }, '/auth': { target: 'http://127.0.0.1:8000' } },
  },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true },
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'] },
});
