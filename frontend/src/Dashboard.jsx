import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { INTENT_LABELS, LANGUAGE_LABELS, OUTCOME_LABELS, SOURCE_LABELS } from "./labels.js";

const pct = (x) => (x == null ? "–" : `${Math.round(x * 100)}%`);
const time = (iso) => new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const MOOD_LABELS = { positive: "Positive", neutral: "Neutral", negative: "Negative" };

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [calls, setCalls] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([api.stats(), api.calls()]);
      setStats(s); setCalls(c); setError("");
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 10000);   // refresh every 10 s
    return () => clearInterval(timer);
  }, [load]);

  return (
    <div className="dashboard">
      <div className="dash-head">
        <h2>How the agent is doing</h2>
        <button className="link" onClick={load}>Refresh</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}

      {stats && (
        <>
          <dl className="tiles">
            <div><dt>Calls handled</dt><dd>{stats.total_calls}</dd></div>
            <div><dt>Resolved by the agent</dt><dd>{pct(stats.resolution_rate)}</dd></div>
            <div><dt>Handed to a human</dt><dd>{pct(stats.transfer_rate)}</dd></div>
            <div>
              <dt>Reply time, 95% of turns under</dt>
              <dd>{stats.latency_ms.p95 == null ? "–" : `${Math.round(stats.latency_ms.p95)} ms`}</dd>
            </div>
          </dl>

          <div className="charts">
            <BarList title="What customers asked for" data={stats.intents} labels={INTENT_LABELS} unit="calls" />
            <BarList title="Languages" data={stats.languages} labels={LANGUAGE_LABELS} unit="calls" />
            <BarList title="Customer mood" data={stats.sentiment} labels={MOOD_LABELS} unit="calls" />
            <BarList title="Who understood each turn" data={stats.nlu_sources} labels={SOURCE_LABELS} unit="turns" />
          </div>
        </>
      )}

      <section className="calls">
        <h3>Recent calls</h3>
        {calls.length === 0 ? (
          <p className="muted">No calls yet. Start one from the Live call page.</p>
        ) : (
          <div className="calls-layout">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Started</th><th>Customer</th><th>Language</th><th>Asked about</th><th>Outcome</th><th>Mood</th></tr>
                </thead>
                <tbody>
                  {calls.map((c) => (
                    <tr key={c._id} className={c._id === openId ? "is-open" : undefined}>
                      <td><button className="row-link" onClick={() => setOpenId(c._id)}>{time(c.started_at)}</button></td>
                      <td>{c.customer_name}</td>
                      <td>{LANGUAGE_LABELS[c.language]}</td>
                      <td>{c.intents.map((i) => INTENT_LABELS[i]).join(", ") || "–"}</td>
                      <td>{c.status === "active" ? "In progress" : c.summary ? OUTCOME_LABELS[c.summary.disposition] : "Summarising…"}</td>
                      <td>{c.summary ? MOOD_LABELS[c.summary.sentiment] : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {openId && <CallDetail id={openId} onClose={() => setOpenId(null)} />}
          </div>
        )}
      </section>
    </div>
  );
}

function BarList({ title, data, labels, unit }) {
  const entries = Object.entries(data || {}).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, v]) => sum + v, 0);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  return (
    <section className="barlist">
      <h3>{title}</h3>
      {entries.length === 0 ? (
        <p className="muted">Nothing yet</p>
      ) : (
        <ul>
          {entries.map(([key, value]) => (
            <li key={key} tabIndex={0} aria-label={`${labels[key] ?? key}: ${value} ${unit}`}>
              <span className="bar-label">{labels[key] ?? key}</span>
              <span className="bar-track"><span className="bar" style={{ width: `${(value / max) * 100}%` }} /></span>
              <span className="bar-value">{value}</span>
              <span className="tip" role="tooltip">{value} {unit}, {Math.round((value / total) * 100)}% of all</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function CallDetail({ id, onClose }) {
  const [call, setCall] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setCall(null);
    api.call(id).then(setCall).catch((e) => setError(e.message));
  }, [id]);

  return (
    <aside className="detail" aria-label="Call details">
      <div className="detail-head">
        <h3>{call ? call.customer_name : "Loading call…"}</h3>
        <button className="link" onClick={onClose}>Close</button>
      </div>
      {error && <p className="error">{error}</p>}
      {call && (
        <>
          {call.summary ? (
            <div className="summary">
              <p>{call.summary.summary}</p>
              <p className="muted">
                {OUTCOME_LABELS[call.summary.disposition]}. Mood: {MOOD_LABELS[call.summary.sentiment]}.
                {call.summary.follow_up && call.summary.follow_up !== "none" && <> Follow-up: {call.summary.follow_up}.</>}
              </p>
            </div>
          ) : (
            <p className="muted">{call.status === "active" ? "This call is still in progress." : "The summary is being written."}</p>
          )}
          <ol className="mini-transcript">
            {call.turns.map((t, i) => (
              <li key={i} className={`turn-${t.role}`}>
                <span className="who">{t.role === "agent" ? "Agent" : call.customer_name.split(" ")[0]}</span>
                <p>{t.text}</p>
              </li>
            ))}
          </ol>
        </>
      )}
    </aside>
  );
}
