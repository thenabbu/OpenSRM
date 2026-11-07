import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [tailwindcss()],
  build: {
    outDir: '../app/static/dist',
    emptyOutDir: true,
    manifest: true,
    target: 'es2022',
    cssCodeSplit: true,
    rollupOptions: { input: { app: 'src/main.ts' } },
  },
});
