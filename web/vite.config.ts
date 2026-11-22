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
    // Ours, not esbuild's default: build.target is a JS target and Vite mirrors
    // it onto the CSS pipeline, where es2022 means chrome94/safari15 — neither
    // supports oklch(), so lightningcss downlevels every token to lab() + hex.
    // That is a lossy round-trip of a colour we authored exactly (DESIGN §2.2),
    // and it only became visible once the theme moved out of the inline <style>
    // in partials/theme.html (which nothing ever processed) into this bundle.
    // chrome111 is the first release with oklch; it is the same baseline the
    // app already required, now stated instead of silently degraded.
    cssTarget: 'chrome111',
    cssCodeSplit: true,
    rollupOptions: { input: { app: 'src/main.ts' } },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    // blobatar's gaze driver reads matchMedia (reduced motion) when it mounts.
    // jsdom has no implementation, so every test that renders an avatar threw
    // "matchMedia is not a function" out of a timer, after the assertions ran.
    setupFiles: ['./src/test-setup.ts'],
  },
});
