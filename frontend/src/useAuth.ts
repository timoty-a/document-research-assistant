import { useEffect, useRef, useState } from 'react';
import { AuthError, currentSession, endSession, restore, submitCredentials, type Session } from './authApi';

export type AuthState =
  | { status: 'checking' | 'unavailable'; message?: string }
  | { status: 'anonymous'; message?: string }
  | { status: 'authenticated'; session: Session; generation: number }
  | { status: 'logout-pending'; message?: string };
export interface LibrarySession { context: string; csrf: string; signal: AbortSignal; isCurrent: () => boolean; invalidate: (message: string) => void }

export function useAuth() {
  const [state, setState] = useState<AuthState>({ status: 'checking' });
  const [pending, setPending] = useState(false);
  const [rechecking, setRechecking] = useState(false);
  const focusCheckId = useRef(0), focusChecking = useRef(false);
  const [error, setError] = useState('');
  const epoch = useRef(0), controller = useRef(new AbortController());
  const csrf = useRef(''), busy = useRef(false), alive = useRef(true);
  const current = useRef<AuthState>(state), channel = useRef<BroadcastChannel | null>(null);
  const logoutIntent = useRef(false);
  function show(next: AuthState) { current.current = next; setState(next); }
  function boundary() {
    controller.current.abort(); controller.current = new AbortController();
    epoch.current++; busy.current = false; setPending(false); setError('');
    focusCheckId.current++; focusChecking.current = false; setRechecking(false);
    return epoch.current;
  }
  const valid = (generation: number) => alive.current && generation === epoch.current;
  function announce() { channel.current?.postMessage('auth-changed'); }

  async function check(message?: string) {
    // A failed logout stays hidden until the user explicitly chooses to check.
    const generation = boundary(); csrf.current = ''; show({ status: 'checking' });
    try {
      const restored = await restore(controller.current.signal);
      if (!valid(generation)) return;
      csrf.current = restored.csrf;
      show(restored.session ? { status: 'authenticated', session: restored.session, generation } : { status: 'anonymous', message });
    } catch {
      if (valid(generation)) show({ status: 'unavailable', message: 'Your session could not be checked. Please try again.' });
    }
  }
  async function checkOnFocus() {
    if (busy.current || logoutIntent.current || focusChecking.current) return;
    const previous = current.current;
    if (previous.status !== 'authenticated') { void check(); return; }
    const generation = epoch.current, request = ++focusCheckId.current;
    focusChecking.current = true; setRechecking(true);
    // Keep the same mounted file input while hidden. Native pickers can send
    // focus before OR after change; remounting here destroys their selection.
    try {
      const verified = await currentSession(controller.current.signal);
      if (!valid(generation) || request !== focusCheckId.current) return;
      if (!verified || verified.session_context !== previous.session.session_context || verified.user.id !== previous.session.user.id) {
        await check(verified ? undefined : 'Your session ended. Please log in again.');
      } else {
        show({ ...previous, session: verified });
      }
    } catch {
      if (valid(generation) && request === focusCheckId.current) {
        boundary(); csrf.current = '';
        show({ status: 'unavailable', message: 'Your session could not be checked. Please try again.' });
      }
    } finally {
      if (valid(generation) && request === focusCheckId.current) {
        focusChecking.current = false; setRechecking(false);
      }
    }
  }
  async function submit(mode: 'login' | 'register', email: string, password: string) {
    if (busy.current || current.current.status !== 'anonymous') return false;
    busy.current = true; setPending(true); setError('');
    const generation = epoch.current;
    try {
      const result = await submitCredentials(mode, email, password, csrf.current, controller.current.signal);
      if (!valid(generation)) {
        announce();
        if (alive.current && !logoutIntent.current) void check();
        return false;
      }
      if (result) {
        const next = boundary(); csrf.current = result.csrf;
        show({ status: 'authenticated', session: result.session, generation: next }); announce();
      } else {
        show({ status: 'anonymous', message: 'Registration request processed. Try signing in with your credentials.' });
      }
      return true;
    } catch (failure) {
      if (!valid(generation)) return false;
      const safe = failure instanceof AuthError ? failure : new AuthError('uncertain', 'The request outcome could not be confirmed.');
      if (safe.kind === 'csrf' || safe.kind === 'uncertain') {
        boundary(); csrf.current = '';
        show({ status: 'unavailable', message: safe.message }); announce();
      } else setError(safe.message);
      return false;
    } finally {
      if (valid(generation)) { busy.current = false; setPending(false); }
    }
  }
  async function logout() {
    if (busy.current) return;
    logoutIntent.current = true;
    const generation = boundary(); busy.current = true; setPending(true); show({ status: 'logout-pending' }); announce();
    try {
      await endSession(csrf.current, controller.current.signal);
      if (!valid(generation)) return;
      csrf.current = ''; logoutIntent.current = false; announce();
      // Safe GET bootstrap, never replay the mutation.
      await check('You have logged out.');
    } catch (failure) {
      if (valid(generation)) show({ status: 'logout-pending', message: failure instanceof AuthError ? failure.message : 'Logout could not be confirmed. Please retry.' });
    } finally { if (valid(generation)) { busy.current = false; setPending(false); } }
  }
  function retryCheck() { logoutIntent.current = false; void check(); }
  useEffect(() => {
    alive.current = true; void check();
    if (typeof BroadcastChannel !== 'undefined') {
      channel.current = new BroadcastChannel('dra-auth');
      channel.current.onmessage = event => {
        if (event.data !== 'auth-changed' || logoutIntent.current) return;
        void check();
      };
    }
    const focus = () => { void checkOnFocus(); };
    window.addEventListener('focus', focus);
    return () => { alive.current = false; epoch.current++; controller.current.abort(); channel.current?.close(); window.removeEventListener('focus', focus); };
  }, []);
  let library: LibrarySession | null = null;
  if (state.status === 'authenticated') {
    const generation = state.generation;
    library = { context: state.session.session_context, csrf: csrf.current, signal: controller.current.signal,
      isCurrent: () => valid(generation) && current.current.status === 'authenticated',
      invalidate: message => { if (valid(generation)) void check(message); } };
  }
  return { state, pending, rechecking, error, submit, logout, retryCheck, library };
}
