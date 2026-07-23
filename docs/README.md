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
- **Containerization**: Podman
- **Orchestration**: Podman Compose
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
- **Podman** and **podman-compose**

## 🐳 Podman Development

The project uses Podman Compose to manage all services:

### Services Included:
1. **PostgreSQL** (port 5432) - Database with pgvector extension
2. **Redis** (port 6379) - Message broker for Celery
3. **API** (port 8000) - FastAPI backend with auto-reload
4. **Workers** - Celery workers for background processing
5. **Web** (port 3000) - Next.js frontend with hot reload
