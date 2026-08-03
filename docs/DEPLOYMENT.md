# Installation and Deployment

## Installation

```bash
brew install podman
brew install podman-compose
```

## Compose file layout

The project follows a single base file + overrides pattern, so dev and prod
share one config without duplication:

| File                          | Purpose                                            |
| ----------------------------- | -------------------------------------------------- |
| `docker-compose.yml`          | Base config, shared by both environments           |
| `docker-compose.override.yml` | Dev overrides — auto-loaded by `podman-compose up` |
| `docker-compose.prod.yml`     | Prod overrides — loaded explicitly with `-f`       |

Dev runs the base + override files. Prod runs the base + prod files; the dev
override file is **not** loaded when explicit `-f` flags are given.

## Configuration

### Dev

Create a `.env` file in the repo root (gitignored). Example:

```
## 30AI
R2_ACCOUNT_ID=<some_value>
R2_S3_API=<some_value>
R2_TOKEN_VALUE=<some_value>
R2_ACCESS_ID=<some_value>
R2_SECRET_ACCESS_KEY=<some_value>
BUCKET_NAME=30aidev
MODAL_TOKEN_ID=<some_value>
MODAL_TOKEN_SECRET=<some_value>
OPENAI_API_KEY=<some_value>
COHERE_API_KEY=<some_value>
LOG_LEVEL=DEBUG
DEEPSEEK_API_KEY=<some_value>
NEXT_PUBLIC_API_URL=http://localhost:8000
CORS_ALLOWED_ORIGINS=http://localhost:3000
```

`NEXT_PUBLIC_API_URL` and `CORS_ALLOWED_ORIGINS` default to
`http://localhost:8000` / `http://localhost:3000`; set them to your Tailscale
IP if you browse the dev site from other machines, e.g.
`CORS_ALLOWED_ORIGINS=http://100.73.123.10:3000` (comma-separated list
allowed, and the API matches full origins exactly).

### Production

Create a `.env.prod` file in the repo root (gitignored). It needs everything
from the dev example, plus production values:

- `NEXT_PUBLIC_API_URL` — public URL clients use to reach the API
  (required; baked into the web build)
- `CORS_ALLOWED_ORIGINS` — comma-separated **full origins** the API should
  accept, e.g. `https://app.example.com` (required)

## Deployment

From the repo root.

### Dev

```bash
podman-compose down
podman-compose up -d --build
```

The dev override file is picked up automatically; nothing else to pass.

### Production

```bash
podman-compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml down
podman-compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Validate the merged config before deploying:

```bash
podman-compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml config
```

### What production changes vs dev

- No bind mounts — containers run the code baked in at build time
- `web` is built with `apps/web/Dockerfile.prod` (`next build` + `next start`)
  instead of the dev server
- `ENVIRONMENT=production` on api/workers
- Postgres and Redis are **not** exposed on host ports
- Postgres data lives in `./docker_data/postgres_data` — the **same bind
  mount in dev and prod** (gitignored; back it up separately)
- Services restart automatically (`restart: unless-stopped`)

## Testing

Run the following to load env vars in this terminal.

```bash
export $(grep -v '^#' .env | xargs)
```

