# Researchly

[![CI](https://github.com/Md-Arif-hasnat99/Researchly/actions/workflows/ci.yml/badge.svg)](https://github.com/Md-Arif-hasnat99/Researchly/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Node.js](https://img.shields.io/badge/Node.js-20+-green.svg)](https://nodejs.org/)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org/)
[![pnpm](https://img.shields.io/badge/pnpm-9+-orange.svg)](https://pnpm.io/)

A production-ready, full-stack AI research assistant for scientific papers. Upload research PDFs, search across them with semantic + keyword hybrid search, ask grounded questions with citations, compare papers, generate literature reviews, and identify research gaps—all with source-level traceability.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              RESEARCHLY SYSTEM                               │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────┐     HTTPS      ┌──────────────┐     ┌────────────────────┐
│   Browser    │◄──────────────►│   FastAPI    │◄───►│    Supabase        │
│  React+Vite  │                │   (Python)   │     │  PostgreSQL+pgvector│
│  TypeScript  │                │              │     │  Auth + Storage    │
└──────┬───────┘                └──────┬───────┘     └─────────┬──────────┘
       │                               │                       │
       │                               ▼                       │
       │                    ┌─────────────────────┐           │
       │                    │     RAG Pipeline    │           │
       │                    │  ┌───────────────┐  │           │
       │                    │  │ Ingestion     │  │           │
       │                    │  │ Embeddings    │  │           │
       │                    │  │ Retrieval     │  │           │
       │                    │  │ Generation    │  │           │
       │                    │  └───────────────┘  │           │
       │                    └──────────┬──────────┘           │
       │                               │                    │
       ▼                               ▼                    ▼
┌──────────────┐              ┌──────────────┐     ┌────────────────────┐
│  Google      │              │  Supabase    │     │  Supabase          │
│  Gemini      │              │  pgvector    │     │  Storage           │
│  (Embeddings │              │  (Vector DB) │     │  (PDF Files)       │
│   + LLM)     │              │              │     │                    │
└──────────────┘              └──────────────┘     └────────────────────┘
```

### Data Flow

```
PDF Upload → Supabase Storage → Background Worker → PyMuPDF Extract
                                                            ↓
                                              Chunk + Metadata (page, section)
                                                            ↓
                                              Gemini Embeddings (batch)
                                                            ↓
                                              pgvector Insert (HNSW index)
                                                            ↓
                                                    status = READY

User Query → Embed → Hybrid Search (vector + keyword) → Rerank
                                                            ↓
                                              Context Builder → Gemini
                                                            ↓
                                              Answer + Citations → Store → Return
```

---

## Tech Stack

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| **Frontend** | React + Vite + TypeScript | 18.3 / 6.2 / 5.7 | SPA with type safety |
| **Styling** | Tailwind CSS + Framer Motion | 3.4 / 12.4 | Utility-first CSS + animations |
| **State** | TanStack Query + React Context | 5.67 | Server state + auth state |
| **Package Mgmt** | pnpm Workspace | 9+ | Monorepo dependency management |
| **Backend** | FastAPI + Uvicorn | 0.115 / 0.30 | High-performance async API |
| **AI/ML** | Google Gemini | 1.5 Pro/Flash | Embeddings + generation |
| **Vector DB** | Supabase pgvector | 0.7+ | HNSW-indexed similarity search |
| **Database** | Supabase PostgreSQL | 15+ | Relational data + RLS |
| **Storage** | Supabase Storage | - | PDF file storage (S3-compatible) |
| **Auth** | Supabase Auth | - | JWT-based auth with RLS |
| **Testing (FE)** | Vitest + RTL + JSDOM | 3.0 / 16.2 | Unit + component tests |
| **Testing (BE)** | Pytest + HTTPX + AsyncIO | 9.0 / 0.27 | API + integration tests |
| **Linting** | ESLint + Ruff | 9.22 / 0.6 | Code quality |
| **CI/CD** | GitHub Actions | - | Automated testing + deployment |
| **Observability** | Structured logging + metrics | - | Request tracing, error tracking |

---

## Project Structure

```
researchly/
├── apps/
│   ├── web/                          # React frontend application
│   │   ├── src/
│   │   │   ├── components/           # Reusable UI components
│   │   │   │   ├── ui/               # Base UI primitives (Button, Input, etc.)
│   │   │   │   ├── layout/           # Layout components (Header, Sidebar)
│   │   │   │   ├── papers/           # Paper-specific components
│   │   │   │   ├── chat/             # Chat interface components
│   │   │   │   └── research/         # Research tools components
│   │   │   ├── features/             # Feature-based modules
│   │   │   │   ├── auth/             # Authentication flows
│   │   │   │   ├── papers/           # Paper management
│   │   │   │   ├── chat/             # Chat functionality
│   │   │   │   └── research/         # Research tools (compare, review, gaps)
│   │   │   ├── hooks/                # Custom React hooks
│   │   │   ├── lib/                  # Utilities, configs, clients
│   │   │   ├── services/             # API service layer
│   │   │   ├── types/                # TypeScript type definitions
│   │   │   ├── pages/                # Route-level page components
│   │   │   ├── context/              # React Context providers
│   │   │   ├── tests/                # Test utilities + setup
│   │   │   ├── App.tsx               # Root component + routing
│   │   │   └── main.tsx              # Entry point
│   │   ├── package.json
│   │   ├── vite.config.ts
│   │   ├── tsconfig.json
│   │   ├── tailwind.config.ts
│   │   └── eslint.config.js
│   │
│   └── api/                          # FastAPI backend application
│       ├── app/
│       │   ├── main.py               # App factory + lifespan
│       │   ├── api/                  # API route handlers
│       │   │   ├── health.py         # Health checks
│       │   │   ├── papers.py         # Paper CRUD + upload
│       │   │   ├── search.py         # Semantic + hybrid search
│       │   │   ├── chat.py           # RAG chat endpoint
│       │   │   └── research.py       # Compare, review, gaps
│       │   ├── core/                 # Core infrastructure
│       │   │   ├── config.py         # Settings management
│       │   │   ├── security.py       # JWT validation, auth
│       │   │   ├── logging.py        # Structured logging
│       │   │   └── exceptions.py     # Custom exceptions
│       │   ├── models/               # SQLAlchemy models
│       │   ├── schemas/              # Pydantic schemas (request/response)
│       │   ├── services/             # Business logic layer
│       │   │   ├── paper_service.py
│       │   │   ├── chat_service.py
│       │   │   └── citation_service.py
│       │   └── rag/                  # RAG pipeline modules
│       │       ├── ingestion/        # PDF extraction, chunking
│       │       ├── embeddings/       # Gemini embedding client
│       │       ├── retrieval/        # Vector + keyword search
│       │       ├── generation/       # Prompt building, LLM calls
│       │       └── pipeline.py       # Orchestration
│       ├── tests/                    # Backend tests
│       ├── requirements.txt
│       └── pyproject.toml
│
├── packages/
│   └── shared/                       # Shared TypeScript types
│       ├── src/index.ts
│       └── package.json
│
├── docs/                             # Documentation (PRD, design, architecture)
│
├── supabase/
│   ├── config.toml                   # Supabase local config
│   └── migrations/                   # SQL migrations (versioned)
│       ├── 20260923000001_initial_schema.sql
│       ├── 20260923000002_rls_policies.sql
│       ├── 20260923000003_storage.sql
│       ├── 20260923000004_auth_config.sql
│       ├── 20260923000005_search_function.sql
│       ├── 20260926000001_hybrid_search.sql
│       ├── 20260927000002_fix_keyword_search_tsquery_type.sql
│       ├── 20260927000003_security_fixes.sql
│       ├── 20260927000004_performance_indexes.sql
│       └── 20260929000005_additional_indexes.sql
│
├── scripts/                          # Operational scripts
│   ├── deploy.sh
│   ├── migrate.sh
│   └── seed.py
│
├── .github/
│   └── workflows/
│       └── ci.yml                    # CI pipeline
│
├── docker-compose.yml                # Local development stack
├── Dockerfile.api                    # Backend container
├── Dockerfile.web                    # Frontend container
├── .env.example                      # Environment template
├── .gitignore
├── package.json                      # Root workspace config
├── pnpm-workspace.yaml               # pnpm workspace config
├── pnpm-lock.yaml
└── README.md
```

---

## Quick Start

### Prerequisites

- **Node.js** ≥ 20.0.0 (LTS recommended)
- **Python** ≥ 3.10
- **pnpm** ≥ 9.0.0 (`corepack enable pnpm`)
- **Docker** + Docker Compose (for local Supabase)
- **Supabase Account** (cloud or self-hosted)
- **Google AI Studio API Key** (Gemini)

### 1. Clone & Install

```bash
git clone https://github.com/Md-Arif-hasnat99/Researchly.git
cd Researchly

# Install frontend dependencies
pnpm install

# Install backend dependencies
cd apps/api
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd ../..
```

### 2. Environment Configuration

```bash
# Copy template
cp .env.example .env

# Frontend env
cp apps/web/.env.example apps/web/.env.local

# Backend env
cp apps/api/.env.example apps/api/.env
```

**Required Variables:**

| Variable | Description | Required | Scope |
|----------|-------------|----------|-------|
| `VITE_SUPABASE_URL` | Supabase project URL | ✅ | Frontend |
| `VITE_SUPABASE_ANON_KEY` | Supabase anon public key | ✅ | Frontend |
| `VITE_API_URL` | Backend API base URL | ✅ | Frontend |
| `GEMINI_API_KEY` | Google AI Studio API key | ✅ | Backend |
| `SUPABASE_URL` | Supabase project URL | ✅ | Backend |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (admin) | ✅ | Backend |
| `SUPABASE_ANON_KEY` | Supabase anon public key | ✅ | Backend |
| `ENVIRONMENT` | `development` \| `production` | ✅ | Backend |
| `CORS_ORIGINS` | Comma-separated allowed origins | ✅ | Backend |

**Optional (Production):**

| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` | `INFO` |
| `EMBEDDING_MODEL` | Gemini embedding model | `text-embedding-004` |
| `GENERATION_MODEL` | Gemini generation model | `gemini-1.5-flash` |
| `CHUNK_SIZE` | Text chunk size (tokens) | `1000` |
| `CHUNK_OVERLAP` | Chunk overlap (tokens) | `200` |
| `TOP_K` | Retrieval top-k | `10` |
| `RERANK_TOP_K` | Post-rerank top-k | `5` |
| `MAX_FILE_SIZE_MB` | Max PDF upload size | `50` |
| `RATE_LIMIT_REQUESTS` | Requests per minute | `60` |

### 3. Local Development with Docker (Recommended)

```bash
# Start Supabase locally (PostgreSQL + Auth + Storage + pgvector)
docker-compose up -d

# Apply migrations
cd supabase
supabase db reset --linked  # or run migrations manually
cd ..

# Start frontend (Terminal 1)
pnpm dev

# Start backend (Terminal 2)
cd apps/api
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Access Points:**
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Supabase Studio: http://localhost:54323

### 4. Manual Supabase Setup (Cloud)

1. Create project at [supabase.com](https://supabase.com)
2. Enable **pgvector** extension: `CREATE EXTENSION IF NOT EXISTS vector;`
3. Run migrations from `supabase/migrations/` in order
4. Configure **Storage**: Create bucket `research-papers` with RLS policies
5. Configure **Auth**: Enable email/password, set redirect URLs
6. Copy credentials to `.env` files

---

## Available Commands

### Root Workspace

```bash
pnpm dev              # Start frontend dev server
pnpm build            # Build all packages (shared + web)
pnpm test             # Run frontend tests (vitest)
pnpm lint             # Lint frontend (ESLint)
pnpm typecheck        # Type-check shared + web
pnpm format           # Format with Prettier (if configured)
```

### Frontend (`apps/web`)

```bash
pnpm --filter web dev           # Dev server with HMR
pnpm --filter web build         # Production build (dist/)
pnpm --filter web preview       # Preview production build
pnpm --filter web test          # Watch mode tests
pnpm --filter web test --run    # CI mode tests
pnpm --filter web typecheck     # TypeScript check
pnpm --filter web lint          # ESLint
pnpm --filter web coverage      # Test coverage report
```

### Backend (`apps/api`)

```bash
cd apps/api

# Development
uvicorn app.main:app --reload

# Testing
pytest                          # All tests
pytest -v                       # Verbose
pytest --cov=app                # With coverage
pytest tests/test_chat.py       # Specific module
pytest -k "test_search"         # Pattern match

# Linting
ruff check .                    # Check
ruff check . --fix              # Auto-fix
ruff format .                   # Format

# Database
alembic upgrade head            # Run migrations
alembic revision --autogenerate -m "msg"  # Create migration
```

### Database (Supabase CLI)

```bash
supabase start                  # Start local stack
supabase db reset               # Reset + migrate + seed
supabase db diff                # Check schema drift
supabase migration new name     # Create new migration
supabase db push                # Push to remote
```

---

## Features Deep Dive

### 🔐 Authentication (Complete)
- Email/password signup + login
- JWT access/refresh tokens (Supabase Auth)
- Protected routes with client-side guards
- Server-side JWT validation on every API call
- Row Level Security (RLS) on all tables
- Session persistence across browser restarts

### 📄 Paper Management (Complete)
- Drag-and-drop PDF upload with progress
- Configurable max file size (default 50MB)
- Real-time processing status: `uploaded → processing → ready │ failed`
- Paper metadata extraction (title, authors, year, abstract)
- Library with search, sort (date, title), filter (status)
- Secure delete (cascades to chunks, vectors, storage)

### 🔍 Semantic + Hybrid Search (Complete)
- **Vector Search**: pgvector HNSW index, cosine similarity
- **Keyword Search**: PostgreSQL `tsvector` + `tsquery` (full-text)
- **Hybrid Fusion**: Reciprocal Rank Fusion (RRF) combining both
- **Filters**: By paper, date range, status
- **Pagination**: Cursor-based for performance

### 💬 RAG Chat (Complete)
- Grounded generation with strict citation requirements
- Conversation history with branching support
- Streaming responses (Server-Sent Events)
- Source citations with paper title, page, chunk preview
- Click citation → open paper at exact page
- Context window management (token budgeting)

### 🔬 Research Tools (Complete)
| Tool | Description | Output |
|------|-------------|--------|
| **Multi-Paper QA** | Ask questions across selected papers | Synthesized answer with per-paper citations |
| **Paper Comparison** | Structured comparison table | Dataset, Model, Method, Metrics, Results, Limitations |
| **Literature Review** | Structured synthesis | Introduction, Approaches, Trends, Results, Gaps, References |
| **Gap Analysis** | Identify research gaps | Limitations, Unresolved Problems, Future Work, Dataset/Method Gaps |

### ⚡ Advanced Features (In Progress)
- **Reranking**: Cross-encoder reranking of retrieved chunks
- **Streaming**: Token-by-token response streaming
- **Background Workers**: Celery + Redis for async ingestion
- **Evaluation**: RAGAS-based retrieval/generation benchmarks
- **Caching**: Redis cache for embeddings + frequent queries

---

## API Reference

### Authentication
All endpoints (except `/api/health`) require `Authorization: Bearer <jwt>`

### Health
```
GET /api/health
Response: { "status": "ok", "version": "1.0.0", "dependencies": {...} }
```

### Papers
```
POST   /api/papers              # Upload PDF (multipart/form-data)
GET    /api/papers              # List papers (query: page, limit, search, status, sort)
GET    /api/papers/{id}         # Get paper details + chunks
DELETE /api/papers/{id}         # Delete paper + all associated data
POST   /api/papers/{id}/retry   # Retry failed processing
GET    /api/papers/{id}/download # Download original PDF
```

### Search
```
POST /api/search
Body: { "query": "string", "paper_ids": ["uuid"], "top_k": 10, "use_hybrid": true, "use_rerank": false }
Response: { "results": [{ "paper_id", "paper_title", "page_number", "section", "content", "score" }] }
```

### Chat
```
POST /api/chat
Body: { "message": "string", "conversation_id": "uuid?", "paper_ids": ["uuid?"], "stream": true }
Response: Streaming SSE or { "message_id", "content", "citations": [...] }
```

### Conversations
```
GET    /api/conversations           # List user conversations
GET    /api/conversations/{id}      # Get conversation + messages
DELETE /api/conversations/{id}      # Delete conversation
PATCH  /api/conversations/{id}      # Update title
```

### Research Tools
```
POST /api/research/compare
Body: { "paper_ids": ["uuid"], "aspects": ["dataset", "model", "method", "metrics", "results", "limitations"] }

POST /api/research/literature-review
Body: { "paper_ids": ["uuid"], "focus": "string?" }

POST /api/research/gaps
Body: { "paper_ids": ["uuid"] }
```

### Error Format
```json
{
  "error": {
    "code": "PAPER_PROCESSING_FAILED",
    "message": "The paper could not be processed.",
    "details": { "stage": "embedding", "retryable": true }
  }
}
```

---

## Database Schema

### Core Tables

```sql
-- Users (managed by Supabase Auth)
profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id),
  name TEXT,
  avatar_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
)

-- Papers
papers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  authors TEXT[],
  abstract TEXT,
  publication_year INT,
  file_path TEXT NOT NULL,           -- Supabase Storage path
  file_size_bytes BIGINT,
  page_count INT,
  status TEXT CHECK (status IN ('uploaded','processing','ready','failed')),
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
)

-- Paper Chunks with Embeddings
paper_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  paper_id UUID REFERENCES papers(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  page_number INT NOT NULL,
  section TEXT,
  chunk_index INT NOT NULL,
  token_count INT,
  embedding VECTOR(768),             -- pgvector, dims match Gemini
  created_at TIMESTAMPTZ DEFAULT NOW()
)

-- Conversations
conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  paper_ids UUID[] DEFAULT '{}',     -- Papers in context
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
)

