"""
Chat Routes — WebSocket-based chat with the LangGraph agent.
Handles real-time messaging, streaming responses, and upload approval.
"""

import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from langchain_core.messages import HumanMessage

from backend.api.auth import verify_ws_token
from backend.agent.graph import create_agent
from backend.services.session_service import get_session_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Store active WebSocket connections
active_connections: dict[str, WebSocket] = {}


async def _get_or_create_graph():
    """Lazy-init the agent graph (singleton)."""
    if not hasattr(_get_or_create_graph, "_graph"):
        _get_or_create_graph._graph = await create_agent()
    return _get_or_create_graph._graph


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket endpoint for real-time chat.

    Protocol:
    1. Client connects with ?token=<auth_token>
    2. Client sends JSON: {"type": "chat", "message": "...", "session_id": "..."}
    3. Server sends JSON: {"type": "response", "data": {...}}
    4. For uploads: {"type": "upload_approval", "data": {"decision": "approved"}}
    """
    token_payload = await verify_ws_token(websocket)
    if not token_payload:
        await websocket.close(code=4001, reason="Authentication required")
        return

    role = token_payload.get("role", "viewer")

    await websocket.accept()
    connection_id = str(uuid.uuid4())[:8]
    logger.info(f"WebSocket connected: {connection_id} (role={role})")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(websocket, "Invalid JSON message")
                continue

            msg_type = message.get("type", "chat")

            # Viewers may not upload
            if role == "viewer" and msg_type in ("upload_file", "upload_link", "upload_approval"):
                await _send_error(
                    websocket,
                    "File uploads are not available in Viewer mode. Contact Tirth for full access.",
                    code="VIEWER_RESTRICTED",
                )
                continue

            if msg_type == "chat":
                await _handle_chat(websocket, message, connection_id, role=role)
            elif msg_type == "upload_file":
                await _handle_upload_file(websocket, message, connection_id)
            elif msg_type == "upload_link":
                await _handle_upload_link(websocket, message, connection_id)
            elif msg_type == "upload_approval":
                await _handle_upload_approval(websocket, message, connection_id)
            else:
                await _send_error(websocket, f"Unknown message type: {msg_type}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {connection_id}")
    except Exception as e:
        logger.error(f"WebSocket error ({connection_id}): {e}")
        try:
            await _send_error(websocket, f"Server error: {str(e)}")
        except Exception:
            pass


VIEWER_ALLOWED_QUERY_TYPES = {"general", "deadline"}
VIEWER_MESSAGE_LIMIT = 10


async def _handle_chat(websocket: WebSocket, message: dict, conn_id: str, role: str = "admin"):
    """Handle a chat message."""
    user_message = message.get("message", "").strip()
    session_id = message.get("session_id", "")

    if not user_message:
        await _send_error(websocket, "Empty message")
        return

    # Viewer rate limiting
    if role == "viewer":
        sessions = get_session_service()
        count = sessions.get_viewer_message_count(session_id)
        if count >= VIEWER_MESSAGE_LIMIT:
            await _send_error(
                websocket,
                "You've reached the session limit. Contact Tirth for full access.",
                code="VIEWER_RATE_LIMIT",
            )
            return

    logger.info(f"[{conn_id}] Chat ({role}): '{user_message[:50]}...'")
    await _send_status(websocket, "thinking", "Processing your question...")

    try:
        graph = await _get_or_create_graph()

        input_state = {
            "messages": [HumanMessage(content=user_message)],
            "session_id": session_id,
        }

        thread_id = session_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        result = await graph.ainvoke(input_state, config=config)

        query_type = result.get("query_type", "unknown")

        # Viewers cannot use summarization queries
        if role == "viewer" and query_type not in VIEWER_ALLOWED_QUERY_TYPES:
            await _send_error(
                websocket,
                "Summarization is not available in Viewer mode. Contact Tirth for full access.",
                code="VIEWER_RESTRICTED",
            )
            return

        # Increment viewer message count after a successful response
        if role == "viewer":
            sessions = get_session_service()
            sessions.increment_viewer_message_count(session_id)

        response_data = {
            "message": result.get("final_response", "No response generated."),
            "query_type": query_type,
            "session_id": result.get("session_id", session_id),
            "provider": result.get("llm_provider", ""),
            "source_chunks": result.get("source_chunks_for_display", []),
            "relevant_files": result.get("response_files", []),
        }

        await websocket.send_json({
            "type": "response",
            "data": response_data,
        })

        logger.info(
            f"[{conn_id}] Response sent: type={query_type}, "
            f"length={len(response_data['message'])}"
        )

    except Exception as e:
        logger.error(f"[{conn_id}] Chat error: {e}", exc_info=True)
        await _send_error(websocket, f"Failed to process message: {str(e)}")


async def _handle_upload_file(websocket: WebSocket, message: dict, conn_id: str):
    """Handle a file upload via WebSocket (base64 encoded)."""
    import base64

    filename = message.get("filename", "unknown")
    file_data_b64 = message.get("data", "")
    session_id = message.get("session_id", "")

    if not file_data_b64:
        await _send_error(websocket, "No file data received")
        return

    try:
        file_bytes = base64.b64decode(file_data_b64)
    except Exception:
        await _send_error(websocket, "Invalid file data encoding")
        return

    logger.info(f"[{conn_id}] Upload: {filename} ({len(file_bytes)} bytes)")
    await _send_status(websocket, "processing", f"Processing {filename}...")

    try:
        graph = await _get_or_create_graph()

        input_state = {
            "messages": [HumanMessage(content=f"Upload file: {filename}")],
            "session_id": session_id,
            "upload_file_info": {
                "name": filename,
                "source": "direct_upload",
                "bytes": file_bytes,
            },
        }

        thread_id = f"upload_{session_id}_{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}

        # Run graph — it will pause at human_approval_gate
        result = await graph.ainvoke(input_state, config=config)

        # Check if we're in interrupted state (waiting for approval)
        state = await graph.aget_state(config)
        if state.next and "human_approval_gate" in state.next:
            # Send approval request to user
            await websocket.send_json({
                "type": "approval_request",
                "data": {
                    "message": result.get("final_response", ""),
                    "proposed_location": result.get("proposed_location", {}),
                    "thread_id": thread_id,
                    "session_id": result.get("session_id", session_id),
                },
            })
        else:
            # Graph completed without interrupt (error or skip)
            await websocket.send_json({
                "type": "response",
                "data": {
                    "message": result.get("final_response", "Upload processed."),
                    "query_type": "upload",
                    "session_id": result.get("session_id", session_id),
                },
            })

    except Exception as e:
        logger.error(f"[{conn_id}] Upload error: {e}", exc_info=True)
        await _send_error(websocket, f"Upload failed: {str(e)}")


async def _handle_upload_link(websocket: WebSocket, message: dict, conn_id: str):
    """Handle a Google Drive link upload."""
    drive_link = message.get("link", "").strip()
    session_id = message.get("session_id", "")

    if not drive_link:
        await _send_error(websocket, "No Drive link provided")
        return

    logger.info(f"[{conn_id}] Drive link upload: {drive_link[:60]}...")
    await _send_status(websocket, "processing", "Downloading from Google Drive...")

    try:
        graph = await _get_or_create_graph()

        input_state = {
            "messages": [HumanMessage(content=f"Upload from Drive: {drive_link}")],
            "session_id": session_id,
            "upload_file_info": {
                "name": "drive_file",
                "source": "drive_link",
                "drive_link": drive_link,
            },
        }

        thread_id = f"upload_{session_id}_{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}

        result = await graph.ainvoke(input_state, config=config)

        state = await graph.aget_state(config)
        if state.next and "human_approval_gate" in state.next:
            await websocket.send_json({
                "type": "approval_request",
                "data": {
                    "message": result.get("final_response", ""),
                    "proposed_location": result.get("proposed_location", {}),
                    "thread_id": thread_id,
                    "session_id": result.get("session_id", session_id),
                },
            })
        else:
            await websocket.send_json({
                "type": "response",
                "data": {
                    "message": result.get("final_response", ""),
                    "query_type": "upload",
                    "session_id": result.get("session_id", session_id),
                },
            })

    except Exception as e:
        logger.error(f"[{conn_id}] Drive upload error: {e}", exc_info=True)
        await _send_error(websocket, f"Drive upload failed: {str(e)}")


async def _handle_upload_approval(websocket: WebSocket, message: dict, conn_id: str):
    """Handle user's approval/rejection of upload location."""
    decision = message.get("decision", "")  # "approved", "rejected", or "custom"
    custom_location = message.get("custom_location")  # structured path from path picker
    thread_id = message.get("thread_id", "")
    session_id = message.get("session_id", "")

    if not thread_id:
        await _send_error(websocket, "Missing thread_id for approval")
        return

    logger.info(f"[{conn_id}] Upload approval: {decision} (thread: {thread_id})")
    await _send_status(websocket, "processing", "Executing upload...")

    try:
        graph = await _get_or_create_graph()
        config = {"configurable": {"thread_id": thread_id}}

        # Build state update — custom path overrides the LLM-proposed location
        if decision == "custom" and custom_location:
            state_update = {
                "human_decision": "approved",
                "proposed_location": custom_location,
            }
            logger.info(f"[{conn_id}] Custom path: {custom_location.get('full_path')}")
        else:
            state_update = {"human_decision": decision}

        await graph.aupdate_state(
            config,
            state_update,
            as_node="human_approval_gate",
        )

        # Continue execution
        result = await graph.ainvoke(None, config=config)

        await websocket.send_json({
            "type": "response",
            "data": {
                "message": result.get("final_response", "Upload complete."),
                "query_type": "upload",
                "session_id": result.get("session_id", session_id),
                "upload_result": result.get("upload_result", {}),
            },
        })

    except Exception as e:
        logger.error(f"[{conn_id}] Approval error: {e}", exc_info=True)
        await _send_error(websocket, f"Upload execution failed: {str(e)}")


async def _send_error(websocket: WebSocket, message: str, code: str = ""):
    """Send an error message to the client."""
    payload: dict = {"message": message}
    if code:
        payload["code"] = code
    await websocket.send_json({"type": "error", "data": payload})


async def _send_status(websocket: WebSocket, status: str, message: str):
    """Send a status update to the client."""
    await websocket.send_json({
        "type": "status",
        "data": {"status": status, "message": message},
    })
