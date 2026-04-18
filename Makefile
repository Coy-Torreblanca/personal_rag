# 30ai Project Makefile

.PHONY: help setup dev dev-up dev-down dev-logs build test lint format clean db-up db-down db-reset db-init db-migrate db-upgrade db-downgrade db-history db-current deploy-staging deploy-production

# Default target
help:
	@echo "30ai Project Management"
	@echo ""
	@echo "Available commands:"
	@echo "  make setup      - Set up development environment"
	@echo "  make dev        - Start all development services (api, web, workers, db) in foreground"
	@echo "  make dev-up     - Start development services in background"
	@echo "  make dev-down   - Stop development services"
	@echo "  make dev-logs   - Show logs for development services"
	@echo "  make build      - Build all services"
	@echo "  make test       - Run all tests"
	@echo "  make lint       - Run linters on all code"
	@echo "  make format     - Format all code"
	@echo "  make clean      - Clean build artifacts"
	@echo "  make db-up      - Start database services only"
	@echo "  make db-down    - Stop database services only"
	@echo "  make db-reset   - Reset database (WARNING: destroys data)"
	@echo "  make db-init    - Initialize database with Alembic"
	@echo "  make db-migrate - Create new migration"
	@echo "  make db-upgrade - Apply migrations"
	@echo "  make db-downgrade - Revert last migration"
	@echo "  make db-history - Show migration history"
	@echo "  make db-current - Show current migration"
	@echo "  make deploy-staging - Deploy to staging"
	@echo "  make deploy-production - Deploy to production"
	@echo ""

# Development setup
setup:
	@echo "Setting up development environment..."
	@cp .env.example .env.local
	@echo "Please edit .env.local with your configuration"
	@echo "Installing Python dependencies..."
	@cd apps/api && uv sync
	@cd apps/workers && uv sync
	@echo "Installing Node.js dependencies..."
	@cd apps/web && npm install
	@echo "Setup complete!"

# Start all development services (foreground)
dev:
	@echo "Starting all development services..."
	@if command -v podman-compose &> /dev/null; then \
		podman-compose up; \
	elif command -v docker-compose &> /dev/null; then \
		docker-compose up; \
	else \
		echo "Error: Neither podman-compose nor docker-compose found."; \
		exit 1; \
	fi

# Start development services in background
dev-up:
	@echo "Starting development services in background..."
	@if command -v podman-compose &> /dev/null; then \
		podman-compose up -d; \
	elif command -v docker-compose &> /dev/null; then \
		docker-compose up -d; \
	else \
		echo "Error: Neither podman-compose nor docker-compose found."; \
		exit 1; \
	fi
	@echo "Services started! Use 'make dev-logs' to view logs."

# Stop development services
dev-down:
	@echo "Stopping development services..."
	@if command -v podman-compose &> /dev/null; then \
		podman-compose down; \
	elif command -v docker-compose &> /dev/null; then \
		docker-compose down; \
	else \
		echo "Error: Neither podman-compose nor docker-compose found."; \
		exit 1; \
	fi
	@echo "Services stopped!"

# Show logs for development services
dev-logs:
	@echo "Showing logs for development services..."
	@if command -v podman-compose &> /dev/null; then \
		podman-compose logs -f; \
	elif command -v docker-compose &> /dev/null; then \
		docker-compose logs -f; \
	else \
		echo "Error: Neither podman-compose nor docker-compose found."; \
		exit 1; \
	fi

# Build all services
build:
	@echo "Building services..."
	@cd apps/web && npm run build
	@echo "Build complete!"

# Run tests
test:
	@echo "Running tests..."
	@cd apps/api && pytest
	@cd apps/web && npm test
	@echo "Tests complete!"

# Run linters
lint:
	@echo "Running linters..."
	@cd apps/api && ruff check .
	@cd apps/api && mypy .
	@cd apps/web && npm run lint
	@echo "Linting complete!"

# Format code
format:
	@echo "Formatting code..."
	@cd apps/api && ruff format .
	@cd apps/web && npm run format
	@echo "Formatting complete!"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	@cd apps/web && rm -rf .next node_modules
	@cd apps/api && rm -rf __pycache__ .pytest_cache
	@cd apps/workers && rm -rf __pycache__
	@echo "Clean complete!"

# Database management
db-up:
	@echo "Starting database services only..."
	@if command -v podman-compose &> /dev/null; then \
		podman-compose up -d postgres redis; \
	elif command -v docker-compose &> /dev/null; then \
		docker-compose up -d postgres redis; \
	else \
		echo "Error: Neither podman-compose nor docker-compose found."; \
		exit 1; \
	fi
	@sleep 5
	@echo "Database services started!"

db-down:
	@echo "Stopping database services only..."
	@if command -v podman-compose &> /dev/null; then \
		podman-compose stop postgres redis; \
	elif command -v docker-compose &> /dev/null; then \
		docker-compose stop postgres redis; \
	else \
		echo "Error: Neither podman-compose nor docker-compose found."; \
		exit 1; \
	fi
	@echo "Database services stopped!"

db-reset: db-down
	@echo "Resetting database..."
	@if command -v podman &> /dev/null; then \
		podman volume rm 30ai_postgres_data 2>/dev/null || true; \
		podman volume rm 30ai_redis_data 2>/dev/null || true; \
	elif command -v docker &> /dev/null; then \
		docker volume rm 30ai_postgres_data 2>/dev/null || true; \
		docker volume rm 30ai_redis_data 2>/dev/null || true; \
	fi
	@echo "Database reset complete!"

# Alembic migrations
db-init:
	@echo "Initializing database with Alembic..."
	@cd apps/api && alembic upgrade head
	@echo "Database initialized!"

db-migrate:
	@echo "Creating new migration..."
	@cd apps/api && alembic revision --autogenerate -m "$(message)"
	@echo "Migration created!"

db-upgrade:
	@echo "Applying migrations..."
	@cd apps/api && alembic upgrade head
	@echo "Migrations applied!"

db-downgrade:
	@echo "Reverting migrations..."
	@cd apps/api && alembic downgrade -1
	@echo "Migration reverted!"

db-history:
	@echo "Migration history:"
	@cd apps/api && alembic history

db-current:
	@echo "Current migration:"
	@cd apps/api && alembic current

# Production deployment
deploy-staging:
	@echo "Deploying to staging..."
	# Add your deployment commands here

deploy-production:
	@echo "Deploying to production..."
	# Add your deployment commands here

