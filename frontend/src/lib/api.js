// Single place that knows how to talk to the FastAPI backend.
// Owns the base URL, the JWT, and error handling so components don't repeat it.

// Vite inlines VITE_* vars at BUILD time, not run time — so the deployed
// frontend must be built with VITE_API_BASE_URL already set to the real
// backend URL (`VITE_API_BASE_URL=https://... npm run build`). The fallback
// keeps local `npm run dev` working with no .env file at all.
const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const TOKEN_KEY = "rag_token";

// --- token storage -----------------------------------------------------------
// localStorage is a key/value store in the browser that survives refreshes and
// browser restarts — that's what makes "stay logged in" work.
// Trade-off: any JS on the page can read it, so an XSS flaw could steal the token.

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

// --- the core request helper every call below goes through -------------------

async function request(path, { method = "GET", body, auth = true } = {}) {
  const headers = {};

  // Only sending a body? Then tell the server it's JSON.
  if (body !== undefined) headers["Content-Type"] = "application/json";

  // Attach the JWT. This is the header get_current_user_id reads on the backend.
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  // fetch resolves as soon as the HEADERS arrive — the body may still be downloading.
  // `res` is a Response object (an envelope: status + headers + an unread body).
  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    // JSON.stringify turns a JS object into the JSON text the server expects.
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  // A 401 on an AUTHENTICATED call means our token is dead → clean logout.
  // A 401 on login/signup (auth: false) just means bad credentials, so let it
  // fall through and report the server's real message instead.
  if (res.status === 401 && auth) {
    clearToken();
    throw new Error("Your session expired. Please log in again.");
  }

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      // res.json() reads the body off the network AND parses the text into an object.
      // FastAPI sends errors as {"detail": "..."} — pull that out for a real message.
      const data = await res.json();
      if (data.detail) message = data.detail;
    } catch {
      // Body wasn't JSON (e.g. an HTML error page) — keep the fallback message.
    }
    // Throwing (instead of returning an error value) means a caller CAN'T silently
    // ignore it: components just wrap calls in try/catch and read err.message.
    throw new Error(message);
  }

  if (res.status === 204) return null; // 204 No Content — DELETE returns no body
  return res.json();
}

// --- auth --------------------------------------------------------------------

export function signup(email, password, displayName) {
  return request("/auth/signup", {
    method: "POST",
    auth: false, // no token yet — that's the whole point of signing up
    body: { email, password, display_name: displayName || null },
  });
}

export function login(email, password) {
  return request("/auth/login", {
    method: "POST",
    auth: false,
    body: { email, password },
  });
}

export function me() {
  return request("/auth/me");
}

// --- conversations -----------------------------------------------------------

export function createConversation() {
  return request("/conversations", { method: "POST" });
}

export function listConversations(limit = 30, offset = 0) {
  return request(`/conversations?limit=${limit}&offset=${offset}`);
}

export function getMessages(conversationId, limit = 100, offset = 0) {
  return request(`/conversations/${conversationId}/messages?limit=${limit}&offset=${offset}`);
}

export function renameConversation(conversationId, title) {
  return request(`/conversations/${conversationId}`, {
    method: "PATCH",
    body: { title },
  });
}

export function deleteConversation(conversationId) {
  return request(`/conversations/${conversationId}`, { method: "DELETE" });
}

// --- chat (streaming) --------------------------------------------------------
// Not using the browser's EventSource API: that's GET-only, and /query/stream is a
// POST with a body. So we read the SSE stream out of the fetch response ourselves.
//
// The handlers are callbacks — the component passes "here's what to do with each
// event", and we call them as events arrive. onToken is what makes text appear
// word-by-word; onStatus reports which pipeline stage the backend is on.
// Named options (not positional args) so new event types don't churn the signature.

export async function streamQuery(conversationId, q, { onToken, onStatus, onSources } = {}) {
  const token = getToken();

  const res = await fetch(`${BASE_URL}/query/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ q, conversation_id: conversationId }),
  });

  if (res.status === 401) {
    clearToken();
    throw new Error("Your session expired. Please log in again.");
  }

  if (!res.ok) {
    // Same detail-extraction as request() so errors read the same everywhere.
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (data.detail) message = data.detail;
    } catch {
      // not JSON — keep the fallback
    }
    throw new Error(message);
  }

  // res.body is a ReadableStream of raw bytes; getReader() lets us pull it chunk
  // by chunk instead of waiting for the whole response. Both are browser built-ins.
  const reader = res.body.getReader();
  const decoder = new TextDecoder(); // bytes -> text
  let buffer = ""; // holds text that hasn't formed a complete SSE event yet

  while (true) {
    // Waits for the next chunk. value = Uint8Array of bytes, done = stream closed.
    // This await is where the browser parks while the network delivers.
    const { value, done } = await reader.read();
    if (done) break;

    // Decode the bytes and append. {stream: true} keeps partial multi-byte characters
    // (like é split across two chunks) intact instead of producing garbage.
    buffer += decoder.decode(value, { stream: true });

    // SSE events are separated by a blank line. Network chunks don't align with
    // events — one chunk may hold two events, or half of one.
    //   buffer: 'data: {"token":"Kube"}\n\ndata: {"token":" is"}\n\ndata: {"tok'
    const events = buffer.split("\n\n");
    //   events: ['data: {"token":"Kube"}', 'data: {"token":" is"}', 'data: {"tok']

    // pop() removes AND returns the last piece — which is incomplete, because the
    // chunk cut off mid-event. Save it to be finished by the next chunk.
    // Without this, JSON.parse('{"tok') would crash.
    buffer = events.pop();
    //   events: complete ones only     buffer: 'data: {"tok'

    for (const event of events) {
      const line = event.trim();
      if (!line.startsWith("data: ")) continue;

      // slice(6) drops the "data: " prefix, leaving '{"token":"Kube"}';
      // JSON.parse turns that text into the object {token: "Kube"}.
      const payload = JSON.parse(line.slice(6));

      if (payload.token) onToken?.(payload.token); // <- this line types text on screen
      if (payload.status) onStatus?.(payload.status); // pipeline stage for the UI
      if (payload.sources) onSources?.(payload.sources); // retrieved chunks
      if (payload.error) throw new Error(payload.error);
      if (payload.done) return; // backend's final {"done": true} ends the stream
    }
  }
}
