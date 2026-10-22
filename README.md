# Researchly

A full-stack AI research assistant for scientific papers. Upload research PDFs, search across them, ask grounded questions, compare papers, generate literature-review material, and inspect the exact sources used by the system.

## Tech Stack

- **Frontend**: React + Vite + TypeScript
- **Package Manager**: pnpm (workspace)
- **UI**: Tailwind CSS + Framer Motion
- **Backend**: FastAPI + Python
- **AI**: Google Gemini (embeddings + generation)
- **Database**: Supabase PostgreSQL + pgvector
- **File Storage**: Supabase Storage
- **Authentication**: Supabase Auth
- **Frontend Testing**: Vitest + React Testing Library
- **Backend Testing**: Pytest + HTTPX
- **Code Quality**: ESLint + Ruff
- **CI**: GitHub Actions

## Project Structure

```
researchly/
├── apps/
│   ├── web/          # React frontend
│   └── api/          # FastAPI backend
├── packages/
│   └── shared/       # Shared TypeScript types
├── docs/
│   ├── PRD.md        # Product Requirements Document
│   ├── design.md     # Design system
│   └── architecture.md
├── supabase/
│   ├── config.toml
│   └── migrations/
├── .github/workflows/ci.yml
├── package.json
└── pnpm-workspace.yaml
```

## Getting Started

### Prerequisites

- Node.js 20+
- Python 3.10+
- pnpm
- Supabase account
- Google Gemini API key

### Installation

```bash
# Install dependencies
pnpm install

# Install backend dependencies
cd apps/api
pip install -r requirements.txt
cd ../..

# Copy environment files
cp .env.example .env
# Edit .env with your credentials
```

### Environment Variables

**Frontend** (`.env.local` in `apps/web/`):
```
VITE_SUPABASE_URL=your_supabase_url
VITE_SUPABASE_ANON_KEY=your_supabase_anon_key
VITE_API_URL=http://localhost:8000
```

**Backend** (`.env` in `apps/api/`):
```
GEMINI_API_KEY=your_gemini_api_key
SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
SUPABASE_ANON_KEY=your_supabase_anon_key
```

### Development

```bash
# Start frontend dev server
pnpm dev

# Start backend (in separate terminal)
cd apps/api
uvicorn app.main:app --reload
```

### Available Commands

```bash
# From root
pnpm dev          # Start frontend dev server
pnpm build        # Build all packages
pnpm test         # Run frontend tests
pnpm lint         # Run frontend linting

# Frontend only
pnpm --filter web dev
pnpm --filter web test
pnpm --filter web build
pnpm --filter web typecheck
pnpm --filter web lint

# Backend only
cd apps/api
pytest
ruff check .
```

## Features

### MVP (Completed)
- User authentication (signup, login, logout, session management)
- PDF upload with progress tracking
- Paper library with search, sort, filter
- PDF text extraction and chunking
- Gemini embeddings generation
- Semantic search with pgvector
- RAG question answering with grounded responses
- Source citations with paper/page references
- Persistent chat conversations
- Multi-paper question answering
- Paper comparison
- Literature review generation
- Research gap analysis

### Advanced (In Progress)
- Hybrid search (vector + keyword)
- Reranking
- RAG evaluation benchmarks
- Streaming responses
- Background processing

## Database Schema

Key tables:
- `profiles` - User profiles
- `papers` - Uploaded papers with metadata
- `paper_chunks` - Text chunks with embeddings
- `conversations` - Chat conversations
- `messages` - Chat messages
- `citations` - Source references linking messages to paper chunks

All tables enforce Row Level Security (RLS) for data isolation.

## API Endpoints

```
GET    /api/health
POST   /api/papers
GET    /api/papers
GET    /api/papers/{id}
DELETE /api/papers/{id}
POST   /api/search
POST   /api/chat
GET    /api/conversations
GET    /api/conversations/{id}
DELETE /api/conversations/{id}
POST   /api/research/compare
POST   /api/research/literature-review
POST   /api/research/gaps
```

## Testing

```bash
# Frontend tests
pnpm --filter web test --run

# Backend tests
cd apps/api && python -m pytest tests
```

## CI/CD

GitHub Actions runs on every PR:
- Frontend: typecheck, lint, tests, build
- Backend: ruff lint, pytest

## Deployment

Frontend: Vercel (configured via Vercel dashboard)
Backend: Render, Fly.io, or any container platform

## Documentation

- [PRD](docs/PRD.md) - Product requirements
- [Architecture](docs/architecture.md) - System architecture
- [Design](docs/design.md) - Design system

## License

MIT