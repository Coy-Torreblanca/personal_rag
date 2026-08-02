# ==========================================
# STAGE 1: Dependencies
# ==========================================
FROM node:22-slim AS deps

WORKDIR /app

# Copy lockfiles first so the `npm ci` layer stays cached
# across rebuilds as long as dependencies don't change
COPY package.json package-lock.json ./

# Install ALL dependencies (including devDependencies) —
# `next dev` requires TypeScript, Tailwind, ESLint, etc.
RUN npm ci

# ==========================================
# STAGE 2: Runtime (development)
# ==========================================
FROM node:22-slim

WORKDIR /app

# Copy node_modules from the deps stage.
# At runtime, docker-compose.yml bind-mounts ./apps/web:/app and
# declares an anonymous /app/node_modules volume, which gets seeded
# from this directory on first start.
COPY --from=deps /app/node_modules ./node_modules

# Copy the rest of the application source.
# This also makes the image self-sufficient when run WITHOUT the
# compose bind mount (e.g. `podman run -p 3000:3000 30ai-web`).
COPY . .

# Disable Next.js telemetry noise
ENV NEXT_TELEMETRY_DISABLED=1

# NOTE: No USER directive on purpose.
# Podman runs rootless by default: inside the container, UID 0 is
# mapped to your host user, so `next dev` can write the `.next/`
# folder into the bind-mounted ./apps/web directory (see
# docker-compose.yml). A non-root user such as `node` would map to
# an unmapped sub-UID and fail with "permission denied" on that
# bind mount.

EXPOSE 3000

# Dev server with hot reload, listening on all interfaces so the
# 3000:3000 port mapping works from the host
CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0"]
