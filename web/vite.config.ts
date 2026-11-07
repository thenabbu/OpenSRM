import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';
import preact from '@preact/preset-vite';

export default defineConfig({
  plugins: [preact(), tailwindcss()],
  // React-shaped libs resolve to preact/compat (accepted ~4 KB gzip trade)
  resolve: { alias: { react: 'preact/compat', 'react-dom': 'preact/compat' } },
  build: {
    outDir: '../app/static/dist',
    emptyOutDir: true,
    manifest: true,
    target: 'es2022',
    cssCodeSplit: true,
    rollupOptions: { input: { app: 'src/main.ts' } },
  },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts', 'src/**/*.test.tsx'] },
});
