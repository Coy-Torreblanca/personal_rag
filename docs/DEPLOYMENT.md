# Testing

Run the following to load env vars in this terminal.
```bash
export $(grep -v '^#' .env | xargs)
```

# Podman Compose

From root project dir, run the following to spin up the containers (or redploy).

```bash
podman-compose down
podman-compose --env-file .env up -d --build  workers api
```
