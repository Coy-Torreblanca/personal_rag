# 30ai - AI-Powered Business Intelligence Platform

30ai is a modern web application that leverages AI to analyze business documents, extract insights, and provide intelligent recommendations.

## 🚀 Features

- **Document Intelligence**: Upload and analyze business documents (PDFs, Word, Excel)
- **AI-Powered Insights**: Extract key information using LLMs
- **Vector Search**: Semantic search across document collections
- **Multi-tenant Architecture**: Support for multiple organizations
- **Real-time Processing**: Background task processing with Celery
- **Modern Stack**: Next.js, FastAPI, PostgreSQL with pgvector, Redis

## 🏗️ Architecture

### Frontend
- **Framework**: Next.js 14 (App Router)
- **Styling**: Tailwind CSS + shadcn/ui
- **State Management**: React Context + SWR
- **Authentication**: Clerk

### Backend
- **API Framework**: FastAPI (Python)
- **Database**: PostgreSQL with pgvector extension
- **Task Queue**: Celery with Redis
- **AI Integration**: LiteLLM, OpenAI, Anthropic
- **Document Parsing**: Unstructured.io

### Infrastructure
- **Containerization**: Docker + Podman
- **Orchestration**: Docker Compose
- **Deployment**: Render/Railway (Backend), Vercel (Frontend)

## 📁 Project Structure

```
30ai/
├── apps/                      # Application code
│   ├── web/                  # Next.js frontend
│   ├── api/                  # FastAPI backend
│   └── workers/              # Celery workers
├── packages/                 # Shared packages
│   ├── shared/              # TypeScript utilities
│   ├── database/            # Database models
│   ├── ai/                  # AI utilities
│   └── config/              # Configuration
├── infrastructure/          # Infrastructure as Code
├── scripts/                 # Build/deployment scripts
├── tests/                   # Integration tests
└── docs/                    # Documentation
```

## 🛠️ Getting Started

### Prerequisites

- Node.js 18+ and npm
- Python 3.11+ and uv
- Podman/Docker and docker-compose/podman-compose

### Quick Start

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd 30ai
   ```

2. **Set up environment variables**
   ```bash
   cp .env.example .env.local
   # Edit .env.local with your configuration
   ```

3. **Install dependencies**
   ```bash
   make setup
   ```

4. **Start development services**
   ```bash
   make dev
   ```

5. **Access the applications**
   - Frontend: http://localhost:3000
   - API: http://localhost:8000
   - API Docs: http://localhost:8000/docs

### Development Commands

```bash
# Start database services
make db-up

# Stop database services
make db-down

# Run tests
make test

# Run linters
make lint

# Format code
make format

# Clean build artifacts
make clean
```

## 🐳 Docker Development

The project uses Docker Compose to manage all services:

### Services Included:
1. **PostgreSQL** (port 5432) - Database with pgvector extension
2. **Redis** (port 6379) - Message broker for Celery
3. **API** (port 8000) - FastAPI backend with auto-reload
4. **Workers** - Celery workers for background processing
5. **Web** (port 3000) - Next.js frontend with hot reload

### Using Makefile (Recommended)
```bash
# Start all services
make db-up

# Start development environment (all services)
make dev

# Stop services
make db-down

# Reset database (WARNING: destroys data)
make db-reset
```

### Using Docker Compose Directly
```bash
# Start all services
docker-compose up -d

# Start with rebuild
docker-compose up -d --build

# View logs
docker-compose logs -f

# View logs for specific service
docker-compose logs -f api

# Stop services
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

### Using Podman Compose
```bash
# Start all services
podman-compose up -d

# View logs
podman-compose logs -f

# Stop services
podman-compose down
```

### Testing the Setup
```bash
# Run comprehensive tests
./scripts/test-docker-compose.sh
```

## 📊 Database

### PostgreSQL with pgvector
- **Host**: localhost:5432
- **Database**: 30ai_db
- **Username**: 30ai_user
- **Password**: 30ai_password

### Schema
The database includes:
- `document_chunks` - Text chunks with vector embeddings
- `documents` - Document metadata
- `organizations` - Organization data
- `users` - User information

### Connecting to the Database
```bash
psql -h localhost -p 5432 -U 30ai_user -d 30ai_db
```

## 🔧 Configuration

### Environment Variables
See `.env.example` for all required environment variables:

- **Database**: `DATABASE_URL`, `DB_USER`, `DB_PASSWORD`
- **Redis**: `REDIS_URL`, `REDIS_PASSWORD`
- **Authentication**: `CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`
- **AI Services**: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- **AWS**: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`

## 🧪 Testing

### Backend Tests
```bash
cd apps/api
pytest
```

### Frontend Tests
```bash
cd apps/web
npm test
```

### E2E Tests
```bash
npm run test:e2e
```

## 🚀 Deployment

### Production Deployment
1. Set up production environment variables in `.env.production`
2. Build and push Docker images
3. Deploy to your infrastructure

### Using Docker Compose for Production
```bash
docker-compose -f docker-compose.prod.yml up -d
```

## 📚 Documentation

- [Project Structure](PROJECT_STRUCTURE.md)
- [Database Setup](DATABASE_SETUP.md)
- [Technology Stack](STACK.md)
- [API Documentation](http://localhost:8000/docs)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## 📄 License

This project is proprietary and confidential.

## 🆘 Support

For support, please contact the development team or open an issue in the repository.