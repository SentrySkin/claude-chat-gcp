import os
import time
from flask import Request, jsonify, make_response
import functions_framework
from markdown import markdown as md_to_html
from selectolax.parser import HTMLParser

from systemprompt import systemprompt  # your existing prompt
from vertexai import init
from anthropic import AnthropicVertex
from google.cloud import logging as cloud_logging
from google.cloud import bigquery

# NEW: auth for REST call to RAG
import google.auth
from google.auth.transport.requests import AuthorizedSession
from vertexai.preview.generative_models import GenerativeModel
from vertexai import init as vertex_init


# ---------------- Config ----------------
PROJECT_ID = os.getenv("GCP_PROJECT", "christinevalmy")
REGION = os.environ.get("FUNCTION_REGION", "us-east5")       # Anthropic model region
RAG_REGION = os.environ.get("RAG_REGION", "us-central1")     # RAG corpus region (must match corpus)
MODEL = os.environ.get("MODEL", "claude-3-5-haiku@20241022")  #claude-sonnet-4@20250514
CORPUS_RESOURCE = os.environ.get(
    "RAG_CORPUS",
    "projects/christinevalmy/locations/us-central1/ragCorpora/8070450532247928832"
)

# Flags
USE_SUMMARIZER = True   # toggle summarization on/off
MAX_TURNS = 6           # keep this many turns before summarizing

# ---------------- Init ----------------
# Model client (Anthropic)
init(project=PROJECT_ID, location=REGION)
anthropic_client = AnthropicVertex(region=REGION, project_id=PROJECT_ID)

# Summarizer (Gemini Flash)
vertex_init(project=PROJECT_ID, location="us-central1")
flash_model = GenerativeModel("gemini-2.0-flash-001")

# Cloud Logging
logging_client = cloud_logging.Client()
logger = logging_client.logger("claude-conversations")
bq_client = bigquery.Client()
BQ_TABLE = f"{PROJECT_ID}.assistant_logs.claude_conversations"


def log_to_bigquery(row: dict):
    """Insert a row into BigQuery."""
    try:
        errors = bq_client.insert_rows_json(BQ_TABLE, [row])
        if errors:
            logger.log_struct({"event": "bq_insert_error", "errors": errors, "row": row}, severity="ERROR")
    except Exception as e:
        logger.log_struct({"event": "bq_exception", "detail": str(e)}, severity="ERROR")


# ---------------- Helpers ----------------
def _folder_from_uri(label: str):
    """If label is a GCS URI, return a folder-ish prefix for display."""
    if label and label.startswith("gs://"):
        path = label[len("gs://"):]
        if "/" in path:
            bucket, rest = path.split("/", 1)
            return f"gs://{bucket}/" + rest.rsplit("/", 1)[0] if "/" in rest else f"gs://{bucket}"
    return None

def generate_prompt(user_input: str) -> str:
    return systemprompt + "\nUser: " + user_input

def md_to_plaintext(md: str) -> str:
    html = md_to_html(md)
    tree = HTMLParser(html)
    body = tree.body or tree.root
    return body.text(separator="\n").replace("\\u2019", "'").replace("\\u2014", "—").strip()

# --------- RAG retrieval via REST ----------
def retrieve_from_rag(query_text: str, top_k: int = 8):
    """Retrieve contexts using Vertex AI RAG REST API (v1beta1: retrieveContexts)."""
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(creds)

    url = (
        f"https://{RAG_REGION}-aiplatform.googleapis.com/v1beta1/"
        f"projects/{PROJECT_ID}/locations/{RAG_REGION}:retrieveContexts"
    )
    payload = {
        "vertex_rag_store": {
            "rag_resources": {
                "rag_corpus": CORPUS_RESOURCE
            }
        },
        "query": {
            "text": query_text,
            "similarity_top_k": top_k
        }
    }

    resp = session.post(url, json=payload, timeout=30)
    if resp.status_code != 200:
        logger.log_struct(
            {"event": "retrieval_error", "status": resp.status_code, "body": resp.text},
            severity="ERROR"
        )
        return [], []

    data = resp.json() or {}
    items = data.get("contexts", {}).get("contexts", [])
    snippets, sources = [], []

    for c in items[:top_k]:
        text = (c.get("chunk") or {}).get("text") or c.get("text") or ""
        if text.strip():
            snippets.append(text.strip()[:2500])
        src = c.get("sourceUri") or c.get("sourceDisplayName") or "unknown_source"
        folder = _folder_from_uri(src)
        sources.append({"label": src, **({"folder": folder} if folder else {})})

    logger.log_struct(
        {"event": "retrieval_debug", "match_count": len(items), "first_source": (sources[0] if sources else None)},
        severity="INFO"
    )
    return snippets, sources

