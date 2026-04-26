# Course RAG — UCLA MSBA Document Assistant

An agentic RAG (Retrieval-Augmented Generation) pipeline that lets UCLA MSBA students query their course materials through a chat interface. Ask about deadlines, get lecture summaries, or ask general questions about course content — the system routes each query to a specialized agent branch and retrieves the most relevant chunks from a self-hosted vector store.

**Live at:** `https://tirth-courserag.duckdns.org`

---

## What it does

- **Chat with your course documents** — slides, lecture transcripts, and homework PDFs indexed and searchable via semantic similarity
- **Deadline tracking** — specialized branch that extracts and cross-references assignment due dates with self-verification
- **Lecture summarization** — retrieve and synthesize content across an entire course or specific lectures
- **File upload pipeline** — drag-and-drop or Google Drive link → LLM classifies the file → proposes a Drive folder → human approves → file is uploaded and embedded automatically
- **Admin dashboard** — trigger re-embedding runs, monitor ChromaDB stats, manage sessions
- **Two-tier access** — admin users have full access; viewer users get read-only chat with rate limiting

---

## Architecture

```
Browser (HTML/CSS/JS)
        │  WebSocket + REST
        ▼
FastAPI (uvicorn)
        │
        ├── /api/login         → HMAC-signed token (admin or viewer)
        ├── /api/verify        → token validation
        ├── /ws/chat           → WebSocket — all real-time interaction
        └── /api/admin/*       → admin-only REST endpoints
                │
                ▼
        LangGraph Agent
                │
        ┌───────┴────────────────────────────┐
        │                                    │
   Query Router                       Upload Pipeline
   (LLM classifier)                   (LLM classifier → human approval)
        │
   ┌────┴──────────────────┐
   │         │             │
Deadline  Summary       General
 Branch    Branch        Branch
   │         │             │
   └────┬────┘             │
        │                  │
   ChromaDB retrieval ◄────┘
   (text-embedding-3-small)
        │
   Claude 3.5 Haiku (primary)
   GPT-4o-mini (fallback)
        │
   Self-verification node
        │
   Final response → WebSocket
```

### Key components

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML/CSS/JS, WebSocket, marked.js |
| Backend | FastAPI, uvicorn, Python 3.11 |
| Agent | LangGraph (StateGraph with checkpointing) |
| Vector store | ChromaDB (self-hosted, persistent) |
| Embeddings | OpenAI `text-embedding-3-small` (1536d) |
| LLM (primary) | Anthropic Claude 3.5 Haiku |
| LLM (fallback) | OpenAI GPT-4o-mini |
| OCR | Tesseract (via PyMuPDF built-in integration) |
| File storage | Google Drive (g.ucla.edu) |
| Session DB | SQLite (aiosqlite) |
| Auth | Custom HMAC-SHA256 tokens (no JWT library) |
| Deployment | Docker + Caddy reverse proxy on Oracle Cloud Free Tier |

---

## Agent workflow

Each WebSocket `chat` message runs through this LangGraph pipeline:

```
input
  └─► query_classifier        — LLM decides: deadline / summary / general / upload
        ├─► deadline_retriever — semantic search with deadline-keyword-boosted metadata filter
        │     └─► deadline_verifier   — cross-checks extracted dates against source chunks
        │           └─► response_builder
        ├─► summary_retriever  — wide retrieval (top-10 chunks) across a course
        │     └─► summary_generator
        │           └─► response_builder
        ├─► general_retriever  — standard top-7 semantic search
        │     └─► general_responder
        │           └─► response_builder
        └─► upload_pipeline    — see Upload section below
```

The graph uses LangGraph's SQLite checkpointer so multi-turn conversations are persisted per `thread_id` (= `session_id`).

### Upload pipeline

```
upload_file / upload_link message
  └─► file_classifier (LLM)   — proposes quarter / course / file_type / path
        └─► human_approval_gate (interrupt)
              ├─ approved  → drive_uploader → embed_new_chunks → response
              ├─ custom    → user picks path in UI → drive_uploader → embed_new_chunks
              └─ rejected  → skip
```

---

## Authentication

Two roles, credentials stored in `.env`:

| Role | Access |
|---|---|
| **admin** | Full access — chat (all query types), file upload, admin panel, re-embed |
| **viewer** | Chat only — `general` and `deadline` queries, no uploads, no admin panel, 10 messages/session |

Tokens are HMAC-SHA256 signed, 24-hour expiry, no external JWT library. The payload encodes `username`, `role`, and a timestamp. Viewers hitting the rate limit or attempting restricted actions get a clear inline message in the chat UI.

### Token structure

```
base64url({"ts":"<unix>","v":2,"role":"admin","username":"..."}) . hex(HMAC-SHA256(password, payload))
```

---

## Project structure

