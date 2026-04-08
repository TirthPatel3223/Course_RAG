# Course RAG Pipeline — Task Tracker

## Phase 1: Foundation ✅ (20/20 tests)
- [x] Config, services, schemas, tests

## Phase 2: Google Drive Integration ✅ (13/13 tests)
- [x] Drive service, setup wizard, embedding pipeline

## Phase 3: LangGraph Agent ✅
- [x] State, prompts, 11 nodes, graph with human-in-the-loop

## Phase 4: Backend API ✅
- [x] `backend/main.py` — FastAPI app with CORS, lifecycle events, static serving
- [x] `backend/api/auth.py` — HMAC-signed token auth (no JWT dependency)
- [x] `backend/api/routes_chat.py` — WebSocket chat (chat, upload, approval)
- [x] `backend/api/routes_admin.py` — Stats, re-embed, session cleanup, Drive tree
- [x] Endpoints verified:
  - `POST /api/login` — password → token
  - `GET /api/verify` — token validation
  - `GET /api/health` — health check
  - `WS /ws/chat` — real-time chat
  - `GET /api/chat/history/{id}` — REST fallback
  - `GET /api/admin/stats` — system statistics
  - `POST /api/admin/reembed` — trigger re-embedding
  - `GET /api/admin/reembed/status` — embedding progress
  - `POST /api/admin/sessions/cleanup` — cleanup
  - `GET /api/admin/drive/tree` — folder tree
  - `GET /api/admin/drive/files` — file listing
- [x] All 33 tests still passing

## Phase 5: Frontend ← NEXT
- [ ] Login page
- [ ] Chat interface with markdown rendering
- [ ] File upload (drag-and-drop + Drive link)
- [ ] Admin panel (stats, re-embed, Drive tree)

## Phase 6-8: Data load, Docker, Oracle Cloud
