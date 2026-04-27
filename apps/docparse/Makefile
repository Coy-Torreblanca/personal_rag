.PHONY: help install install-dev test lint format clean run docker-build docker-run

help:
	@echo "DocParse - Development Commands"
	@echo ""
	@echo "Available commands:"
	@echo "  make install      - Install production dependencies"
	@echo "  make install-dev  - Install development dependencies"
	@echo "  make test         - Run tests"
	@echo "  make lint         - Run linter"
	@echo "  make format       - Format code"
	@echo "  make clean        - Clean build artifacts"
	@echo "  make run          - Run the application locally"
	@echo "  make docker-build - Build Docker image"
	@echo "  make docker-run   - Run Docker container"

install:
	uv pip install -e .

install-dev:
	uv pip install -e ".[dev]"

test:
	pytest tests/ -v

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +

run:
	uvicorn src.main:app --reload --host 0.0.0.0 --port 8001

docker-build:
	docker build -t docparse:latest .

docker-build-dev:
	docker build -f Dockerfile.dev -t docparse:dev .

docker-run:
	docker run -p 8001:8001 -v $(PWD):/app -e DOCPARSE_PROVIDER=docling docparse:latest

docker-run-dev:
	docker run -p 8001:8001 -v $(PWD):/app -e DOCPARSE_PROVIDER=docling docparse:dev
