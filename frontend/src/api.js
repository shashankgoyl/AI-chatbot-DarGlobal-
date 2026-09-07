const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const NUMERIC_FILTER_KEYS = new Set(["price_min", "price_max"]);

function toFilterPayload(filters) {
  const out = {};
  if (!filters) return out;
  for (const [key, value] of Object.entries(filters)) {
    if (value === "" || value === null || value === undefined) continue;
    if (NUMERIC_FILTER_KEYS.has(key)) {
      const num = Number(value);
      if (!Number.isNaN(num)) out[key] = num;
      continue;
    }
    out[key] = value;
  }
  return out;
}

export async function sendChatMessage(message, history, filters) {
  const res = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      history: history.map(({ role, content }) => ({ role, content })),
      filters: toFilterPayload(filters),
    }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }

  return res.json(); // { answer, sources, provider }
}

// Streams a reply from POST /api/chat/stream as Server-Sent Events. Uses a
// plain fetch + ReadableStream reader rather than the EventSource API,
// since EventSource can only do GET and this needs a JSON body (message +
// history + filters).
export async function streamChatMessage(message, history, filters, handlers = {}) {
  const { onSources, onToken, onDone, onError, signal } = handlers;

  const res = await fetch(`${API_URL}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      history: history.map(({ role, content }) => ({ role, content })),
      filters: toFilterPayload(filters),
    }),
    signal,
  });

  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handleEvent = (rawEvent) => {
    const dataLine = rawEvent.split("\n").find((l) => l.startsWith("data: "));
    if (!dataLine) return;
    let payload;
    try {
      payload = JSON.parse(dataLine.slice(6));
    } catch {
      return;
    }
    if (payload.type === "sources") onSources?.(payload.sources || []);
    else if (payload.type === "token") onToken?.(payload.text || "");
    else if (payload.type === "done") onDone?.(payload.provider);
    else if (payload.type === "error") onError?.(payload.message || "Stream error");
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sepIndex;
    while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, sepIndex);
      buffer = buffer.slice(sepIndex + 2);
      handleEvent(rawEvent);
    }
  }
}

// Real counts from the last scrape + the configured models — used to drive
// the hero stat cards and status bar instead of hardcoding numbers.
export async function getStats() {
  const res = await fetch(`${API_URL}/api/stats`);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json(); // { darglobal_count, wasalt_count, total_indexed, vectorstore_ready, model, fallback_model, gemini_configured }
}

export async function getHealth() {
  const res = await fetch(`${API_URL}/api/health`);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json(); // { status }
}

// Distinct source/location/beds/currency values actually present in the
// current index — drives the filter picker so it never offers a choice
// that would silently return nothing.
export async function getFilterOptions() {
  const res = await fetch(`${API_URL}/api/filters`);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json(); // { sources, locations, beds, currencies }
}