-- Messages
messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT CHECK (role IN ('user','assistant')),
  content TEXT NOT NULL,
  token_count INT,
  created_at TIMESTAMPTZ DEFAULT NOW()
)

-- Citations (links messages → chunks)
citations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id UUID REFERENCES messages(id) ON DELETE CASCADE,
  paper_id UUID REFERENCES papers(id) ON DELETE CASCADE,
  chunk_id UUID REFERENCES paper_chunks(id) ON DELETE CASCADE,
  page_number INT NOT NULL,
  similarity_score FLOAT,
  created_at TIMESTAMPTZ DEFAULT NOW()
)
```

### Indexes (Performance Critical)

```sql
-- Vector similarity search (HNSW)
CREATE INDEX ON paper_chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- Full-text search
CREATE INDEX ON paper_chunks USING gin (to_tsvector('english', content));

-- Composite for filtered search
CREATE INDEX ON paper_chunks (paper_id, page_number);
CREATE INDEX ON paper_chunks (paper_id, chunk_index);

-- Query performance
CREATE INDEX ON papers (user_id, created_at DESC);
CREATE INDEX ON conversations (user_id, updated_at DESC);
CREATE INDEX ON messages (conversation_id, created_at);
CREATE INDEX ON citations (message_id);
```

### Row Level Security (All Tables)

```sql
-- Example: papers
ALTER TABLE papers ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users own their papers" ON papers
  FOR ALL USING (auth.uid() = user_id);

