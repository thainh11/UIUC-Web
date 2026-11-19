# Frontend

One React page (React 19, Vite, TypeScript, Tailwind, Recharts). Setup, the full stack and the API are described in the [root README](../README.md); page design is in [docs/design.md](../docs/design.md).

| Command | What it does |
|---|---|
| `npm run dev` | Dev server on http://localhost:5180. `/api` is proxied to `API_URL` (default http://localhost:8100) |
| `npm run build` | Type-check and build into `dist/` |
| `npm run lint` | Oxlint |
| `npm test` | Vitest, `src/**/*.test.ts` |
| `npm run e2e` | Playwright + axe against the real API (needs the database and the API on :8100; first run `npx playwright install chromium`) |
| `npm run gen:api` | Regenerate `src/api/schema.d.ts` from the running API's OpenAPI schema |

`src/api/` holds the typed client, `src/lib/` the pure helpers and the chat store, `src/hooks/` data loading, and `src/components/` the sections of the page.
