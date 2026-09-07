import { useEffect, useMemo, useRef, useState } from "react";
import { getFilterOptions, getHealth, getStats, streamChatMessage } from "./api";

const HISTORY_KEY = "estate-index-chat-history-v1";

function makeId() {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `id-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

const INTRO = {
  id: "intro",
  role: "assistant",
  time: new Date().toISOString(),
  content:
    "Ask me about properties and projects listed publicly on DarGlobal or Wasalt — prices, locations, bedroom counts, or what's available in a given city. I only answer from what's in the current index, so if something's missing, say the word and it'll point you to the source site instead.",
  sources: [],
};

const SUGGESTIONS = [
  { icon: "🏡", text: "Villas for sale in Riyadh" },
  { icon: "🏙️", text: "What DarGlobal projects are in Dubai?" },
  { icon: "🏢", text: "Apartments for sale in Jeddah under 2,000,000 SAR" },
  { icon: "🗼", text: "Tell me about Trump Tower Jeddah" },
];

const EMPTY_FILTERS = { source: "", location: "", beds: "", price_currency: "", price_min: "", price_max: "" };

// Real logos, hotlinked directly from each source's own site (found on their
// public homepages) rather than redrawn — this is a citation/attribution
// use (we link out to their listings throughout), not a recreation of their
// mark. Falls back to plain text if the image ever fails to load.
const BRAND_LOGOS = {
  darglobal: "https://cdn.darglobal.co.uk/globe_logo_a689bbb809.webp",
  wasalt: "https://cdn.wasalt.sa/images/wasalt-logo-ar.svg",
};

function BrandLogo({ source, className = "" }) {
  const [failed, setFailed] = useState(false);
  const src = BRAND_LOGOS[source];
  if (!src || failed) return null;
  return (
    <img
      src={src}
      alt={source === "darglobal" ? "DarGlobal" : "Wasalt"}
      className={`brand-logo ${className}`}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}

function loadStoredMessages() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [INTRO];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) return [INTRO];
    // Backfill ids for history saved before messages carried a stable id.
    return parsed.map((m) => (m.id ? m : { ...m, id: makeId() }));
  } catch {
    return [INTRO];
  }
}

function formatTime(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  const isToday = new Date().toDateString() === date.toDateString();
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return isToday ? `Today, ${time}` : `${date.toLocaleDateString()}, ${time}`;
}

// Small markdown-lite renderer: blank-line paragraphs, "- " bullet lists,
// and **bold** — enough for the plain-text answers the backend returns,
// without pulling in a full markdown dependency.
function renderContent(text) {
  const blocks = String(text || "").trim().split(/\n{2,}/);
  return blocks.map((block, i) => {
    const lines = block.split("\n").map((l) => l.trim()).filter(Boolean);
    const isList = lines.length > 0 && lines.every((l) => /^[-*]\s+/.test(l));
    const withBold = (line) =>
      line.split(/(\*\*[^*]+\*\*)/g).map((part, j) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={j}>{part.slice(2, -2)}</strong>
        ) : (
          part
        )
      );

    if (isList) {
      return (
        <ul key={i} className="message__list">
          {lines.map((l, j) => (
            <li key={j}>{withBold(l.replace(/^[-*]\s+/, ""))}</li>
          ))}
        </ul>
      );
    }
    return <p key={i}>{withBold(block)}</p>;
  });
}

function sourceBadge(sources) {
  if (!sources || sources.length === 0) return { label: "Concierge", kind: "default" };
  const kinds = new Set(sources.map((s) => s.source));
  if (kinds.size > 1) return { label: "Multi-Source", kind: "default" };
  const only = [...kinds][0];
  if (only === "darglobal") return { label: "DarGlobal", kind: "darglobal" };
  if (only === "wasalt") return { label: "Wasalt", kind: "wasalt" };
  return { label: "Concierge", kind: "default" };
}

function badgeKindToSource(kind) {
  return kind === "darglobal" || kind === "wasalt" ? kind : null;
}

function SourceCard({ source }) {
  const label = source.source === "darglobal" ? "DarGlobal" : "Wasalt";
  return (
    <a
      className={`source-card source-card--${source.source || "other"}`}
      href={source.url || "#"}
      target="_blank"
      rel="noreferrer"
    >
      <span className="source-card__badge">
        <BrandLogo source={source.source} />
        {label}
      </span>
      <span className="source-card__title">{source.title || "Untitled listing"}</span>
      {source.location && <span className="source-card__location">📍 {source.location}</span>}
      {source.beds && <span className="source-card__location">🛏 {source.beds}</span>}
      <span className="source-card__foot">
        {source.price ? <span className="source-card__price">{source.price}</span> : <span />}
        <span className="source-card__link">View source ↗</span>
      </span>
    </a>
  );
}

function StatCard({ label, value, hint }) {
  return (
    <div className="stat-card">
      <p className="stat-card__label">{label}</p>
      <p className="stat-card__value">
        {value === null || value === undefined ? (
          <span className="stat-card__value--loading" aria-label="Loading" />
        ) : (
          value
        )}
      </p>
      {hint && <p className="stat-card__hint">{hint}</p>}
    </div>
  );
}

export default function App() {
  const [messages, setMessages] = useState(loadStoredMessages);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [stats, setStats] = useState(null);
  const [health, setHealth] = useState("checking");
  const [lastLatencyMs, setLastLatencyMs] = useState(null);
  const [showBookmarkedOnly, setShowBookmarkedOnly] = useState(false);
  const [copiedId, setCopiedId] = useState(null);
  const [engineOpen, setEngineOpen] = useState(false);
  const [filterOptions, setFilterOptions] = useState(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const bottomRef = useRef(null);
  const abortRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    getStats().then(setStats).catch(() => setStats(null));
    getHealth()
      .then(() => setHealth("connected"))
      .catch(() => setHealth("offline"));
    getFilterOptions().then(setFilterOptions).catch(() => setFilterOptions(null));
  }, []);

  // Persist the conversation across reloads. Storage can legitimately be
  // unavailable (private browsing, cleared site data) — fail silently and
  // the app just falls back to an in-memory conversation for that session.
  useEffect(() => {
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(messages));
    } catch {
      // ignore — nothing we can do about it, and it shouldn't break the chat
    }
  }, [messages]);

  const activeFilterCount = useMemo(
    () => Object.values(filters).filter((v) => v !== "" && v !== null && v !== undefined).length,
    [filters]
  );

  function updateFilter(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  function clearFilters() {
    setFilters(EMPTY_FILTERS);
  }

  async function handleSend(text) {
    const trimmed = (text ?? input).trim();
    if (!trimmed || loading) return;

    const historyForRequest = messages;
    const userMsg = { id: makeId(), role: "user", content: trimmed, time: new Date().toISOString() };
    const assistantMsg = {
      id: makeId(),
      role: "assistant",
      content: "",
      sources: [],
      time: new Date().toISOString(),
      provider: null,
      streaming: true,
    };

    setMessages([...historyForRequest, userMsg, assistantMsg]);
    setInput("");
    setError(null);
    setLoading(true);
    const startedAt = performance.now();

    const patchLastMessage = (patch) => {
      setMessages((prev) => {
        const copy = [...prev];
        const lastIndex = copy.length - 1;
        copy[lastIndex] =
          typeof patch === "function" ? patch(copy[lastIndex]) : { ...copy[lastIndex], ...patch };
        return copy;
      });
    };

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamChatMessage(trimmed, historyForRequest, filters, {
        signal: controller.signal,
        onSources: (sources) => patchLastMessage({ sources }),
        onToken: (chunk) => patchLastMessage((m) => ({ ...m, content: m.content + chunk })),
        onDone: (provider) => {
          setLastLatencyMs(Math.round(performance.now() - startedAt));
          setHealth("connected");
          patchLastMessage({ provider, streaming: false });
        },
        onError: (message) => {
          setHealth("offline");
          setError(message);
          patchLastMessage({ streaming: false });
        },
      });
    } catch (err) {
      setHealth("offline");
      setError(err.message || "Something went wrong reaching the assistant.");
      patchLastMessage({ streaming: false });
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  }

  function handleSubmit(e) {
    e.preventDefault();
    handleSend();
  }

  function toggleBookmark(i) {
    setMessages((prev) => {
      const copy = [...prev];
      copy[i] = { ...copy[i], bookmarked: !copy[i].bookmarked };
      return copy;
    });
  }

  async function copyMessage(id, content) {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedId(id);
      setTimeout(() => setCopiedId((cur) => (cur === id ? null : cur)), 1500);
    } catch {
      // clipboard not available — silently ignore, nothing to fall back to
    }
  }

  function clearConversation() {
    abortRef.current?.abort();
    setMessages([INTRO]);
    setError(null);
    try {
      localStorage.removeItem(HISTORY_KEY);
    } catch {
      // ignore
    }
  }

  const hasChatted = messages.length > 1;
  const bookmarkedCount = messages.filter((m) => m.bookmarked).length;

  const statusLabel = useMemo(() => {
    const modelLabel = stats?.model ? stats.model.split("/").pop() : "model not set";
    const parts = [`OpenRouter Pipeline`, modelLabel];
    if (stats?.gemini_configured) parts.push("Gemini fallback ready");
    if (lastLatencyMs != null) parts.push(`${lastLatencyMs}ms last reply`);
    return parts.join(" • ");
  }, [stats, lastLatencyMs]);

  return (
    <div className="page">
      <header className="navbar">
        <div className="navbar__brand">
          <div className="navbar__mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="22" height="22">
              <path d="M16 3 L29 13 V29 H3 V13 Z" fill="none" stroke="currentColor" strokeWidth="2" />
              <path d="M12 29 V18 H20 V29" fill="none" stroke="currentColor" strokeWidth="2" />
            </svg>
          </div>
          <div>
            <p className="navbar__title">
              Estate Index <span className="navbar__title-tag">INTELLIGENCE PLATFORM</span>
            </p>
            <p className="navbar__subtitle">AI answers over DarGlobal &amp; Wasalt public listings</p>
          </div>
        </div>

        <div className="navbar__mode">
          <span className="navbar__mode-dot" aria-hidden="true" />
          Intelligence Chat
        </div>

        <div className="navbar__actions">
          <button
            type="button"
            className={`navbar__connect ${health === "connected" ? "navbar__connect--connected" : ""} ${
              health === "offline" ? "navbar__connect--offline" : ""
            }`}
            onClick={() => getHealth().then(() => setHealth("connected")).catch(() => setHealth("offline"))}
            title="Check backend connection"
          >
            <span className={`navbar__dot navbar__dot--${health}`} />
            {health === "connected" ? "Connected" : health === "offline" ? "Offline" : "Checking…"}
          </button>
        </div>
      </header>

      <div className="status-bar">
        <span className="status-bar__left">
          <span className={`status-bar__dot status-bar__dot--${health}`} />
          {statusLabel}
        </span>
        <div className="status-bar__right">
          <button type="button" onClick={() => setEngineOpen((v) => !v)}>
            ⚙ Engine Settings
          </button>
          {engineOpen && (
            <div className="engine-popover">
              <p>
                <strong>Primary model</strong> {stats?.model || "—"}
              </p>
              <p>
                <strong>Fallback model</strong>{" "}
                {stats?.gemini_configured ? stats?.fallback_model : "not configured"}
              </p>
              <p>
                <strong>Vector index</strong> {stats?.vectorstore_ready ? "built" : "not built yet"}
              </p>
              <p>
                <strong>Indexed docs</strong> {stats?.total_indexed ?? "—"}
              </p>
            </div>
          )}
        </div>
      </div>

      <main className="hero">
        <p className="hero__eyebrow">PRIVATE REAL ESTATE INTELLIGENCE • Live Intelligence Index</p>
        <div className="hero__row">
          <div className="hero__intro">
            <h1>Estate Index Concierge</h1>
            <p>
              Ask freely about publicly listed DarGlobal and Wasalt developments — locations,
              unit types, and prices as scraped from their public listing pages. Answers are
              grounded only in what's currently indexed, generated by OpenRouter with an
              automatic Gemini fallback if it's unavailable.
            </p>
          </div>
          <div className="hero__stats">
            <StatCard
              label={<><BrandLogo source="darglobal" /> DarGlobal Sources</>}
              value={stats ? stats.darglobal_count : null}
              hint="pages indexed"
            />
            <StatCard
              label={<><BrandLogo source="wasalt" /> Wasalt Sources</>}
              value={stats ? stats.wasalt_count : null}
              hint="pages indexed"
            />
            <StatCard
              label="Total Indexed"
              value={stats ? stats.total_indexed : null}
              hint={stats?.vectorstore_ready ? "index ready" : "index building"}
            />
          </div>
        </div>

        <div className="hero__suggestions-row">
          <span className="hero__suggestions-label">CURATED INQUIRIES</span>
          <div className="suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s.text} type="button" onClick={() => handleSend(s.text)}>
                <span className="suggestions__icon" aria-hidden="true">{s.icon}</span>
                {s.text}
              </button>
            ))}
          </div>
        </div>
      </main>

      <section className="filters-bar">
        <button type="button" className="filters-toggle" onClick={() => setFiltersOpen((v) => !v)}>
          🔧 Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
        </button>

        {activeFilterCount > 0 && (
          <div className="active-filters">
            {Object.entries(filters)
              .filter(([, v]) => v !== "" && v !== null && v !== undefined)
              .map(([key, value]) => (
                <span key={key} className="active-filter-chip">
                  {value}
                  <button type="button" onClick={() => updateFilter(key, "")} aria-label={`Remove ${key} filter`}>
                    ✕
                  </button>
                </span>
              ))}
            <button type="button" className="active-filters__clear" onClick={clearFilters}>
              Clear all
            </button>
          </div>
        )}

        {filtersOpen && (
          <div className="filters-panel">
            <label>
              Source
              <select value={filters.source} onChange={(e) => updateFilter("source", e.target.value)}>
                <option value="">Any</option>
                {(filterOptions?.sources || []).map((s) => (
                  <option key={s} value={s}>
                    {s === "darglobal" ? "DarGlobal" : "Wasalt"}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Location
              <select value={filters.location} onChange={(e) => updateFilter("location", e.target.value)}>
                <option value="">Any</option>
                {(filterOptions?.locations || []).map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
              {filterOptions && filterOptions.locations.length === 0 && (
                <span className="filters-panel__hint">no location data indexed yet</span>
              )}
            </label>

            <label>
              Beds
              <select value={filters.beds} onChange={(e) => updateFilter("beds", e.target.value)}>
                <option value="">Any</option>
                {(filterOptions?.beds || []).map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Currency
              <select
                value={filters.price_currency}
                onChange={(e) => updateFilter("price_currency", e.target.value)}
              >
                <option value="">Any</option>
                {(filterOptions?.currencies || []).map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Min price
              <input
                type="number"
                inputMode="numeric"
                placeholder="e.g. 500000"
                value={filters.price_min}
                onChange={(e) => updateFilter("price_min", e.target.value)}
              />
            </label>

            <label>
              Max price
              <input
                type="number"
                inputMode="numeric"
                placeholder="e.g. 5000000"
                value={filters.price_max}
                onChange={(e) => updateFilter("price_max", e.target.value)}
              />
            </label>
          </div>
        )}
      </section>

      <section className="chat">
        <div className="chat__top-actions">
          {bookmarkedCount > 0 && (
            <button
              type="button"
              className={`chat__bookmark-filter ${showBookmarkedOnly ? "is-active" : ""}`}
              onClick={() => setShowBookmarkedOnly((v) => !v)}
            >
              {showBookmarkedOnly ? "★" : "☆"} Bookmarked ({bookmarkedCount})
            </button>
          )}
          {hasChatted && (
            <button type="button" className="chat__clear" onClick={clearConversation}>
              Clear conversation
            </button>
          )}
        </div>

        <ul className="messages">
          {(showBookmarkedOnly ? messages.filter((m) => m.bookmarked) : messages).map((m) => (
            <li key={m.id} className={`message message--${m.role}`}>
              {m.role === "user" ? (
                <>
                  <p className="message__meta message__meta--user">You • {formatTime(m.time)}</p>
                  <div className="message__bubble">
                    <p>{m.content}</p>
                  </div>
                </>
              ) : (
                <div className="message__card">
                  <div className="message__card-head">
                    <div className="message__card-id">
                      <span className="message__card-mark" aria-hidden="true">✦</span>
                      <span className="message__card-name">Estate Index Concierge</span>
                      <span
                        className={`message__card-badge ${
                          sourceBadge(m.sources).kind === "wasalt" ? "message__card-badge--wasalt" : ""
                        }`}
                      >
                        <BrandLogo source={badgeKindToSource(sourceBadge(m.sources).kind)} />
                        {sourceBadge(m.sources).label} • Live Index
                      </span>
                      {m.provider === "gemini" && (
                        <span className="message__card-badge message__card-badge--fallback">via Gemini fallback</span>
                      )}
                    </div>
                    <div className="message__card-tools">
                      <button
                        type="button"
                        title="Bookmark"
                        aria-pressed={!!m.bookmarked}
                        onClick={() => toggleBookmark(messages.findIndex((x) => x.id === m.id))}
                        className={m.bookmarked ? "is-active" : ""}
                      >
                        {m.bookmarked ? "★" : "☆"}
                      </button>
                      <button type="button" title="Copy answer" onClick={() => copyMessage(m.id, m.content)}>
                        {copiedId === m.id ? "✓" : "⧉"}
                      </button>
                    </div>
                  </div>

                  {m.content ? (
                    <div className="message__body">{renderContent(m.content)}</div>
                  ) : m.streaming ? (
                    <div className="message__body message__body--loading">
                      <span className="dot" />
                      <span className="dot" />
                      <span className="dot" />
                    </div>
                  ) : null}

                  {m.streaming && m.content && <span className="message__cursor" aria-hidden="true" />}

                  {m.sources && m.sources.filter((s) => s.url).length > 0 && (
                    <div className="message__sources">
                      {m.sources
                        .filter((s) => s.url)
                        .map((s, j) => (
                          <SourceCard key={j} source={s} />
                        ))}
                    </div>
                  )}

                  <p className="message__meta">{formatTime(m.time)}</p>
                </div>
              )}
            </li>
          ))}
        </ul>

        {error && <p className="error-banner">{error}</p>}
        <div ref={bottomRef} />
      </section>

      <form className="composer" onSubmit={handleSubmit}>
        <span className="composer__icon" aria-hidden="true">🔎</span>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about a listing, city, or unit layout…"
          aria-label="Message"
          disabled={loading}
        />
        <button type="submit" disabled={loading || !input.trim()}>
          Inquire ↑
        </button>
      </form>
      <p className="composer__hint">
        Synthesized from {stats?.total_indexed ?? "…"} public listing pages from DarGlobal &amp;
        Wasalt. Confirm official terms with the developer directly. Press Enter ↵ to send.
      </p>

      <footer className="footer">
        <div>
          <p className="footer__brand">Estate Index <span>PRIVATE AI CONCIERGE</span></p>
          <p>Synthesized real estate intelligence indexing public listing pages.</p>
        </div>
        <div className="footer__right">
          <p>
            DATA FEEDS:
            <span className="footer__logos">
              <BrandLogo source="darglobal" /> · <BrandLogo source="wasalt" />
            </span>
          </p>
          <p>© {new Date().getFullYear()} Estate Index. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}
