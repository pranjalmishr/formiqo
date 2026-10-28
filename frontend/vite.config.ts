import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
export default defineConfig({ plugins: [react()], server: { proxy: { '/api': process.env.RESUMEAI_API_URL || 'http://127.0.0.1:8010' } }, test: { environment: 'jsdom', setupFiles: './src/test-setup.ts' } });
