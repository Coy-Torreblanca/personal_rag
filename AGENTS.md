# 30ai Project Agents Guide

## Project Structure

This project follows a production-standard monorepo structure:

### Key Directories
- `apps/` - Application code (web, api, workers)
- `packages/` - Shared libraries (database, ai, config, shared)
- `infrastructure/` - Infrastructure as Code
- `scripts/` - Build and deployment scripts

### Getting Started
1. Check `STACK.md` for technology stack
2. Check `PROJECT_STRUCTURE.md` for detailed structure
3. Check `DATABASE_SETUP.md` for database configuration
4. Use `Makefile` for common tasks

### Common Commands
```bash
make setup      # Set up development environment
make dev        # Start all development services (foreground)
make dev-up     # Start development services (background)
make dev-down   # Stop development services
make dev-logs   # View service logs
make db-up      # Start database services only
make test       # Run tests
make lint       # Run linters
```

## Database

PostgreSQL with pgvector extension is configured in `docker-compose.yml`.
Use environment variables for configuration (see `.env.example`).

## Container Runtime

This project uses Podman as the primary container runtime. The Makefile automatically detects
and uses `podman compose` when available, falling back to `docker-compose` if needed.