-- Similar policies on all tables via auth.uid() = user_id
```

---

## Deployment

### Frontend (Vercel / Netlify / Cloudflare Pages)

```bash
# Build
pnpm --filter web build

# Deploy dist/ folder
# Vercel: Connect repo, set Root Directory = apps/web, Build Command = pnpm build, Output = dist
```

**Environment Variables (Vercel Dashboard):**
```
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
VITE_API_URL=https://api.yourdomain.com
```

### Backend (Render / Fly.io / Railway / Kubernetes)

#### Option A: Render (Docker)
```yaml
# render.yaml (reference - not committed)
services:
  - type: web
    name: researchly-api
    runtime: docker
    dockerfilePath: ./Dockerfile.api
    plan: starter
    envVars:
      - key: GEMINI_API_KEY; sync: false
      - key: SUPABASE_URL; sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY; sync: false
      - key: SUPABASE_ANON_KEY; sync: false
      - key: CORS_ORIGINS; value: https://your-frontend.vercel.app
```

#### Option B: Fly.io
```bash
fly launch --dockerfile Dockerfile.api
fly secrets set GEMINI_API_KEY=... SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...
fly deploy
```

#### Option C: Kubernetes (Helm)
```yaml
# helm/researchly-api/values.yaml
image:
  repository: ghcr.io/yourorg/researchly-api
  tag: "latest"

