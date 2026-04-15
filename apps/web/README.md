# LoopLM Web

Next.js frontend for LoopLM.

## Development

From the repo root:

```bash
pnpm install
pnpm --filter @looplm/web dev
```

The app runs on `http://localhost:3100` in local development.

## Environment

The frontend primarily depends on:

- `NEXT_PUBLIC_API_URL`
- `NEXT_PUBLIC_REPOSITORY_URL` (optional)

For full setup, use the repo-root `.env.example` and the main `README.md`.
