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


# Disable Next.js telemetry noise
ENV NEXT_TELEMETRY_DISABLED=1

# 1. Add the -m flag to create a home directory (/home/nextjs) for npm logs
RUN groupadd -r nextjs && useradd -r -m -g nextjs nextjs

# 2. Give the nextjs user explicit ownership of the /app directory
RUN chown -R nextjs:nextjs /app

COPY --from=builder --chown=nextjs:nextjs /app/public ./public
COPY --from=builder --chown=nextjs:nextjs /app/.next ./.next
COPY --from=builder --chown=nextjs:nextjs /app/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nextjs /app/package.json ./package.json
COPY --from=builder --chown=nextjs:nextjs /app/next.config.ts ./next.config.ts

USER nextjs

EXPOSE 3000

# Dev server with hot reload, listening on all interfaces so the
# 3000:3000 port mapping works from the host
CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0"]
