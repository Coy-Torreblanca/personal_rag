# 30ai Project Structure

This document outlines the production-standard directory structure for the 30ai project.

## Root Directory Structure
```
30ai/
├── .github/                    # GitHub workflows and templates
│   ├── workflows/
│   │   ├── ci.yml             # Continuous Integration
│   │   ├── cd.yml             # Continuous Deployment
│   │   └── security-scan.yml  # Security scanning
│   └── ISSUE_TEMPLATE.md      # Issue templates
│
├── apps/                      # Multi-app workspace (monorepo)
│   ├── web/                   # Next.js frontend application
│   ├── api/                   # FastAPI backend application
│   └── workers/               # Celery workers for background tasks
│
├── packages/                  # Shared packages/libraries
│   ├── shared/               # Shared TypeScript/JavaScript code
│   ├── database/             # Database models and migrations
│   ├── ai/                   # AI/ML utilities and models
│   └── config/               # Shared configuration
│
├── infrastructure/           # Infrastructure as Code
│   ├── docker/              # Container configurations (Podman)
│   ├── kubernetes/          # K8s manifests
│   └── terraform/           # Terraform modules
│
├── scripts/                  # Build and deployment scripts
├── docs/                     # Project documentation
├── tests/                    # Integration and E2E tests
├── .env.example             # Environment template
├── .env.local               # Local development env (gitignored)
├── .env.production          # Production env (gitignored)
├── docker-compose.yml       # Local development services (Podman Compose)
├── docker-compose.prod.yml  # Production services (Podman Compose)
├── Makefile                 # Common tasks
├── pyproject.toml          # Python project configuration
├── package.json            # Root package.json (workspace)
├── README.md               # Project overview
└── LICENSE                 # Project license
```

## Detailed Structure

### 1. Frontend (`apps/web/`)
```
apps/web/
├── app/                    # Next.js App Router
│   ├── (auth)/            # Authentication routes
│   ├── (dashboard)/       # Dashboard routes
│   ├── (marketing)/       # Marketing pages
│   ├── api/               # Next.js API routes
│   ├── layout.tsx         # Root layout
│   └── page.tsx           # Home page
├── components/            # React components
│   ├── ui/               # Reusable UI components
│   ├── forms/            # Form components
│   ├── layout/           # Layout components
│   └── ai/               # AI-specific components
├── lib/                   # Frontend utilities
│   ├── api/              # API client
│   ├── auth/             # Authentication utilities
│   ├── utils/            # General utilities
│   └── constants.ts      # Constants
├── styles/               # CSS/SCSS styles
├── public/               # Static assets
├── tests/                # Frontend tests
├── next.config.js        # Next.js configuration
├── tailwind.config.js    # Tailwind configuration
├── tsconfig.json         # TypeScript configuration
└── package.json          # Dependencies
```

### 2. Backend API (`apps/api/`)
```
apps/api/
├── src/
│   ├── main.py           # FastAPI application entry point
│   ├── api/              # API routes
│   │   ├── v1/           # API version 1
│   │   │   ├── __init__.py
│   │   │   ├── auth.py   # Authentication endpoints
│   │   │   ├── documents.py # Document endpoints
│   │   │   ├── embeddings.py # Embedding endpoints
│   │   │   └── organizations.py # Organization endpoints
│   │   └── dependencies.py # FastAPI dependencies
│   ├── core/             # Core application logic
│   │   ├── config.py     # Configuration
│   │   ├── security.py   # Security utilities
│   │   └── exceptions.py # Custom exceptions
│   ├── models/           # Pydantic models
│   ├── schemas/          # Database schemas (SQLAlchemy)
│   ├── services/         # Business logic
│   │   ├── document_service.py
│   │   ├── embedding_service.py
│   │   └── ai_service.py
│   ├── database/         # Database connection and sessions
│   ├── ai/               # AI/ML integration
│   │   ├── embeddings.py # Embedding generation
│   │   ├── llm.py        # LLM interactions
│   │   └── parsers.py    # Document parsing
│   └── workers/          # Celery task definitions
├── tests/                # Backend tests
├── alembic/              # Database migrations
│   ├── versions/         # Migration files
│   └── env.py            # Migration environment
├── Dockerfile            # Production container definition
├── Dockerfile.dev        # Development container definition
├── requirements.txt      # Python dependencies
├── requirements-dev.txt  # Development dependencies
├── pyproject.toml       # Python project config
└── uv.lock              # uv lock file
```

### 3. Workers (`apps/workers/`)
```
apps/workers/
├── src/
│   ├── main.py           # Celery application
│   ├── tasks/            # Celery tasks
│   │   ├── document_tasks.py  # Document processing
│   │   ├── embedding_tasks.py # Embedding generation
│   │   └── ai_tasks.py        # AI processing
│   └── config.py         # Worker configuration
├── tests/
├── Dockerfile
├── requirements.txt
└── pyproject.toml
```

### 4. Shared Packages (`packages/`)
```
packages/
├── shared/               # TypeScript/JavaScript shared code
│   ├── src/
│   │   ├── types/       # TypeScript types
│   │   ├── utils/       # Shared utilities
│   │   └── constants.ts # Shared constants
│   ├── package.json
│   └── tsconfig.json
│
├── database/             # Database models and utilities
│   ├── src/
│   │   ├── models/      # SQLAlchemy models
│   │   ├── migrations/  # Alembic migrations
│   │   └── session.py   # Database session
│   └── pyproject.toml
│
├── ai/                   # AI utilities
│   ├── src/
│   │   ├── embeddings.py
│   │   ├── llm.py
│   │   └── parsers.py
│   └── pyproject.toml
│
└── config/              # Shared configuration
    ├── src/
    │   └── settings.py  # Pydantic settings
    └── pyproject.toml
```

### 5. Infrastructure (`infrastructure/`)
```
infrastructure/
├── docker/
│   ├── postgres/        # PostgreSQL configuration
│   ├── redis/           # Redis configuration
│   └── nginx/           # Nginx configuration
│
├── kubernetes/
│   ├── namespaces/
│   ├── deployments/
│   ├── services/
│   ├── configmaps/
│   └── secrets/
│
└── terraform/
    ├── modules/
    │   ├── vpc/
    │   ├── rds/
    │   ├── ecs/
    │   └── s3/
    └── environments/
        ├── dev/
        ├── staging/
        └── prod/
```

### 6. Development Configuration
```
.dockerignore           # Container ignore patterns
.gitignore             # Git ignore patterns
.editorconfig          # Editor configuration
.prettierrc            # Code formatting
.eslintrc.js           # JavaScript linting
.mypy.ini              # Python type checking
.pylintrc              # Python linting
```

## Key Principles

1. **Separation of Concerns**: Clear separation between frontend, backend, and workers
2. **Monorepo Structure**: All related code in one repository with clear boundaries
3. **Shared Code**: Reusable packages to avoid duplication
4. **Infrastructure as Code**: Reproducible deployment configurations
5. **Environment Configuration**: Separate configurations for dev, staging, prod
6. **Testing**: Comprehensive test structure at all levels
7. **Documentation**: Self-documenting structure with READMEs in each directory

## Getting Started

1. Clone the repository
2. Copy `.env.example` to `.env.local` and configure
3. Run `make setup` to initialize the project
4. Run `make dev` to start all development services (or `make dev-up` for background)
5. Run `make test` to run tests
6. Use `make dev-logs` to view logs, `make dev-down` to stop services

This structure follows industry best practices for scalable, maintainable applications with AI/ML components.