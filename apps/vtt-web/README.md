# Echo Vault Solo Table

A responsive vinext browser table for the original deterministic Echo Vault encounter.
The UI reads only the public VTT session projection, stages preview commands, and refreshes
the authoritative view after each commit.

## Local development

```bash
npm install
npm run dev
```

The browser client uses `http://127.0.0.1:8000` as its default VTT API base. To point it
at another gateway, set `NEXT_PUBLIC_VTT_API_BASE_URL` in a local ignored `.env` file:

```bash
NEXT_PUBLIC_VTT_API_BASE_URL=http://127.0.0.1:8000
```

The API must expose `GET /api/v1/session` and `POST /api/v1/commands` and allow the
frontend origin through its exact CORS allowlist.

## Verification

```bash
npm test
npm run lint
```

The project preserves the Sites vinext/Vite/Cloudflare Worker structure. No durable browser
state is used; session authority remains in the Python VTT service.
