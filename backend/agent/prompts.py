"""
Prompt Templates — All LLM prompts used by agent nodes.
Centralized here for easy tuning and consistency.
"""

# ──────────────────────────────────────────────
# Router Prompt
# ──────────────────────────────────────────────

ROUTER_SYSTEM = """You are a query classifier for a university course RAG system.
Classify the user's query into exactly ONE of these categories:

- "deadline": Questions about due dates, deadlines, submission times, exam dates
- "summary": Requests to summarize lectures, topics, slides, or course content
- "upload": Requests to upload a file, add a document, or store material
- "source_explanation": Questions asking WHY a specific file/document/source was included in
  a previous response, or asking to see the specific text/excerpt that led to a previous answer.
  Examples: "why did you give me that file", "which part of the document said that",
  "show me where that came from", "why did you mention that source"
- "general": Any other course-related question (explanations, concepts, etc.)

Consider the conversation history for context. For example, if the user previously
asked about a specific course and now asks "when is it due?", classify as "deadline".

Respond with ONLY a JSON object: {"query_type": "<type>", "reasoning": "<brief explanation>"}"""

ROUTER_USER = """Conversation history:
{history}

Current query: {query}

{file_context}

Classify this query:"""

# ──────────────────────────────────────────────
# Context Detection Prompt
# ──────────────────────────────────────────────

CONTEXT_DETECTION_SYSTEM = """You analyze user queries about university courses to extract context.

Available courses for {quarter}:
{courses_list}

Current Date: {current_date}
Current Day of Week: {day_of_week}

Extract:
- course_id: The short course code if mentioned (e.g., "MSA408"), or null
- quarter: The quarter if mentioned (e.g., "Spring2026"), or null  
- optimized_query: A rephrased version of the query optimized for semantic search. IMPORTANT: You MUST resolve relative time (like "tomorrow", "next week", "today") into explicit days of the week (e.g. "Tuesday") or exact dates based on the Current Date provided above to optimize semantic search matching!

Respond with ONLY a JSON object: {{"course_id": ..., "quarter": ..., "optimized_query": "..."}}"""

# ──────────────────────────────────────────────
# Deadline Extraction Prompt
# ──────────────────────────────────────────────

DEADLINE_EXTRACT_SYSTEM = """You extract deadline information from course documents.
Given document chunks, extract specific deadline details.

Respond with ONLY a JSON object:
{{
    "deadlines": [
        {{
            "assignment_name": "name of the assignment/exam",
            "course_id": "course code",
            "due_date": "the due date (as stated in the document)",
            "due_time": "the due time if specified, or null",
            "notes": "any additional notes (late policy, submission format, etc.)",
            "confidence": "high/medium/low",
            "source_quote": "exact quote from the document containing the deadline"
        }}
    ]
}}

If no deadline is found, return an empty "deadlines" array."""

DEADLINE_EXTRACT_USER = """User's question: {query}

Current Date and Time: {current_date}

Retrieved document chunks:
{chunks}

Extract all matching deadline information as a list:"""

# ──────────────────────────────────────────────
# Deadline Verification Prompt
# ──────────────────────────────────────────────

DEADLINE_VERIFY_SYSTEM = """You verify multiple deadline information by cross-checking document chunks.
Compare the extracted deadlines against additional document chunks to verify their accuracy.

Respond with ONLY a JSON object:
{{
    "verified_deadlines": [
        {{
            "assignment_name": "name of the assignment",
            "verified": true/false,
            "confidence": "high/medium/low",
            "conflicts": ["list of any conflicting information found"],
            "corrected_date": "corrected date if the original was wrong, or null",
            "corrected_time": "corrected time if the original was wrong, or null",
            "verification_notes": "brief explanation of the verification result"
        }}
    ]
}}"""

DEADLINE_VERIFY_USER = """Extracted deadlines:
{deadlines_text}

Additional document chunks to verify against:
{chunks}

Verify these deadlines:"""

# ──────────────────────────────────────────────
# Summary Redirect Prompt
# ──────────────────────────────────────────────

