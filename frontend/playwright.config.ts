import { defineConfig } from '@playwright/test'

// Runs against the real API: start Postgres and `uvicorn backend.app.main:app --port 8100` first
// (or point API_URL at another host before starting Vite).
export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  use: { baseURL: 'http://127.0.0.1:5180' },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1',
    url: 'http://127.0.0.1:5180',
    reuseExistingServer: true,
  },
})
