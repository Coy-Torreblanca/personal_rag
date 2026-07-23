# Podman Compose

From root project dir, run the following to spin up the containers (or redploy).

```bash
podman stop 30ai-api
podman stop 30ai-workers
podman rm 30ai-api
podman rm 30ai-workers
podman-compose --env-file .env up -d --build  workers api
```