# --------- History Management ----------
def build_history(raw_history, base_prompt: str):
    """
    Manage conversation history:
    - Keep last MAX_TURNS turns as-is
    - Summarize older turns with Gemini Flash (fallback: concat)
    - Append latest query as 'user' message
    """
    older = raw_history[:-MAX_TURNS]
    recent = raw_history[-MAX_TURNS:]

    messages = []

    if older:
        if USE_SUMMARIZER:
            try:
                convo_text = "\n".join(
                    f"{m['role']}: {m['content'][0]['text']}"
                    for m in older if m.get("content")
                )
                prompt = f"""
                Summarize this conversation in 4–5 sentences.
                Focus only on: program interest, location, schedule, tuition/aid,
                objections, and next steps. Ignore small talk.

                Conversation:
                {convo_text}
                """
                resp = flash_model.generate_content([prompt])
                summary_text = resp.candidates[0].content.parts[0].text.strip()
                messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": f"Earlier conversation summary: {summary_text}"}]
                })
            except Exception as e:
                logger.log_struct({"event": "flash_summary_error", "detail": str(e)}, severity="WARNING")
                concat_summary = "Earlier conversation:\n" + " ".join(
                    f"{m['role']}: {m['content'][0]['text']}"
                    for m in older if m.get("content")
                )[:800]
                messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": concat_summary}]
                })
        else:
            concat_summary = "Earlier conversation:\n" + " ".join(
                f"{m['role']}: {m['content'][0]['text']}"
                for m in older if m.get("content")
            )[:800]
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": concat_summary}]
            })

    for m in recent:
        role = (m.get("role") or "").lower()
        if role in {"user", "assistant"} and m.get("content"):
            messages.append({"role": role, "content": m["content"]})

    messages.append({
        "role": "user",
        "content": [{"type": "text", "text": base_prompt}]
    })

    return messages

# ---------------- HTTP Entry ----------------
@functions_framework.http
def app(request: Request):
    try:
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id", "unknown")
        thread_id = data.get("thread_id", "unknown")
        history = (data.get("history") or [])[-50:]

        user_query = (data.get("query") or data.get("message") or data.get("text") or "").strip()

        logger.log_struct({
            "event": "user_message",
            "user_id": user_id,
            "thread_id": thread_id,
            "message": user_query,
            "role": "user"
        }, severity="INFO")

        log_to_bigquery({
            "user_id": user_id,
            "thread_id": thread_id,
            "role": "user",
            "message": user_query,
            "model": None,
            "latency_sec": None
        })

        try:
            snippets, sources = retrieve_from_rag(user_query, top_k=8)
            context_str = "\n\n---\n".join(snippets)
        except Exception as e:
            logger.log_struct({"event": "rag_error", "detail": str(e)}, severity="WARNING")
            context_str, sources = "", []

        base_prompt = generate_prompt(f"Retrieved context:\n{context_str}\n\nUser question: {user_query}")
        messages = build_history(history, base_prompt)

        start = time.time()
        resp = anthropic_client.messages.create(
            model=MODEL,
            messages=messages,
            max_tokens=1000,
            temperature=0.7,
            top_p=0.8
        )
        resp = anthropic_client.messages.create(
            model=MODEL,
            messages=messages,
            max_tokens=1000,
            temperature=0.7,
            top_p=0.8
        )
        resp = anthropic_client.messages.create(
            model=MODEL,
            messages=messages,
            max_tokens=1000,
            temperature=0.7,
            top_p=0.8
        )
        latency = round(time.time() - start, 2)

        answer_md = "\n\n".join(getattr(b, "text", "") for b in resp.content if getattr(b, "text", None))
        answer_text = md_to_plaintext(answer_md)

        logger.log_struct({
            "event": "assistant_reply",
            "user_id": user_id,
            "thread_id": thread_id,
            "message": answer_text,
            "role": "assistant",
            "model": MODEL,
            "latency_sec": latency
        }, severity="INFO")

        log_to_bigquery({
            "user_id": user_id,
            "thread_id": thread_id,
            "role": "assistant",
            "message": answer_text,
            "model": MODEL,
            "latency_sec": latency
        })

        return make_response(jsonify(
            response=answer_text,
            model=MODEL,
            latency_sec=latency,
            rag_corpus=CORPUS_RESOURCE,
            rag_snippets=snippets,
            rag_sources=sources
        ), 200)

    except Exception as e:
        logger.log_struct({
            "event": "error",
            "error_type": type(e).__name__,
            "detail": str(e)
        }, severity="ERROR")
        return make_response(jsonify(error=type(e).__name__, detail=str(e)), 500)
