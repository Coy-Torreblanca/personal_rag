# Database Setup for 30ai Project

This project uses PostgreSQL with the pgvector extension for vector embeddings, and Redis for Celery task queue.

## Prerequisites

1. **Podman** (or Docker) installed
2. **podman-compose** (or docker-compose) installed

### Install Podman on macOS:
```bash
brew install podman
```

### Install podman-compose on macOS:
```bash
brew install podman-compose
```

## Starting the Database

### Option 1: Using the provided scripts
```bash
# Start the database services
./start-db.sh

# Stop the services
./stop-db.sh

# View logs
./logs-db.sh
```

### Option 2: Manual commands
```bash
# Start services
podman-compose up -d

# Stop services
podman-compose down

# View logs
podman-compose logs -f
```

## Database Configuration

### PostgreSQL
- **Host:** localhost
- **Port:** 5432
- **Database:** 30ai_db
- **Username:** 30ai_user
- **Password:** 30ai_password

### Redis
- **Host:** localhost
- **Port:** 6379

## Database Schema

The database is initialized with the following schema:

### 1. `document_chunks` table
Stores text chunks from documents along with their vector embeddings.

### 2. `documents` table
Stores metadata about uploaded documents.

### 3. `organizations` table
Stores organization information (synced from Clerk).

### 4. `users` table
Stores user information (synced from Clerk).

## Connecting to the Database

### Using psql:
```bash
psql -h localhost -p 5432 -U 30ai_user -d 30ai_db
```

### Using a GUI tool:
- **TablePlus:** Connect to PostgreSQL at localhost:5432
- **DBeaver:** Create a new PostgreSQL connection
- **pgAdmin:** Add a new server

## Environment Variables

Copy the example environment file:
```bash
cp .env.example .env
```

Then edit `.env` with your actual configuration values.

## Verifying the Setup

1. Check if PostgreSQL is running:
```bash
podman ps
```

2. Test the connection:
```bash
pg_isready -h localhost -p 5432 -U 30ai_user -d 30ai_db
```

3. Verify pgvector extension is installed:
```bash
psql -h localhost -p 5432 -U 30ai_user -d 30ai_db -c "SELECT * FROM pg_available_extensions WHERE name = 'vector';"
```

## Troubleshooting

### Port already in use
If port 5432 is already in use, modify the port mapping in `docker-compose.yml`:
```yaml
ports:
  - "5433:5432"  # Change external port to 5433
```

### Permission issues
If you encounter permission issues with volumes, try:
```bash
podman unshare chown -R 1000:1000 ./postgres_data
```

### Container won't start
Check logs for errors:
```bash
podman-compose logs postgres
```

### pgvector extension not loading
Ensure you're using the correct image: `pgvector/pgvector:pg16`