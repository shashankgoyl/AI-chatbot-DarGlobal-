"""
Conversational RAG graph built with LangGraph.

Graph shape:

    retrieve -> generate -> END

`retrieve` pulls the top-k relevant chunks from the FAISS store built by
ingest_pipeline.py. `generate` calls a free OpenRouter chat model with the
retrieved context plus prior turns (sent by the frontend on every request,
so the graph itself stays stateless — friendly to a free-tier host that
may spin instances up/down).
"""
from __future__ import annotations

from typing import TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from . import config
from .ingest_pipeline import load_or_build_vectorstore

SYSTEM_PROMPT = """You are the AI assistant for a real-estate research tool that indexes \
publicly listed properties and projects from two sources: DarGlobal (international luxury \
branded residences) and Wasalt (a Saudi Arabian property portal covering villas, apartments, \
buildings and land).

Rules:
- Answer ONLY using the CONTEXT provided below plus the conversation so far. \
If the context doesn't contain the answer, say you don't have that listing in your \
current data and suggest the user rephrase or check the source site directly.
- Always mention which source (DarGlobal or Wasalt) a property comes from when relevant.
- Never invent prices, locations, or availability that aren't in the context.
- You are not a licensed real-estate agent or financial advisor; for anything transactional \
(booking, payment, legal, visa/ownership eligibility) tell the user to confirm directly with \
DarGlobal or Wasalt.
- Be concise and use bullet points for multiple listings.
"""


class ChatState(TypedDict):
    question: str
    chat_history: list[dict]  # [{"role": "user"|"assistant", "content": str}, ...]
    context: str
    sources: list[dict]
    answer: str


_vectorstore = None
_llm = None


def get_vectorstore():
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = load_or_build_vectorstore()
    return _vectorstore


def reset_vectorstore_cache():
    global _vectorstore
    _vectorstore = None


def get_llm():
    global _llm
    if _llm is None:
        from langchain_openai import ChatOpenAI

        if not config.OPENROUTER_API_KEY:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Get a free key at https://openrouter.ai/keys "
                "and put it in your .env / Render environment variables."
            )

        _llm = ChatOpenAI(
            model=config.OPENROUTER_MODEL,
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
            temperature=0.2,
            default_headers={
                "HTTP-Referer": config.OPENROUTER_SITE_URL,
                "X-Title": config.OPENROUTER_APP_NAME,
            },
        )
    return _llm


def _retrieve_node(state: ChatState) -> ChatState:
    vectorstore = get_vectorstore()
    results = vectorstore.similarity_search(state["question"], k=config.RETRIEVER_K)

    context_parts = []
    sources = []
    for doc in results:
        meta = doc.metadata or {}
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
            }
        )

    state["context"] = "\n\n---\n\n".join(context_parts) if context_parts else "(no matching listings found)"
    state["sources"] = sources
    return state


def _generate_node(state: ChatState) -> ChatState:
    llm = get_llm()

    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    for turn in state.get("chat_history", [])[-8:]:  # keep the prompt small
        if turn.get("role") == "user":
            messages.append(HumanMessage(content=turn.get("content", "")))
        elif turn.get("role") == "assistant":
            messages.append(AIMessage(content=turn.get("content", "")))

    messages.append(
        HumanMessage(
            content=f"CONTEXT:\n{state['context']}\n\nQUESTION: {state['question']}"
        )
    )

    response = llm.invoke(messages)
    state["answer"] = response.content
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


def answer_question(question: str, chat_history: list[dict] | None = None) -> dict:
    graph = get_graph()
    result = graph.invoke(
        {
            "question": question,
            "chat_history": chat_history or [],
            "context": "",
            "sources": [],
            "answer": "",
        }
    )
    return {"answer": result["answer"], "sources": result["sources"]}
