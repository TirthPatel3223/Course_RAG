# Course RAG Pipeline

An agentic RAG pipeline for querying UCLA MSBA course materials — deadlines, summaries, and general Q&A. Built with **LangGraph**, **ChromaDB**, **OpenAI embeddings**, and deployed on **Oracle Cloud Free Tier**.

## Architecture

- **Frontend**: Web-based chat interface (HTML/CSS/JS)
- **Backend**: FastAPI + WebSocket
- **Agent**: LangGraph with 4 branches (Deadline, Summary, Upload, General)
- **Vector Store**: ChromaDB (self-hosted)
- **File Storage**: Google Drive (g.ucla.edu)
- **LLM**: Claude Sonnet 4 (primary) + GPT-4o-mini (fallback)
- **Embeddings**: OpenAI `text-embedding-3-small`

## Quick Start

### 1. Clone & Install
```bash
git clone https://github.com/YOUR_USERNAME/Course_RAG.git
cd Course_RAG
python -m venv venv
source venv/bin/activate  # or .\venv\Scripts\Activate.ps1 on Windows
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Setup Google Drive
```bash
python scripts/setup_drive.py
```

### 4. Initial Embedding
```bash
python scripts/initial_embed.py
```

### 5. Run Locally
```bash
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```
Open http://localhost:8000

## Docker Deployment

```bash
docker compose up -d --build
```

## Production Deployment (Oracle Cloud)

See `docs/implementation_plan.md` for full deployment guide.

```bash
# On the VPS (first time):
sudo ./scripts/setup_oracle.sh

# From your local machine (deploy updates):
./scripts/deploy.sh <VPS_IP> <SSH_KEY_PATH>
```

## Project Structure

```
Course_RAG/
├── backend/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Settings & course registry
│   ├── agent/               # LangGraph agent
│   │   ├── graph.py         # Graph definition
│   │   ├── state.py         # Agent state
│   │   ├── prompts.py       # LLM prompts
│   │   └── nodes/           # 11 agent nodes
│   ├── services/            # Business logic
│   │   ├── llm_service.py   # Claude + OpenAI fallback
│   │   ├── chroma_service.py
│   │   ├── drive_service.py
│   │   └── ...
│   ├── api/                 # REST + WebSocket routes
│   └── models/              # Pydantic schemas
├── frontend/
│   ├── index.html           # Main SPA
│   ├── styles.css           # Design system
│   └── app.js               # Client logic
├── scripts/                 # Setup & deploy scripts
├── Dockerfile
├── docker-compose.yml
└── Caddyfile                # Reverse proxy config
```

## License

Private — UCLA MSBA coursework.
