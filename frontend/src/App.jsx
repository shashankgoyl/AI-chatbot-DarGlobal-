import { useEffect, useRef, useState } from "react";
import { sendChatMessage } from "./api";

const INTRO = {
  role: "assistant",
  content:
    "Ask me about properties and projects listed publicly on DarGlobal or Wasalt — prices, locations, bedroom counts, or what's available in a given city. I only answer from what's in the current index, so if something's missing, say the word and it'll point you to the source site instead.",
};

const SUGGESTIONS = [
  "Villas for sale in Riyadh",
  "What DarGlobal projects are in Dubai?",
  "Apartments for sale in Jeddah under 2,000,000 SAR",
  "Tell me about Trump Tower Jeddah",
];

function SourceChip({ source }) {
  const label = source.source === "darglobal" ? "DarGlobal" : "Wasalt";
  return (
    <a
      className="source-chip"
      href={source.url || "#"}
      target="_blank"
      rel="noreferrer"
    >
      <span className={`source-chip__tag source-chip__tag--${source.source}`}>{label}</span>
      <span className="source-chip__title">{source.title || "Untitled listing"}</span>
      {source.price && <span className="source-chip__price">{source.price}</span>}
    </a>
  );
}

export default function App() {
  const [messages, setMessages] = useState([INTRO]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function handleSend(text) {
    const trimmed = (text ?? input).trim();
    if (!trimmed || loading) return;

    const nextMessages = [...messages, { role: "user", content: trimmed }];
    setMessages(nextMessages);
    setInput("");
    setError(null);
    setLoading(true);

    try {
      const { answer, sources } = await sendChatMessage(trimmed, nextMessages);
      setMessages((prev) => [...prev, { role: "assistant", content: answer, sources }]);
    } catch (err) {
      setError(err.message || "Something went wrong reaching the assistant.");
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(e) {
    e.preventDefault();
    handleSend();
  }

  const hasChatted = messages.length > 1;

  return (
    <div className="page">
      <header className="header">
        <div className="header__mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="28" height="28">
            <path
              d="M16 3 L29 13 V29 H3 V13 Z"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            />
            <path d="M12 29 V18 H20 V29" fill="none" stroke="currentColor" strokeWidth="2" />
          </svg>
        </div>
        <div>
          <p className="header__title">Estate Index</p>
          <p className="header__subtitle">AI answers over DarGlobal &amp; Wasalt public listings</p>
        </div>
      </header>

      <main className="chat">
        <div className="chat__scroll">
          <ul className="messages">
            {messages.map((m, i) => (
              <li key={i} className={`message message--${m.role}`}>
                <div className="message__bubble">
                  <p>{m.content}</p>
                  {m.sources && m.sources.filter((s) => s.url).length > 0 && (
                    <div className="message__sources">
                      {m.sources
                        .filter((s) => s.url)
                        .map((s, j) => (
                          <SourceChip key={j} source={s} />
                        ))}
                    </div>
                  )}
                </div>
              </li>
            ))}
            {loading && (
              <li className="message message--assistant">
                <div className="message__bubble message__bubble--loading">
                  <span className="dot" />
                  <span className="dot" />
                  <span className="dot" />
                </div>
              </li>
            )}
          </ul>

          {!hasChatted && (
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" onClick={() => handleSend(s)}>
                  {s}
                </button>
              ))}
            </div>
          )}

          {error && <p className="error-banner">{error}</p>}
          <div ref={bottomRef} />
        </div>

        <form className="composer" onSubmit={handleSubmit}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about a listing, city, or project…"
            aria-label="Message"
            disabled={loading}
          />
          <button type="submit" disabled={loading || !input.trim()}>
            Send
          </button>
        </form>
      </main>

      <footer className="footer">
        Answers are generated from scraped public listing data and may be incomplete or out of
        date — always confirm details directly with DarGlobal or Wasalt before making a decision.
      </footer>
    </div>
  );
}
