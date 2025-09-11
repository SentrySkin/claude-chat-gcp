import os
import time
import re
import asyncio
from concurrent.futures import ThreadPoolExecutor
from flask import Request, jsonify, make_response
import functions_framework
from markdown import markdown as md_to_html
from selectolax.parser import HTMLParser
from datetime import datetime


# Import your updated system prompt functions
from systemprompt import get_system_prompt_for_request, detect_enrollment_completion_state, extract_contact_info
from vertexai import init
from anthropic import AnthropicVertex
from google.cloud import logging as cloud_logging
from google.cloud import bigquery

# NEW: auth for REST call to RAG
import google.auth
from google.auth.transport.requests import AuthorizedSession
from vertexai.preview.generative_models import GenerativeModel
from vertexai import init as vertex_init

# ---------------- Optimized Config ----------------
PROJECT_ID = os.getenv("GCP_PROJECT", "christinevalmy")
REGION = os.environ.get("FUNCTION_REGION", "us-east5")
RAG_REGION = os.environ.get("RAG_REGION", "us-central1")
MODEL = os.environ.get("MODEL", "claude-3-7-sonnet@20250219")  # Using stable, fast model
CORPUS_RESOURCE = os.environ.get(
    "RAG_CORPUS",
    "projects/christinevalmy/locations/us-central1/ragCorpora/5685794529555251200"#8070450532247928832
)

# Optimized for better context + speed balance
USE_SUMMARIZER = True
MAX_TURNS = 15  # Increased for better context retention
RAG_TOP_K = 10   # Reduced for speed while maintaining quality
RAG_SNIPPET_LENGTH = 2500  # Shorter snippets for faster processing

# ---------------- Init ----------------
init(project=PROJECT_ID, location=REGION)
anthropic_client = AnthropicVertex(region=REGION, project_id=PROJECT_ID)
# anthropic_client = get_client(region=REGION, project_id=PROJECT_ID)

# def get_client(region=REGION, project_id=PROJECT_ID):
#     # call all models health-check
#     # return the active model
#     try:
#         return AnthropicVertex(region=REGION, project_id=PROJECT_ID)
#     except:
#         pass

vertex_init(project=PROJECT_ID, location="us-central1")
flash_model = GenerativeModel("claude-3-7-sonnet@20250219")

logging_client = cloud_logging.Client()
logger = logging_client.logger("claude-conversations")
bq_client = bigquery.Client()
BQ_TABLE = f"{PROJECT_ID}.assistant_logs.claude_conversations"

# Thread pool for async operations
executor = ThreadPoolExecutor(max_workers=3)

def log_to_bigquery(row: dict):
    """Insert a row into BigQuery asynchronously."""
    def _log():
        try:
            errors = bq_client.insert_rows_json(BQ_TABLE, [row])
            if errors:
                logger.log_struct({"event": "bq_insert_error", "errors": errors, "row": row}, severity="ERROR")
        except Exception as e:
            logger.log_struct({"event": "bq_exception", "detail": str(e)}, severity="ERROR")
    
    # Run BigQuery logging asynchronously to not block response
    executor.submit(_log)

# ---------------- Helper Functions ----------------
def _folder_from_uri(label: str):
    """If label is a GCS URI, return a folder-ish prefix for display."""
    if label and label.startswith("gs://"):
        path = label[len("gs://"):]
        if "/" in path:
            bucket, rest = path.split("/", 1)
            return f"gs://{bucket}/" + rest.rsplit("/", 1)[0] if "/" in rest else f"gs://{bucket}"
    return None

def md_to_plaintext(md: str) -> str:
    """Optimized markdown to plaintext conversion."""
    if not md or len(md) < 10:
        return md
    
    html = md_to_html(md)
    tree = HTMLParser(html)
    body = tree.body or tree.root
    return body.text(separator="\n").replace("\\u2019", "'").replace("\\u2014", "—").strip()

# --------- Optimized Completion Detection ----------------
def ultra_fast_completion_check(user_query, history):
    """
    Ultra-fast completion detection with minimal processing
    """
    user_query_lower = user_query.lower().strip()
    
    # Remove topic prefix if present
    if user_query_lower.startswith("[topic:"):
        user_query_lower = user_query_lower.split("]", 1)[1].strip() if "]" in user_query_lower else user_query_lower
    
    # Quick completion signals (expanded list)
    completion_signals = {
        "thanks", "thank you", "nope", "no", "sounds good", "that's correct", 
        "im good", "i'm good", "that's all", "nothing else", "looks good", 
        "perfect", "ok", "okay", "cool", "great", "awesome", "yep", "yes that's correct"
    }
    
    # Fast exact match check
    if user_query_lower in completion_signals:
        # Quick scan for contact info in last 8 messages (much faster than full history)
        recent_messages = history[-8:] if len(history) > 8 else history
        recent_text = " ".join([
            msg.get("content", [{}])[0].get("text", "")[:200]  # Only check first 200 chars
            for msg in recent_messages if msg.get("content")
        ])
        
        # Fast contact detection
        has_email = "@" in recent_text
        has_digits = sum(1 for c in recent_text if c.isdigit()) >= 7
        has_enrollment = "enrollment" in recent_text.lower()
        
        return has_email and has_digits and has_enrollment
    
    return False

