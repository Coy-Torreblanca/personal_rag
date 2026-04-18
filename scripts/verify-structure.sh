#!/bin/bash

echo "Verifying 30ai project structure..."
echo "=================================="

# Check required directories
required_dirs=(
    ".github/workflows"
    "apps/web"
    "apps/api"
    "apps/workers"
    "packages/shared"
    "packages/database"
    "packages/ai"
    "packages/config"
    "infrastructure/docker"
    "infrastructure/kubernetes"
    "infrastructure/terraform"
    "scripts"
    "docs"
    "tests"
)

echo "Checking directory structure..."
for dir in "${required_dirs[@]}"; do
    if [ -d "$dir" ]; then
        echo "✓ $dir"
    else
        echo "✗ $dir (missing)"
    fi
done

echo ""
echo "Checking required files..."
required_files=(
    ".gitignore"
    "Makefile"
    "README.md"
    "PROJECT_STRUCTURE.md"
    "DATABASE_SETUP.md"
    "STACK.md"
    ".env.example"
    "docker-compose.yml"
    "docker-compose.prod.yml"
    "apps/api/pyproject.toml"
    "apps/api/Dockerfile"
    "apps/api/Dockerfile.dev"
    "apps/web/package.json"
    "apps/web/Dockerfile"
    "apps/web/Dockerfile.dev"
    "packages/database/pyproject.toml"
    "packages/ai/pyproject.toml"
)

for file in "${required_files[@]}"; do
    if [ -f "$file" ]; then
        echo "✓ $file"
    else
        echo "✗ $file (missing)"
    fi
done

echo ""
echo "Checking executable scripts..."
if [ -x "start-db.sh" ] && [ -x "stop-db.sh" ] && [ -x "logs-db.sh" ]; then
    echo "✓ Database scripts are executable"
else
    echo "✗ Some database scripts are not executable"
fi

echo ""
echo "Structure verification complete!"
echo ""
echo "Next steps:"
echo "1. Copy .env.example to .env.local"
echo "2. Run 'make setup' to install dependencies"
echo "3. Run 'make dev' to start development services"