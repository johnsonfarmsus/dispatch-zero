# Dispatch Zero

Location-based adventure quest app. See [`dispatch-zero_project_document.md`](dispatch-zero_project_document.md) for the full product spec.

## Local dev

```bash
cp .env.example .env  # then fill secrets
docker compose up
# app at http://localhost:8000/healthz
```

## Deploy

```bash
./deploy/deploy.sh
```

Targets VPS 2 (`89.167.39.152`).
