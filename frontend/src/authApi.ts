/** Runtime-checked auth contract. Cookies stay browser-managed; no persistence. */
export class AuthError extends Error {
  constructor(public readonly kind: 'rejected' | 'csrf' | 'unavailable' | 'uncertain', message: string) { super(message); }
}
export interface Session {
  user: { id: string; email: string };
  expires_at: string;
  session_context: string;
}
export const uuid = (value: unknown): value is string => typeof value === 'string' && /^[\da-f]{8}(-[\da-f]{4}){3}-[\da-f]{12}$/i.test(value);
function csrf(value: unknown): string {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{32,128}$/.test(value)) throw new Error('Invalid response');
  return value;
}
function session(value: unknown, response: Response): Session {
  if (!value || typeof value !== 'object') throw new Error('Invalid response');
  const s = value as Record<string, unknown>, user = s.user as Record<string, unknown> | undefined;
  if (!user || !uuid(user.id) || typeof user.email !== 'string' || !user.email || user.email.length > 320 ||
      !uuid(s.session_context) || response.headers.get('X-Session-Context') !== s.session_context ||
      typeof s.expires_at !== 'string' || !Number.isFinite(Date.parse(s.expires_at))) throw new Error('Invalid response');
  return { user: { id: user.id, email: user.email }, session_context: s.session_context, expires_at: s.expires_at };
}
async function request(path: string, options: RequestInit, signal: AbortSignal) {
  return fetch(`/auth/${path}`, { ...options, credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.any([signal, AbortSignal.timeout(20_000)]) });
}
/** Focus checks do not rotate CSRF or create a new anonymous cookie. */
export async function currentSession(signal: AbortSignal): Promise<Session | null> {
  try {
    const response = await request('me', {}, signal);
    if (response.status === 401) return null;
    if (response.status !== 200) throw new Error('Unavailable');
    return session(await response.json(), response);
  } catch { throw new AuthError('unavailable', 'Your session could not be checked. Please try again.'); }
}
export async function restore(signal: AbortSignal): Promise<{ session: Session | null; csrf: string }> {
  try {
    const bootstrap = await request('csrf', {}, signal);
    if (bootstrap.status !== 200) throw new Error('Unavailable');
    const token = csrf((await bootstrap.json()).csrf_token);
    const response = await request('me', {}, signal);
    if (response.status === 401) return { session: null, csrf: token };
    if (response.status !== 200) throw new Error('Unavailable');
    const identity = session(await response.json(), response);
    // Cookies may have rotated in another tab between the two GET requests.
    if (bootstrap.headers.get('X-Session-Context') !== identity.session_context) throw new Error('Context changed');
    return { session: identity, csrf: token };
  } catch { throw new AuthError('unavailable', 'Your session could not be checked. Please try again.'); }
}
export async function submitCredentials(mode: 'login' | 'register', email: string, password: string, token: string, signal: AbortSignal) {
  try {
    const response = await request(mode, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token }, body: JSON.stringify({ email, password }) }, signal);
    if (response.status === 403) throw new AuthError('csrf', 'Your sign-in context changed. Check the session, then submit again.');
    if (response.status === 401) throw new AuthError('rejected', 'Email or password is incorrect.');
    if (response.status === 429) throw new AuthError('rejected', 'Too many attempts. Please wait before trying again.');
    if ([400, 413, 415, 422].includes(response.status)) throw new AuthError('rejected', 'Use a valid email and a password of 15–128 characters, at most 512 UTF-8 bytes.');
    if (mode === 'register' && response.status === 202) {
      const body = await response.json();
      if (body?.message !== 'Registration request processed. Try signing in with your credentials.') throw new Error('Invalid response');
      return null;
    }
    if (mode !== 'login' || response.status !== 200) throw new Error('Unconfirmed');
    const body = await response.json();
    return { session: session(body, response), csrf: csrf(body.csrf_token) };
  } catch (error) {
    if (error instanceof AuthError) throw error;
    throw new AuthError('uncertain', 'The request outcome could not be confirmed. Check your session before trying again.');
  }
}
export async function endSession(token: string, signal: AbortSignal): Promise<void> {
  try {
    const response = await request('logout', { method: 'POST', headers: { 'X-CSRF-Token': token } }, signal);
    if (response.status === 403) throw new AuthError('csrf', 'Your session changed. Check it before trying logout again.');
    if (response.status !== 204) throw new Error('Unconfirmed');
  } catch (error) {
    if (error instanceof AuthError) throw error;
    throw new AuthError('uncertain', 'Logout could not be confirmed. Your private view is hidden; retry logout.');
  }
}
