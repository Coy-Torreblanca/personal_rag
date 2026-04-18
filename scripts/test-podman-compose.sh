#!/bin/bash

echo "Testing Podman Compose setup..."
echo "================================"

# Check if podman-compose is available
if command -v podman-compose &> /dev/null; then
    COMPOSE_CMD="podman-compose"
    echo "Using podman-compose"
else
    echo "Error: podman-compose not found. Please install Podman and podman-compose."
    exit 1
fi

# Test 1: Build images
echo ""
echo "1. Building container images..."
$COMPOSE_CMD build --no-cache || {
    echo "❌ Failed to build images"
    exit 1
}
echo "✅ Images built successfully"

# Test 2: Start services
echo ""
echo "2. Starting services..."
$COMPOSE_CMD up -d || {
    echo "❌ Failed to start services"
    exit 1
}

# Wait for services to be ready
echo "Waiting for services to be ready..."
sleep 10

# Test 3: Check if services are running
echo ""
echo "3. Checking service status..."
$COMPOSE_CMD ps || {
    echo "❌ Failed to check service status"
    $COMPOSE_CMD down
    exit 1
}

# Test 4: Check PostgreSQL connection
echo ""
echo "4. Testing PostgreSQL connection..."
if command -v pg_isready &> /dev/null; then
    pg_isready -h localhost -p 5432 -U 30ai_user -d 30ai_db && echo "✅ PostgreSQL is ready" || {
        echo "❌ PostgreSQL is not ready"
        $COMPOSE_CMD logs postgres
        $COMPOSE_CMD down
        exit 1
    }
else
    echo "⚠️  pg_isready not available, skipping PostgreSQL test"
fi

# Test 5: Check Redis connection
echo ""
echo "5. Testing Redis connection..."
if command -v redis-cli &> /dev/null; then
    redis-cli -h localhost -p 6379 ping | grep -q "PONG" && echo "✅ Redis is ready" || {
        echo "❌ Redis is not ready"
        $COMPOSE_CMD logs redis
        $COMPOSE_CMD down
        exit 1
    }
else
    echo "⚠️  redis-cli not available, skipping Redis test"
fi

# Test 6: Check API health endpoint
echo ""
echo "6. Testing API health endpoint..."
sleep 5  # Give API time to start
curl -f http://localhost:8000/health && echo "✅ API is healthy" || {
    echo "❌ API is not healthy"
    $COMPOSE_CMD logs api
    $COMPOSE_CMD down
    exit 1
}

# Test 7: Check API root endpoint
echo ""
echo "7. Testing API root endpoint..."
curl -f http://localhost:8000/ && echo "✅ API root endpoint works" || {
    echo "❌ API root endpoint failed"
    $COMPOSE_CMD down
    exit 1
}

# Test 8: Stop services
echo ""
echo "8. Stopping services..."
$COMPOSE_CMD down && echo "✅ Services stopped successfully" || {
    echo "❌ Failed to stop services"
    exit 1
}

echo ""
echo "==============================="
echo "✅ All tests passed! Podman Compose setup is working correctly."
echo ""
echo "To start services for development:"
echo "  make db-up"
echo ""
echo "To start all services (API, Workers, Web):"
echo "  $COMPOSE_CMD up -d"
echo ""
echo "To view logs:"
echo "  $COMPOSE_CMD logs -f"
echo ""
echo "To stop services:"
echo "  $COMPOSE_CMD down"