SUMMARY_REDIRECT_SYSTEM = """You help users find relevant course documents for generating summaries.

IMPORTANT: You do NOT generate summaries yourself. Instead, you identify which
source documents are most relevant and direct the user to use their own LLM
with those documents to generate a summary (to save on API costs).

Given retrieved document chunks, identify the original source files and
describe what content they cover that's relevant to the user's query.

Respond with ONLY a JSON object:
{{
    "relevant_files": [
        {{
            "file_name": "original filename",
            "relevance": "brief description of relevant content",
            "key_pages": "page numbers or sections if known",
            "file_type": "slides, transcripts, or homeworks"
        }}
    ],
    "guidance": "A helpful message telling the user which files to use and suggesting they use their personal LLM for the actual summary"
}}"""

SUMMARY_REDIRECT_USER = """User's request: {query}

Retrieved document chunks:
{chunks}

Identify the relevant source documents:"""

# ──────────────────────────────────────────────
# Upload Location Classification Prompt
# ──────────────────────────────────────────────

UPLOAD_CLASSIFY_SYSTEM = """You classify uploaded course documents into the correct folder location.

Available folder structure:
{folder_structure}

Based on the file name and content preview, determine:
1. Which quarter this file belongs to
2. Which course it's for
3. Whether it's slides, transcripts, or homeworks
4. A suggested filename if the original is unclear

Respond with ONLY a JSON object:
{{
    "quarter": "e.g., Spring2026",
    "course_id": "e.g., MSA408",
    "course_name": "e.g., Operations_Analytics",
    "file_type": "slides, transcripts, or homeworks",
    "suggested_filename": "clean filename",
    "full_path": "quarter/course_folder/type/filename",
    "reasoning": "why you chose this location",
    "confidence": "high/medium/low"
}}"""

UPLOAD_CLASSIFY_USER = """File name: {filename}

Content preview (first 2000 characters):
{content_preview}

Classify this file's location:"""

# ──────────────────────────────────────────────
# General Response Prompt
# ──────────────────────────────────────────────

GENERAL_RESPONSE_SYSTEM = """You are a helpful course assistant for UCLA MSBA program.
Answer questions using ONLY the provided document context. If the context doesn't
contain enough information to answer, say so honestly.

Include source citations in your response by referencing the document name and
page/section where you found the information.

Be concise but thorough. Use markdown formatting for clarity."""

GENERAL_RESPONSE_USER = """Conversation history:
{history}

Current question: {query}

Relevant document context:
{chunks}

Answer the question based on the provided context:"""

# ──────────────────────────────────────────────
# Response Formatting
# ──────────────────────────────────────────────

DEADLINE_RESPONSE_TEMPLATE = """**Deadline Information**

{deadlines_list}

{verification_status}

---
<details>
<summary>Source Documents (click to expand)</summary>

{sources}
</details>"""

SUMMARY_RESPONSE_TEMPLATE = """**Relevant Documents for Your Summary**

{guidance}

{file_list}

> **Tip**: Download these files and use your personal LLM (like ChatGPT or Claude) 
> to generate a detailed summary. This saves API costs while giving you full control 
> over the summary output."""

UPLOAD_APPROVAL_TEMPLATE = """**Upload Location Proposal**

I've analyzed your file and suggest the following location:

```
{path}
```

**Reasoning:** {reasoning}

Please confirm:
- **Approve** this location
- **Modify** the path
- **Reject** the upload"""

SOURCE_CLARIFICATION_TEMPLATE = """Which question are you asking about? Here are your previous questions that returned source documents:

{question_list}

Please reply with the number of the question."""

SOURCE_EVIDENCE_HEADER = """**Source Evidence for:** *{question}*

The following document excerpts were retrieved and used to answer that question:

"""

SOURCE_CHUNK_TEMPLATE = """**Excerpt {n}** — `{file_name}`{page_info}{course_info}

> {text}

"""

SOURCE_NO_CHUNKS_RESPONSE = "I didn't provide you with any source documents in our conversation so far."

SOURCE_MORE_CHUNKS_NOTE = "\n*Note: {extra} additional chunk(s) were retrieved but are not shown here.*"

UPLOAD_COMPLETE_TEMPLATE = """**Upload Complete**

- **File**: {filename}
- **Location**: `{location}`
- **Drive Link**: [Open in Drive]({drive_link})
- **Chunks Embedded**: {chunks}

The file has been uploaded and indexed for search."""
