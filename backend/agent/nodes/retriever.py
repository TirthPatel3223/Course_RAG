"""
Retriever Node — Queries ChromaDB for relevant document chunks.
Shared retriever used by deadline, summary, and general branches.
"""

import logging
from backend.agent.state import AgentState
from backend.config import get_settings
from backend.services.embedding_service import get_embedding_service
from backend.services.chroma_service import get_chroma_service

logger = logging.getLogger(__name__)


async def retriever(state: AgentState) -> dict:
    """
    Query ChromaDB for relevant chunks based on the user's query.
    Applies metadata filters based on detected course/quarter context.
    Uses deadline-boosted search for deadline queries.
    """
    settings = get_settings()
    embedder = get_embedding_service()
    chroma = get_chroma_service()

    query = state.get("retrieval_query", "")
    query_type = state.get("query_type", "general")
    detected_course = state.get("detected_course")
    detected_quarter = state.get("detected_quarter", settings.current_quarter)

    if not query:
        logger.warning("Empty retrieval query")
        return {"retrieved_chunks": [], "source_chunks_for_display": []}

    # Determine top_k based on query type
    top_k_map = {
        "deadline": settings.deadline_top_k,
        "summary": settings.summary_top_k,
        "general": settings.general_top_k,
    }
    top_k = top_k_map.get(query_type, settings.general_top_k)

    # Build metadata filter
    where_filter = None
    filter_conditions = []

    if detected_quarter:
        filter_conditions.append({"quarter": detected_quarter})
    if detected_course:
        filter_conditions.append({"course_id": detected_course})

    if len(filter_conditions) == 1:
        where_filter = filter_conditions[0]
    elif len(filter_conditions) > 1:
        where_filter = {"$and": filter_conditions}

    # Generate query embedding
    query_embedding = await embedder.embed_query(query)

    # Query ChromaDB
    if query_type == "deadline":
        # Use deadline-boosted search
        results = chroma.query_with_deadline_boost(
            query_embedding=query_embedding,
            top_k=top_k,
            where=where_filter,
        )
    else:
        results = chroma.query(
            query_embedding=query_embedding,
            top_k=top_k,
            where=where_filter,
        )

    # If no results with filters, try without course filter
    if not results and detected_course:
        logger.info("No results with course filter, trying without...")
        if detected_quarter:
            where_filter = {"quarter": detected_quarter}
        else:
            where_filter = None

        if query_type == "deadline":
            results = chroma.query_with_deadline_boost(
                query_embedding=query_embedding,
                top_k=top_k,
                where=where_filter,
            )
        else:
            results = chroma.query(
                query_embedding=query_embedding,
                top_k=top_k,
                where=where_filter,
            )

    logger.info(
        f"Retrieved {len(results)} chunks for '{query_type}' query "
        f"(course={detected_course}, quarter={detected_quarter})"
    )

    # Prepare display-friendly source chunks
    display_chunks = []
    for r in results:
        display_chunks.append({
            "text": r["document"][:500] + ("..." if len(r["document"]) > 500 else ""),
            "file_name": r["metadata"].get("file_name", "Unknown"),
            "course_id": r["metadata"].get("course_id", ""),
            "page_number": r["metadata"].get("page_number"),
            "chunk_index": r["metadata"].get("chunk_index"),
            "distance": round(r["distance"], 4),
            "drive_link": r["metadata"].get("drive_link", ""),
        })

    return {
        "retrieved_chunks": results,
        "source_chunks_for_display": display_chunks,
    }