env:
  GEMINI_API_KEY: ""
  SUPABASE_URL: ""
  SUPABASE_SERVICE_ROLE_KEY: ""
  ENVIRONMENT: "production"
  CORS_ORIGINS: "https://your-frontend.vercel.app"

resources:
  limits:
    memory: "2Gi"
    cpu: "2000m"
  requests:
    memory: "1Gi"
    cpu: "1000m"

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilization: 70
```

### Database (Supabase Cloud)
- Use Supabase managed PostgreSQL (no self-hosting needed)
- Enable pgvector extension
- Run migrations via Supabase CLI or Dashboard SQL editor
- Configure connection pooling (PgBouncer) for production

### Storage (Supabase / S3-compatible)
- Supabase Storage handles PDF files automatically
- For custom S3: Set `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`

### Production Checklist

- [ ] TLS/SSL certificates (automatic on Vercel/Render/Fly)
- [ ] Environment variables set (no `.env` files in production)
- [ ] CORS origins restricted to frontend domain
- [ ] Rate limiting enabled (API gateway or middleware)
- [ ] Database connection pooling configured
- [ ] Monitoring alerts (error rate, latency, queue depth)
- [ ] Backup strategy (Supabase daily backups + point-in-time recovery)
- [ ] Log aggregation (Datadog, Logtail, or self-hosted)
- [ ] Health check endpoints responding
- [ ] Load testing completed

---

## Monitoring & Observability

### Structured Logging (Backend)
```python
# app/core/logging.py - JSON structured logs
{
  "timestamp": "2026-10-22T10:30:00.123Z",
  "level": "INFO",
  "logger": "app.rag.pipeline",
  "message": "RAG query completed",
  "request_id": "req_abc123",
  "user_id": "usr_xyz789",
  "duration_ms": 1240,
  "tokens": { "prompt": 3421, "completion": 512 },
  "retrieval": { "candidates": 20, "reranked": 5, "latency_ms": 45 }
}
```

### Key Metrics to Track

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| API p95 latency | < 2s | > 5s |
| RAG query p95 | < 3s | > 8s |
| Paper processing time | < 60s | > 180s |
| Error rate | < 0.1% | > 1% |
| Embedding failures | 0 | > 0 |
| Auth failures | < 0.5% | > 2% |
| Database connection pool usage | < 70% | > 90% |

### Recommended Stack
- **Logs**: Datadog / Logtail / Grafana Loki
- **Metrics**: Prometheus + Grafana / Datadog
- **Traces**: OpenTelemetry → Jaeger / Tempo
- **Alerts**: PagerDuty / Opsgenie / Grafana Alerting
- **Uptime**: Better Uptime / Pingdom

---

## Security

### Implemented
- ✅ JWT validation on every request (RS256, JWKS)
- ✅ Row Level Security on all database tables
- ✅ Service role key only on backend (never frontend)
- ✅ Gemini API key only on backend
- ✅ CORS restricted to known origins
- ✅ Input validation (Pydantic schemas)
- ✅ File type validation (PDF only, magic bytes)
- ✅ File size limits
- ✅ Rate limiting (per-user, per-endpoint)
- ✅ Secure headers (HSTS, CSP, X-Frame-Options)
- ✅ No secrets in logs or error responses

### Production Hardening
```python
# Additional middleware (add to app/main.py)
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Apply to sensitive endpoints
@app.post("/api/chat")
@limiter.limit("30/minute")
async def chat(...):
```

### Secrets Management
- **Never** commit `.env` files
- Use platform secret stores (Vercel Env, Render Env, Fly Secrets, K8s Secrets)
- Rotate keys quarterly
- Use separate keys per environment (dev/staging/prod)

---

## Performance

### Benchmarks (Target)

| Operation | p50 | p95 | p99 |
|-----------|-----|-----|-----|
| Health check | 5ms | 15ms | 30ms |
| Paper list (20) | 80ms | 200ms | 400ms |
| Semantic search | 300ms | 800ms | 1.5s |
| Hybrid search | 400ms | 1s | 2s |
| RAG query (no stream) | 1.5s | 3s | 5s |
| RAG query (stream first token) | 500ms | 1s | 2s |
| PDF upload (10MB) | 2s | 5s | 10s |
| Paper processing (50 pages) | 30s | 60s | 120s |

### Optimization Strategies

1. **Embedding Caching**: Cache embeddings for identical chunks (Redis)
2. **Connection Pooling**: PgBouncer (Supabase managed) + SQLAlchemy pool
3. **Batch Embeddings**: Process 100 chunks per Gemini request
4. **Async Ingestion**: Background workers (Celery + Redis)
5. **Query Optimization**: Composite indexes, `EXPLAIN ANALYZE` regularly
6. **Frontend**: Route-level code splitting, TanStack Query caching, virtualized lists

---

## Testing Strategy

### Test Pyramid

```
                    ┌─────────────┐
                    │   E2E (5%)  │  ← Playwright (critical paths)
                    ├─────────────┤
               ┌────│ Integration │────┐
               │    │   (15%)     │    │
               ▼    └─────────────┘    ▼
        ┌─────────────┐          ┌─────────────┐
        │  Frontend   │          │  Backend    │
        │  Unit (40%) │          │  Unit (40%) │
        │  Vitest+RTL │          │  Pytest     │
        └─────────────┘          └─────────────┘
