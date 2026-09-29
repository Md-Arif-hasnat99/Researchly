/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    // Enable CSS code splitting
    cssCodeSplit: true,
    // Reduce chunk size warning threshold (default 500KB)
    chunkSizeWarningLimit: 300,
    // Manual chunk splitting for better caching
    rollupOptions: {
      output: {
        manualChunks: {
          // Core React libraries - rarely change
          vendor: ['react', 'react-dom', 'react-router-dom'],
          // Animation library - only needed on Chat page
          animations: ['framer-motion'],
          // Icons - lazy loaded per component
          icons: ['lucide-react'],
          // Markdown rendering - only needed on Chat page
          markdown: ['react-markdown', 'remark-gfm', 'remark-breaks'],
          // Query library - used across app
          query: ['@tanstack/react-query'],
          // Supabase client
          supabase: ['@supabase/supabase-js'],
        },
      },
    },
    // Use esbuild for faster minification (default in Vite 6+)
    minify: 'esbuild',
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/tests/setup.ts',
    css: true,
  },
});