# --------- Smart RAG Retrieval ----------------
def smart_retrieve_from_rag(query_text: str, conversation_stage: str = "active"):
    """
    Intelligent RAG retrieval based on conversation stage
    """
    # Skip RAG for certain completion scenarios
    if conversation_stage == "completion":
        return [], []
    
    # Reduce RAG calls for post-enrollment stages
    if conversation_stage in ["post_enrollment", "enrollment_collection"]:
        top_k = 3
    else:
        top_k = RAG_TOP_K
    
    try:
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

        resp = session.post(url, json=payload, timeout=20)  # Reduced timeout
        if resp.status_code != 200:
            logger.log_struct(
                {"event": "retrieval_error", "status": resp.status_code},
                severity="WARNING"
            )
            return [], []

        data = resp.json() or {}
        items = data.get("contexts", {}).get("contexts", [])
        snippets, sources = [], []

        # Smart relevance filtering with schedule priority
        relevance_keywords = [
            query_text.lower(), 'esthetic', 'nail', 'wax', 'makeup', 'barbering',
            'program', 'course', 'schedule', 'start date', 'start dates', 'when',
            'price', 'tuition', 'admission', 'enrollment', 'financial aid',
            '2025', 'january', 'february', 'march', 'april', 'may', 'june',
            'july', 'august', 'september', 'october', 'november', 'december'
        ]

        for c in items[:top_k]:
            text = (c.get("chunk") or {}).get("text") or c.get("text") or ""
            if text.strip():
                # Quick relevance check
                text_lower = text.lower()
                if any(keyword in text_lower for keyword in relevance_keywords):
                    snippets.append(text.strip()[:RAG_SNIPPET_LENGTH])
            
            src = c.get("sourceUri") or c.get("sourceDisplayName") or "unknown_source"
            folder = _folder_from_uri(src)
            sources.append({"label": src, **({"folder": folder} if folder else {})})

        return snippets[:3], sources[:3]  # Limit to top 3 for speed

    except Exception as e:
        logger.log_struct({"event": "rag_error", "detail": str(e)}, severity="WARNING")
        return [], []

# --------- Optimized History Management ----------------
def build_optimized_history(raw_history, base_prompt: str, conversation_stage: str = "active"):
    """
    Smart history management based on conversation stage (Claude-only version).
    Uses Claude for summarization instead of Gemini.
    """
    if conversation_stage == "completion":
        # Minimal history for completion
        recent = raw_history[-3:]
    else:
        # Full history management for active conversation
        older = raw_history[:-MAX_TURNS]
        recent = raw_history[-MAX_TURNS:]

    messages = []

    # Only summarize if we have significant older history
    if conversation_stage != "completion" and older and len(older) > 3:
        try:
            # Smarter conversation filtering for summarization
            key_exchanges = []
            for m in older:
                if m.get("content"):
                    text = m['content'][0]['text']
                    # Prioritize enrollment-relevant content
                    if any(keyword in text.lower() for keyword in [
                        'esthetic', 'nail', 'wax', 'makeup', 'program', 'course',
                        'new york', 'new jersey', 'ny', 'nj', 
                        'full time', 'part time', 'evening', 'weekend',
                        'price', 'cost', 'tuition', 'financial aid',
                        'name', 'email', 'phone', 'contact', '@', 'enrollment'
                    ]):
                        key_exchanges.append(f"{m['role']}: {text[:300]}")  # Limit length
            
            if key_exchanges:
                convo_text = "\n".join(key_exchanges[-6:])  # Last 6 relevant exchanges
                prompt = f"""
                Summarize key enrollment details in 2 sentences:
                - Program interest and location
                - Contact info status
                
                Conversation:
                {convo_text}
                """

                # ✅ Claude call instead of Gemini
                resp = anthropic_client.messages.create(
                    model=MODEL,  # e.g. "claude-3-7-sonnet@20250219"
                    system="You are a helpful assistant that summarizes conversations.",
                    messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                    max_tokens=200,
                    temperature=0.1
                )
                summary_text = resp.content[0].text.strip()

                messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": f"Context: {summary_text}"}]
                })
        except Exception as e:
            logger.log_struct({"event": "claude_summary_error", "detail": str(e)}, severity="WARNING")
            # Fallback: include simple key terms
            key_terms = set()
            for m in older[-5:]:  # Only check last 5 for speed
                if m.get("content"):
                    text = m['content'][0]['text'].lower()
                    if 'esthetic' in text: key_terms.add('esthetics')
                    if 'nail' in text: key_terms.add('nails')
                    if 'new york' in text or 'ny' in text: key_terms.add('NY campus')
                    if 'new jersey' in text or 'nj' in text: key_terms.add('NJ campus')
                    if '@' in text: key_terms.add('email provided')
            
            if key_terms:
                messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": f"Context: {', '.join(key_terms)}"}]
                })

    # Add recent conversation turns
    for m in recent:
        role = (m.get("role") or "").lower()
        if role in {"user", "assistant"} and m.get("content"):
            messages.append({"role": role, "content": m["content"]})

    # Add current query
    messages.append({
        "role": "user",
        "content": [{"type": "text", "text": base_prompt}]
    })

    return messages

