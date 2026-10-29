import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiTarget = new URL(env.VITE_DEV_API_URL || env.VITE_API_URL || 'http://127.0.0.1:8000');
  if (apiTarget.hostname === 'localhost') apiTarget.hostname = '127.0.0.1';
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: apiTarget.origin,
          changeOrigin: true,
        },
      },
    },
  };
});
