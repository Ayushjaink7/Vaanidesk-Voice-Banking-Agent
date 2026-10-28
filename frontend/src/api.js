// Small wrapper around fetch so every component talks to the API the same way.
const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(BASE + path, options);
  } catch {
    throw new Error(`Can't reach the API at ${BASE}. Is the backend running?`);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
  return body;
}

const json = (method, data) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: data ? JSON.stringify(data) : undefined,
});

export const api = {
  demoCustomers: () => request("/customers/demo"),
  health: () => request("/health"),
  startCall: (phone) => request("/calls", json("POST", { phone })),
  say: (callId, text) => request(`/calls/${callId}/turns`, json("POST", { text })),
  sendAudio: (callId, blob, language) => {
    const form = new FormData();
    form.append("file", blob, "voice.webm");
    form.append("language", language);
    return request(`/calls/${callId}/audio`, { method: "POST", body: form });
  },
  endCall: (callId) => request(`/calls/${callId}/end`, json("POST")),
  calls: (limit = 25) => request(`/calls?limit=${limit}`),
  call: (callId) => request(`/calls/${callId}`),
  stats: () => request("/stats"),
};
