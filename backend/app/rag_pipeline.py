"""
Conversational RAG graph built with LangGraph, with automatic provider
fallback (OpenRouter -> Gemini) and optional structured filtering over the
retrieved listings' metadata (source / location / beds / price range).

Graph shape (used for the non-streaming path):

    retrieve -> generate -> END

`retrieve` pulls the top-k relevant chunks from the FAISS store built by
ingest_pipeline.py, applying any structured filters over a wider candidate
pool first so filtering doesn't just starve the answer of context.
`generate` calls whichever chat model is currently available — OpenRouter
first, Gemini as an automatic fallback if OpenRouter is unset, rate
limited, or errors — with the retrieved context plus prior turns (sent by
the frontend on every request, so the graph itself stays stateless).

`stream_answer` mirrors the same retrieve+generate logic but yields
incremental events for the SSE endpoint instead of building the graph.
"""
from __future__ import annotations

from typing import Iterator, Optional, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from . import config
from .filters import matches_filters
from .ingest_pipeline import load_or_build_vectorstore

SYSTEM_PROMPT = """You are the AI assistant for a real-estate research tool that indexes \
publicly listed properties and projects from two sources: DarGlobal (international luxury \
branded residences) and Wasalt (a Saudi Arabian property portal covering villas, apartments, \
buildings and land).

Rules:
- Answer ONLY using the CONTEXT provided below plus the conversation so far. \
If the context doesn't contain the answer, say you don't have that listing in your \
current data and suggest the user rephrase, clear any active filters, or check the \
source site directly.
- Always mention which source (DarGlobal or Wasalt) a property comes from when relevant.
- Never invent prices, locations, or availability that aren't in the context.
- You are not a licensed real-estate agent or financial advisor; for anything transactional \
(booking, payment, legal, visa/ownership eligibility) tell the user to confirm directly with \
DarGlobal or Wasalt.
- Be concise and use bullet points for multiple listings.
"""

# When structured filters are active, pull a wider candidate pool from the
# vector store before filtering down to RETRIEVER_K — otherwise a filter
# would just discard most of a small top-k and starve the answer of context.
FILTER_CANDIDATE_MULTIPLIER = 6

PROVIDERS = ("openrouter", "gemini")


class ChatState(TypedDict):
    question: str
    chat_history: list[dict]
    filters: dict
    context: str
    sources: list[dict]
    answer: str
    provider: str


_vectorstore = None
_openrouter_llm = None
_gemini_llm = None


def get_vectorstore():
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = load_or_build_vectorstore()
    return _vectorstore


def reset_vectorstore_cache():
    global _vectorstore
    _vectorstore = None


def get_openrouter_llm():
    global _openrouter_llm
    if _openrouter_llm is None:
        if not config.OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY is not set.")
        from langchain_openai import ChatOpenAI

        _openrouter_llm = ChatOpenAI(
            model=config.OPENROUTER_MODEL,
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
            temperature=0.2,
            default_headers={
                "HTTP-Referer": config.OPENROUTER_SITE_URL,
                "X-Title": config.OPENROUTER_APP_NAME,
            },
        )
    return _openrouter_llm


def get_gemini_llm():
    global _gemini_llm
    if _gemini_llm is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        from langchain_google_genai import ChatGoogleGenerativeAI

        _gemini_llm = ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL,
            api_key=config.GEMINI_API_KEY,
            temperature=0.2,
        )
    return _gemini_llm


_LLM_GETTERS = {"openrouter": get_openrouter_llm, "gemini": get_gemini_llm}


def reset_llm_cache():
    """Used after an admin re-ingest / config change so a bad key isn't stuck cached."""
    global _openrouter_llm, _gemini_llm
    _openrouter_llm = None
    _gemini_llm = None


def _build_messages(question: str, context: str, chat_history: list[dict] | None) -> list[BaseMessage]:
    messages: list[BaseMessage] = [SystemMessage(content=SYSTEM_PROMPT)]
    for turn in (chat_history or [])[-8:]:  # keep the prompt small
        if turn.get("role") == "user":
            messages.append(HumanMessage(content=turn.get("content", "")))
        elif turn.get("role") == "assistant":
            messages.append(AIMessage(content=turn.get("content", "")))
    messages.append(HumanMessage(content=f"CONTEXT:\n{context}\n\nQUESTION: {question}"))
    return messages


