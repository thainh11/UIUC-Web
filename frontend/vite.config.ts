import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const API_TARGET = process.env.API_URL ?? 'http://localhost:8100'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5180, proxy: { '/api': API_TARGET } },
  preview: { port: 5180, proxy: { '/api': API_TARGET } },
  test: { include: ['src/**/*.test.ts'] },
})