```

### Running Tests

```bash
# Frontend
pnpm --filter web test --run          # All tests
pnpm --filter web test --run --coverage
pnpm --filter web test --run tests/chat-scope.test.tsx

# Backend
cd apps/api
pytest                                # All tests
pytest --cov=app --cov-report=html
pytest tests/test_chat.py::test_streaming_chat -v

# E2E (when configured)
pnpm --filter web test:e2e
```

### Coverage Targets
- Frontend: ≥ 80% lines, ≥ 70% branches
- Backend: ≥ 85% lines, ≥ 75% branches
- RAG Pipeline: ≥ 90% (critical path)

---

## Contributing

### Branch Strategy
```
main
  │
  ├── feat/part-XX-feature-name     # Feature branches
  ├── fix/issue-description         # Bug fixes
  ├── docs/update-readme            # Documentation
  └── chore/dependency-updates      # Maintenance
```

### Workflow
1. Create branch from `main`
2. Implement feature + tests
3. Run locally: `pnpm lint && pnpm test && pnpm build`
4. Backend: `ruff check . && pytest`
5. Commit with conventional commits:
   ```
   feat(chat): add streaming response support
   
   - Implement SSE streaming in chat endpoint
   - Add streaming hook in frontend
   - Update types for stream chunks
   ```
6. Push → Create PR → CI must pass → Review → Merge (squash)

### Code Standards
- **TypeScript**: Strict mode, no `any`, explicit returns
- **Python**: Type hints everywhere, `ruff` + `mypy` clean
- **Git**: Conventional commits, linear history
- **PRs**: Small, focused, with tests

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| `pgvector` extension not found | Supabase pgvector not enabled | `CREATE EXTENSION vector;` in SQL editor |
| `HNSW index creation failed` | Table has no rows | Insert test data first, or use `CONCURRENTLY` |
| `JWT validation failed` | Clock skew / wrong keys | Verify `SUPABASE_JWT_SECRET`, sync server time |
| `Gemini rate limit` | Exceeded quota | Implement exponential backoff, request quota increase |
| `CORS error` | Origin not in `CORS_ORIGINS` | Add frontend URL to backend env |
| `File upload fails` | Storage bucket policy | Check bucket RLS policies, CORS config |
| `Embedding dimension mismatch` | Model changed | Re-embed all chunks, or use consistent model |
| `Out of memory on processing` | Large PDF, no streaming | Implement chunked processing, increase memory |

### Debug Commands

```bash
# Check Supabase connection
curl -H "apikey: $SUPABASE_ANON_KEY" "$SUPABASE_URL/rest/v1/papers?select=count"

