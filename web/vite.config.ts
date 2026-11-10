import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';
import preact from '@preact/preset-vite';

export default defineConfig({
  plugins: [preact(), tailwindcss()],
  // React-shaped libs resolve to preact/compat (accepted ~4 KB gzip trade)
  resolve: { alias: { react: 'preact/compat', 'react-dom': 'preact/compat' } },
  // The bundle is served from /static/dist/ (app/views/partials/theme.html
  // points the module at asset_dist('app')). Without this, Vite emits dynamic
  // imports as '/assets/Chunk.js', which Flask does not serve — every island
  // chunk 404s and the app silently renders server markup only. That is why the
  // P6/P7 islands never hydrated in a real browser.
  base: '/static/dist/',
  build: {
    outDir: '../app/static/dist',
    emptyOutDir: true,
    // .vite/manifest.json starts with a dot, and Flask's send_from_directory
    // refuses dotfiles — so the service worker could never fetch it and its
    // precache list was always empty. Emit a plain-named copy instead.
    manifest: 'manifest.json',
    target: 'es2022',
    cssCodeSplit: true,
    rollupOptions: { input: { app: 'src/main.ts' } },
  },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts', 'src/**/*.test.tsx'] },
});