# --------- Conversation State Analysis ----------------
def analyze_conversation_state(history, user_query):
    """
    Fast conversation state analysis
    """
    try:
        has_contact_info, completion_signal, enrollment_shared = detect_enrollment_completion_state(history, user_query)
        
        if completion_signal and has_contact_info and enrollment_shared:
            return "completion"
        elif has_contact_info and enrollment_shared:
            return "post_enrollment"
        elif has_contact_info:
            return "enrollment_ready"
        else:
            # Check for other conversation stages
            from systemprompt import detect_enrollment_ready, detect_enrollment_info_collected, detect_pricing_inquiry, detect_payment_inquiry
            
            # Check if user is asking about pricing
            if detect_pricing_inquiry(user_query):
                return "pricing"
            
            # Check if user is asking about payment options
            if detect_payment_inquiry(user_query):
                return "payment_options"
            
            # Check if user is ready for enrollment but missing contact info
            enrollment_ready = detect_enrollment_ready(history, user_query)
            enrollment_info_collected = detect_enrollment_info_collected(history)
            
            if enrollment_ready and not enrollment_info_collected:
                return "enrollment_collection"
            else:
                return "active"
    except:
        return "active"  # Fallback to active state

# --------- Optimized Claude Parameters ----------------
def get_optimized_claude_params(conversation_stage, user_query_length):
    """
    Dynamic Claude parameters based on conversation state and query complexity
    """
    base_params = {
        "temperature": 0.2,
        "top_p": 0.8
    }
    
    if conversation_stage == "completion":
        return {**base_params, "max_tokens": 100, "temperature": 0.1}
    elif conversation_stage == "post_enrollment":
        return {**base_params, "max_tokens": 200, "temperature": 0.2}
    elif conversation_stage == "enrollment_collection":
        return {**base_params, "max_tokens": 300, "temperature": 0.2}
    elif conversation_stage in ["pricing", "payment_options"]:
        return {**base_params, "max_tokens": 400, "temperature": 0.2}
    elif user_query_length < 20:  # Short queries
        return {**base_params, "max_tokens": 250}
    else:  # Longer, complex queries
        return {**base_params, "max_tokens": 350}

