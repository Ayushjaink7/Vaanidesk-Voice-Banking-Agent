import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import {
  ACTION_LABELS, AWAITING_LABELS, DEMO_TPINS, INTENT_LABELS, LANGUAGE_LABELS,
  SOURCE_IN_SENTENCE, TRY_SAYING, maskPhone,
} from "./labels.js";

const hasDevanagari = (text) => /[ऀ-ॿ]/.test(text);

// Read the agent's reply aloud with the browser's built-in voices (Indian English / Hindi when available).
function speak(text, language) {
  if (!("speechSynthesis" in window)) return;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = language === "en" ? "en-IN" : "hi-IN";
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

export default function CallConsole() {
  const [customers, setCustomers] = useState([]);
  const [phone, setPhone] = useState("");
  const [call, setCall] = useState(null);          // { id, name }
  const [turns, setTurns] = useState([]);
  const [state, setState] = useState({ awaiting: null, language: "en", verified: false });
  const [ended, setEnded] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [voiceLang, setVoiceLang] = useState("auto");
  const [recording, setRecording] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(false);
  const recorderRef = useRef(null);
  const endRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    api.demoCustomers()
      .then((list) => { setCustomers(list); if (list.length) setPhone(list[0].phone); })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => { endRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [turns]);

  const firstName = call?.name.split(" ")[0] ?? "Customer";

  async function startCall() {
    setError(""); setBusy(true);
    try {
      const res = await api.startCall(phone);
      setCall({ id: res.call_id, name: res.customer_name });
      setTurns([{ role: "agent", text: res.reply }]);
      setState({ awaiting: null, language: res.language, verified: false });
      if (speakReplies) speak(res.reply, res.language);
      setEnded(false);
      setTimeout(() => inputRef.current?.focus(), 0);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function applyTurn(res) {
    setTurns((prev) => [
      ...prev,
      { role: "customer", text: res.transcript, note: { kind: "heard", ...res } },
      { role: "agent", text: res.reply, note: { kind: "did", ...res } },
    ]);
    setState({ awaiting: res.awaiting, language: res.language, verified: res.verified });
    if (speakReplies) speak(res.reply, res.language);
    if (res.call_ended) setEnded(true);
  }

  async function send(message) {
    const clean = message.trim();
    if (!clean || !call || ended || busy) return;
    setError(""); setBusy(true);
    try {
      applyTurn(await api.say(call.id, clean));
      setText("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleRecording() {
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    setError("");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("This browser can't record audio. Type your message instead.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      const chunks = [];
      recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        setBusy(true);
        try {
          applyTurn(await api.sendAudio(call.id, new Blob(chunks, { type: recorder.mimeType }), voiceLang));
        } catch (e) {
          setError(e.message);
        } finally {
          setBusy(false);
        }
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch {
      setError("Microphone access was blocked. Allow it in the browser, or type your message.");
    }
  }

  async function endCall() {
    if (!call || ended) return;
    setBusy(true);
    try {
      await api.endCall(call.id);
      setEnded(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const selected = customers.find((c) => c.phone === phone);

  return (
    <div className="console">
      <section className="caller" aria-label="Caller">
        <label className="field">
          <span>Call as</span>
          <select value={phone} onChange={(e) => setPhone(e.target.value)} disabled={!!call && !ended}>
            {customers.map((c) => (
              <option key={c.phone} value={c.phone}>{c.name} ({maskPhone(c.phone)})</option>
            ))}
          </select>
        </label>
        {selected && <p className="hint">Demo TPIN for {selected.name.split(" ")[0]}: {DEMO_TPINS[selected.phone]}</p>}
        <button className="primary" onClick={startCall} disabled={busy || !phone || (!!call && !ended)}>
          {call && ended ? "Start a new call" : "Start call"}
        </button>
      </section>

      {error && <p className="error" role="alert">{error}</p>}

      {!call ? (
        <section className="empty">
          <h2>Start a call to talk to the agent</h2>
          <p>
            Pick a demo customer and start a call. Then speak or type in English, Hindi or Hinglish.
            The right column shows what the agent understood from each turn and what it did at the bank.
          </p>
        </section>
      ) : (
        <section className="call" aria-label={`Call with ${call.name}`}>
          <div className="call-head">
            <h2>Call with {call.name}</h2>
            <dl className="call-state">
              <div><dt>Language</dt><dd>{LANGUAGE_LABELS[state.language]}</dd></div>
              <div><dt>Identity</dt><dd>{state.verified ? "Verified" : "Not verified"}</dd></div>
              <div><dt>Waiting for</dt><dd>{ended ? "Call ended" : AWAITING_LABELS[state.awaiting] ?? "Next request"}</dd></div>
            </dl>
          </div>

          <div className="sheet-head" aria-hidden="true">
            <span>Conversation</span><span>What the agent understood and did</span>
          </div>
          <ol className="transcript">
            {turns.map((t, i) => (
              <li key={i} className={`turn turn-${t.role}`}>
                <div className="speech">
                  <span className="who">{t.role === "agent" ? "Agent" : firstName}</span>
                  <p lang={hasDevanagari(t.text) ? "hi" : undefined}>{t.text}</p>
                </div>
                {t.note && <Note note={t.note} />}
              </li>
            ))}
            {busy && call && !ended && <li className="turn turn-pending" aria-live="polite">Agent is thinking…</li>}
            <li ref={endRef} aria-hidden="true" />
          </ol>

          {ended ? (
            <p className="ended">Call ended. The summary appears on the dashboard in a few seconds.</p>
          ) : (
            <div className="composer">
              <form onSubmit={(e) => { e.preventDefault(); send(text); }}>
                <button type="button" className={`mic ${recording ? "is-recording" : ""}`}
                        onClick={toggleRecording} disabled={busy && !recording}
                        aria-pressed={recording}>
                  {recording ? "Stop and send" : "Speak"}
                </button>
                <label className="visually-hidden" htmlFor="say">Type what the customer says</label>
                <input id="say" ref={inputRef} value={text} onChange={(e) => setText(e.target.value)}
                       placeholder={state.awaiting === "tpin" ? "Say your 4-digit TPIN" : "Type what you'd say on the call"}
                       autoComplete="off" disabled={recording} />
                <button type="submit" className="primary" disabled={busy || !text.trim()}>Send</button>
              </form>
              <div className="composer-foot">
                <label className="field inline">
                  <span>Voice language</span>
                  <select value={voiceLang} onChange={(e) => setVoiceLang(e.target.value)}>
                    <option value="auto">Detect</option>
                    <option value="en">English</option>
                    <option value="hi">Hindi</option>
                  </select>
                </label>
                <label className="field inline check">
                  <input type="checkbox" checked={speakReplies}
                         onChange={(e) => { setSpeakReplies(e.target.checked); if (!e.target.checked) window.speechSynthesis?.cancel(); }} />
                  <span>Read replies aloud</span>
                </label>
                <button className="link" onClick={endCall} disabled={busy}>End call</button>
              </div>
              <div className="try">
                <span>Try saying</span>
                {TRY_SAYING.map((s) => (
                  <button key={s} className="chip" onClick={() => send(s)} disabled={busy}
                          lang={hasDevanagari(s) ? "hi" : undefined}>{s}</button>
                ))}
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function Note({ note }) {
  if (note.kind === "heard") {
    return (
      <aside className="note">
        <strong>{INTENT_LABELS[note.intent] ?? note.intent}</strong>
        <span>{LANGUAGE_LABELS[note.language]}, understood by {SOURCE_IN_SENTENCE[note.nlu_source]} in {note.latency_ms.nlu} ms</span>
        {note.latency_ms.stt > 0 && <span>Speech to text: {Math.round(note.latency_ms.stt)} ms</span>}
      </aside>
    );
  }
  return (
    <aside className="note note-did">
      <strong>{ACTION_LABELS[note.action] ?? "No bank action"}</strong>
      <span>Replied in {Math.round(note.latency_ms.total)} ms</span>
    </aside>
  );
}