# Test Gemini API
curl -H "Authorization: Bearer $GEMINI_API_KEY" \
  "https://generativelanguage.googleapis.com/v1beta/models"

# View backend logs
docker logs -f researchly-api  # or journalctl -u researchly-api

# Database query analysis
EXPLAIN ANALYZE SELECT * FROM paper_chunks 
WHERE embedding <-> '[0.1,...]'::vector 
ORDER BY embedding <-> '[0.1,...]'::vector LIMIT 10;
```

---

## Roadmap

### v1.1 (Q4 2026)
- [ ] Reranking with cross-encoder
- [ ] Streaming chat responses
- [ ] Background job queue (Celery + Redis)
- [ ] RAG evaluation dashboard (RAGAS)
- [ ] Export conversations (PDF, Markdown)

### v1.2 (Q1 2027)
- [ ] Multi-modal (figures, tables extraction)
- [ ] Agentic research (autonomous literature search)
- [ ] Team workspaces + sharing
- [ ] Public paper collections
- [ ] Zotero / Mendeley import

### v2.0 (Q2 2027)
- [ ] Fine-tuned embedding model
- [ ] Custom reranker
- [ ] On-premise deployment option
- [ ] Advanced analytics (usage, quality)

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Support

- **Issues**: [GitHub Issues](https://github.com/Md-Arif-hasnat99/Researchly/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Md-Arif-hasnat99/Researchly/discussions)
- **Documentation**: [Wiki](https://github.com/Md-Arif-hasnat99/Researchly/wiki)
- **Security**: Email security@researchly.dev (PGP key available)

---

## Acknowledgments

- [Supabase](https://supabase.com) — Backend-as-a-Service platform
- [Google Gemini](https://ai.google.dev) — Generative AI models
- [pgvector](https://github.com/pgvector/pgvector) — Vector similarity search
- [FastAPI](https://fastapi.tiangolo.com) — Modern Python web framework
- [React](https://react.dev) + [Vite](https://vitejs.dev) — Frontend tooling
- [Tailwind CSS](https://tailwindcss.com) — Utility-first styling
- [Framer Motion](https://www.framer.com/motion/) — Animations
- [TanStack Query](https://tanstack.com/query) — Server state management