```
Course_RAG/
├── backend/
│   ├── main.py                  # FastAPI app, login/verify endpoints, static serving
│   ├── config.py                # Pydantic Settings, course registry (COURSES dict)
│   ├── agent/
│   │   ├── graph.py             # LangGraph StateGraph definition
│   │   ├── state.py             # AgentState TypedDict
│   │   ├── prompts.py           # All LLM prompt templates
│   │   └── nodes/               # One file per graph node
│   │       ├── input_handler.py
│   │       ├── router.py
│   │       ├── retriever.py
│   │       ├── deadline_extractor.py
│   │       ├── deadline_verifier.py
│   │       ├── summary_redirector.py
│   │       ├── general_responder.py
│   │       ├── source_explainer.py
│   │       ├── upload_handler.py
│   │       ├── location_classifier.py
│   │       ├── upload_executor.py
│   │       └── response_output.py
│   ├── api/
│   │   ├── auth.py              # HMAC token generation/verification, FastAPI dependencies
│   │   ├── routes_chat.py       # WebSocket endpoint, message handlers
│   │   └── routes_admin.py      # Admin REST endpoints (require_admin protected)
│   ├── models/
│   │   └── schemas.py           # Pydantic request/response models
│   └── services/
│       ├── llm_service.py       # Claude + OpenAI fallback wrapper
│       ├── chroma_service.py    # ChromaDB CRUD
│       ├── drive_service.py     # Google Drive OAuth + file ops
│       ├── embedding_service.py # OpenAI embedding calls with sub-batching
│       ├── pdf_processor.py     # PyMuPDF extraction + Tesseract OCR fallback
│       ├── text_processor.py    # Chunking (slides vs transcripts), metadata tagging
│       └── session_service.py   # SQLite session + message history + viewer rate limit
├── frontend/
│   ├── index.html               # Single-page app shell
│   ├── styles.css               # Design system (dark theme, CSS variables)
│   └── app.js                   # WebSocket client, role-aware UI, upload queue
├── scripts/
│   ├── setup_drive.py           # Google OAuth consent flow
│   ├── initial_embed.py         # First-run Drive → ChromaDB embedding
│   ├── setup_oracle.sh          # VPS provisioning (Docker, Caddy, firewall)
│   └── deploy.sh                # Local → VPS rsync + container restart
├── Dockerfile
├── docker-compose.yml
├── Caddyfile                    # HTTPS reverse proxy config
├── .env.example                 # Credential template
└── requirements.txt
```

---

## Setup

### Prerequisites

- Python 3.11+
- Docker (for deployment)
- Tesseract OCR (`tesseract-ocr` — included automatically in Docker image)
- Anthropic API key
- OpenAI API key
- Google Cloud project with Drive API enabled + OAuth credentials

### 1. Clone & install

```bash
git clone https://github.com/TirthPatel3223/Course_RAG.git
cd Course_RAG
python -m venv venv
source venv/bin/activate       # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...

ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_secure_admin_password

VIEWER_USERNAME=viewer
VIEWER_PASSWORD=your_viewer_password

GOOGLE_CREDENTIALS_PATH=credentials/oauth_credentials.json
GOOGLE_TOKEN_PATH=credentials/token.pickle
DRIVE_ROOT_FOLDER=Course_RAG_Data

CURRENT_QUARTER=Spring2026

# Optional — OCR settings (defaults shown)
# OCR_DPI=200
# OCR_FALLBACK_THRESHOLD=30
```

### 3. Google Drive OAuth

Place your `oauth_credentials.json` (downloaded from Google Cloud Console) in `credentials/`, then run:

```bash
python scripts/setup_drive.py
```

This opens a browser for the one-time OAuth consent and saves `token.pickle`.

### 4. Initial embedding

```bash
python scripts/initial_embed.py
```

Downloads all PDFs and TXTs from Drive, chunks them, and loads embeddings into ChromaDB (`data/chroma_db/`). Scanned PDFs are automatically processed via Tesseract OCR.

### 5. Run locally

```bash
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://localhost:8000](http://localhost:8000) — log in with your admin credentials.

---

## Docker deployment

```bash
docker compose up -d --build
```

The compose file mounts `data/`, `credentials/`, and `.env` as volumes so state persists across container restarts.

### Oracle Cloud Free Tier (production)

```bash
# First time — provision the VPS
sudo ./scripts/setup_oracle.sh

# Deploy updates from your local machine
./scripts/deploy.sh <VPS_IP> <SSH_KEY_PATH>
```

HTTPS is handled by [Caddy](https://caddyserver.com/) via the `Caddyfile` — automatic TLS with Let's Encrypt.

---

## Course configuration

Courses are defined statically in [backend/config.py](backend/config.py) under the `COURSES` dict:

```python
COURSES = {
    "Spring2026": [
        CourseInfo("MSA408", "26S-MGMTMSA-408-LEC-2", "Operations_Analytics"),
        CourseInfo("MSA409", "26S-MGMTMSA-409-01/02", "Competitive_Analytics"),
        CourseInfo("MSA410", "26S-MGMTMSA-410-LEC-2", "Customer_Analytics"),
        CourseInfo("MSA413", "26S-MGMTMSA-413-SEM-1", "Industry_Seminar_II"),
    ],
}
```

Add new quarters/courses here. Drive folder structure is derived automatically from this registry.

---

## PDF processing

The pipeline handles two types of PDFs:

1. **Text-based PDFs** (slides with selectable text, syllabi) — text is extracted directly via PyMuPDF.
2. **Scanned / image-based PDFs** (photographed textbook pages, slides exported as images) — when PyMuPDF returns fewer than 30 characters per page, Tesseract OCR runs locally to extract text from the page image.

OCR runs entirely on-device (no external API calls), keeping costs at zero and avoiding rate limits. The OCR pipeline processes pages sequentially to stay within the Oracle Free Tier memory budget (6GB).

Tunable via `.env`:

| Setting | Default | Description |
|---|---|---|
| `OCR_DPI` | 200 | Render resolution for OCR (higher = more accurate but more RAM) |
| `OCR_FALLBACK_THRESHOLD` | 30 | Characters per page below which OCR is triggered |

---

## License

Private — UCLA MSBA coursework.