def _retrieve(question: str, filters: Optional[dict]) -> tuple[str, list[dict]]:
    vectorstore = get_vectorstore()
    k = config.RETRIEVER_K
    pool_size = k * FILTER_CANDIDATE_MULTIPLIER if filters else k
    results = vectorstore.similarity_search(question, k=pool_size)

    context_parts = []
    sources = []
    for doc in results:
        meta = doc.metadata or {}
        if not matches_filters(meta, filters):
            continue
        context_parts.append(
            f"[{meta.get('source', 'unknown')}] {meta.get('title', '')}\n{doc.page_content}"
        )
        sources.append(
            {
                "title": meta.get("title"),
                "url": meta.get("url"),
                "source": meta.get("source"),
                "price": meta.get("price"),
                "location": meta.get("location"),
                "beds": meta.get("beds"),
            }
        )
        if len(sources) >= k:
            break

    if not context_parts:
        note = (
            "(no listings in the current index match those filters — tell the user to "
            "widen or clear them)"
            if filters
            else "(no matching listings found)"
        )
        return note, []

    return "\n\n---\n\n".join(context_parts), sources


def _invoke_with_fallback(messages: list[BaseMessage]) -> tuple[str, str]:
    errors = []
    for name in PROVIDERS:
        try:
            llm = _LLM_GETTERS[name]()
            response = llm.invoke(messages)
            return response.content, name
        except Exception as exc:  # noqa: BLE001 - any provider failure should try the next one
            errors.append(f"{name}: {exc}")

    raise RuntimeError(
        "No AI provider is currently available (" + "; ".join(errors) + "). "
        "Set OPENROUTER_API_KEY and/or GEMINI_API_KEY in your .env."
    )


def _stream_with_fallback(messages: list[BaseMessage]) -> Iterator[tuple[str, str]]:
    """Yields (chunk_text, provider) tuples.

    Falls back to the next provider only if nothing has been streamed yet
    (missing key, or the connection fails before the first token). Once a
    provider has actually started streaming tokens to the client, a later
    failure is raised instead of silently switching mid-answer.
    """
    errors = []
    for name in PROVIDERS:
        try:
            llm = _LLM_GETTERS[name]()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            continue

        yielded_any = False
        try:
            for chunk in llm.stream(messages):
                if chunk.content:
                    yielded_any = True
                    yield chunk.content, name
            return
        except Exception as exc:  # noqa: BLE001
            if yielded_any:
                raise RuntimeError(f"{name} stream was interrupted: {exc}") from exc
            errors.append(f"{name}: {exc}")
            continue

    raise RuntimeError(
        "No AI provider is currently available (" + "; ".join(errors) + "). "
        "Set OPENROUTER_API_KEY and/or GEMINI_API_KEY in your .env."
    )


def _retrieve_node(state: ChatState) -> ChatState:
    context, sources = _retrieve(state["question"], state.get("filters"))
    state["context"] = context
    state["sources"] = sources
    return state


def _generate_node(state: ChatState) -> ChatState:
    messages = _build_messages(state["question"], state["context"], state.get("chat_history"))
    content, provider = _invoke_with_fallback(messages)
    state["answer"] = content
    state["provider"] = provider
    return state


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        builder = StateGraph(ChatState)
        builder.add_node("retrieve", _retrieve_node)
        builder.add_node("generate", _generate_node)
        builder.set_entry_point("retrieve")
        builder.add_edge("retrieve", "generate")
        builder.add_edge("generate", END)
        _graph = builder.compile()
    return _graph


def answer_question(
    question: str,
    chat_history: list[dict] | None = None,
    filters: dict | None = None,
) -> dict:
    graph = get_graph()
    result = graph.invoke(
        {
            "question": question,
            "chat_history": chat_history or [],
            "filters": filters or {},
            "context": "",
            "sources": [],
            "answer": "",
            "provider": "",
        }
    )
    return {"answer": result["answer"], "sources": result["sources"], "provider": result["provider"]}


def stream_answer(
    question: str,
    chat_history: list[dict] | None = None,
    filters: dict | None = None,
) -> Iterator[dict]:
    """Generator of event dicts for the SSE endpoint.

    Event shapes: {"type": "sources", "sources": [...]}, then any number of
    {"type": "token", "text": "..."}, then either {"type": "done",
    "provider": "..."} or {"type": "error", "message": "..."}.
    """
    context, sources = _retrieve(question, filters)
    yield {"type": "sources", "sources": sources}

    messages = _build_messages(question, context, chat_history)
    try:
        provider_used = None
        for chunk_text, provider in _stream_with_fallback(messages):
            provider_used = provider
            yield {"type": "token", "text": chunk_text}
        yield {"type": "done", "provider": provider_used or "unknown"}
    except Exception as exc:  # noqa: BLE001 - surfaced to the client as an SSE error event
        yield {"type": "error", "message": str(exc)}
