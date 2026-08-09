// Stable per-browser id used to look up this user's Outlook tokens on the
// backend. Kept in localStorage rather than a cookie because the frontend and
// backend sit on different origins, and Safari blocks third-party cookies.

const KEY = 'ea_session_id'

function randomId() {
  if (crypto.randomUUID) return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
}

export function getSessionId() {
  let id = localStorage.getItem(KEY)
  if (!id) {
    id = randomId()
    localStorage.setItem(KEY, id)
  }
  return id
}
