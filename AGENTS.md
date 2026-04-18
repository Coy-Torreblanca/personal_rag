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
make dev        # Start development services
make db-up      # Start database services
make test       # Run tests
make lint       # Run linters
```

## Database

PostgreSQL with pgvector extension is configured in `docker-compose.yml`.
Use environment variables for configuration (see `.env.example`).