# ---------------- Main HTTP Entry ----------------
@functions_framework.http
def app(request: Request):
    start_total = time.time()
    
    try:
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id", "unknown")
        thread_id = data.get("thread_id", "unknown")
        history = (data.get("history") or [])[-30:]  # Limit history window for performance

        user_query = (data.get("query") or data.get("message") or data.get("text") or "").strip()
        
        # Remove topic prefix if present
        if user_query.startswith("[TOPIC:"):
            user_query = user_query.split("]", 1)[1].strip() if "]" in user_query else user_query
        
        # Ultra-fast completion check
        if ultra_fast_completion_check(user_query, history):
            completion_message = "Perfect! Thank you for your interest in Christine Valmy International School. Our enrollment advisor will reach out to you soon. We look forward to welcoming you to the Christine Valmy family!"
            
            logger.log_struct({
                "event": "ultra_fast_completion",
                "user_id": user_id,
                "thread_id": thread_id,
                "message": user_query,
                "total_latency": round(time.time() - start_total, 3)
            }, severity="INFO")
            
            # Async BigQuery logging
            log_to_bigquery({
                "user_id": user_id,
                "thread_id": thread_id,
                "role": "assistant",
                "message": completion_message,
                "model": "ultra_fast_completion",
                "latency_sec": 0.05
            })
            
            return make_response(jsonify(
                response=completion_message,
                latency_retrieve=0,
                model="ultra_fast_completion",
                latency_sec=0.05,
                rag_corpus=CORPUS_RESOURCE,
                rag_snippets=[],
                latency_after_claude=0,
                rag_sources=[],
                should_complete_conversation=True,
                total_latency=round(time.time() - start_total, 3)
            ), 200)

        # Analyze conversation state
        conversation_stage = analyze_conversation_state(history, user_query)
        
        logger.log_struct({
            "event": "user_message",
            "user_id": user_id,
            "thread_id": thread_id,
            "message": user_query,
            "conversation_stage": conversation_stage,
            "role": "user"
        }, severity="INFO")

        # Async BigQuery logging for user message
        log_to_bigquery({
            "user_id": user_id,
            "thread_id": thread_id,
            "role": "user",
            "message": user_query,
            "model": None,
            "latency_sec": None
        })
        
        # Smart RAG retrieval
        start_rag = time.time()
        snippets, sources = smart_retrieve_from_rag(user_query, conversation_stage)
        context_str = "\n\n---\n".join(snippets)
        latency_retrieve = round(time.time() - start_rag, 3)
        
        # Get optimized system prompt with RAG context integrated
        start_prompt = time.time()
        system_prompt = get_system_prompt_for_request(history, user_query, context_str)
        system_prompt += f"\n\nCRITICAL DATE VALIDATION: Today's date is {datetime.now().strftime('%Y-%m-%d')}. MANDATORY REQUIREMENTS: 1) VERIFY every date from RAG context is after today before displaying, 2) Show EXACTLY TWO upcoming future start dates only, 3) Check conversation history to avoid repeating identical schedule information, 4) If RAG lacks future dates, request current information. NEVER guess or assume dates."
        latency_prompt = round(time.time() - start_prompt, 3)
        
        # Build optimized message history (no longer need RAG context in user message)
        base_prompt = f"User question: {user_query}"
        messages = build_optimized_history(history, base_prompt, conversation_stage)

        # Get optimized Claude parameters
        claude_params = get_optimized_claude_params(conversation_stage, len(user_query))
        
        # Call Claude with optimized parameters
        start_claude = time.time()
        resp = anthropic_client.messages.create(
            model=MODEL,
            system=system_prompt,
            messages=messages,
            **claude_params
        )
        latency_claude = round(time.time() - start_claude, 3)
        
        # Process response
        start_processing = time.time()
        answer_md = "\n\n".join(getattr(b, "text", "") for b in resp.content if getattr(b, "text", None))
        answer_text = md_to_plaintext(answer_md)
        latency_processing = round(time.time() - start_processing, 3)
        
        total_latency = round(time.time() - start_total, 3)
        
        # Enhanced logging with performance metrics
        logger.log_struct({
            "event": "assistant_reply",
            "user_id": user_id,
            "thread_id": thread_id,
            "message": answer_text,
            "role": "assistant",
            "model": MODEL,
            "conversation_stage": conversation_stage,
            "performance": {
                "total_latency": total_latency,
                "rag_latency": latency_retrieve,
                "prompt_latency": latency_prompt,
                "claude_latency": latency_claude,
                "processing_latency": latency_processing,
                "system_prompt_length": len(system_prompt),
                "message_count": len(messages),
                "rag_snippets": len(snippets)
            }
        }, severity="INFO")

        # Async BigQuery logging
        log_to_bigquery({
            "user_id": user_id,
            "thread_id": thread_id,
            "role": "assistant",
            "message": answer_text,
            "model": MODEL,
            "latency_sec": latency_claude
        })

        return make_response(jsonify(
            response=answer_text,
            latency_retrieve=latency_retrieve,
            model=MODEL,
            latency_sec=latency_claude,
            rag_corpus=CORPUS_RESOURCE,
            rag_snippets=snippets,
            latency_after_claude=latency_processing,
            rag_sources=sources,
            conversation_stage=conversation_stage,
            total_latency=total_latency,
            performance_metrics={
                "rag_latency": latency_retrieve,
                "prompt_latency": latency_prompt,
                "claude_latency": latency_claude,
                "processing_latency": latency_processing
            }
        ), 200)

    except Exception as e:
        total_latency = round(time.time() - start_total, 3)
        logger.log_struct({
            "event": "error",
            "error_type": type(e).__name__,
            "detail": str(e),
            "total_latency": total_latency
        }, severity="ERROR")
        return make_response(jsonify(
            error=type(e).__name(), 
            detail=str(e),
            total_latency=total_latency
        ), 500)