import { useEffect, useRef, useState, type FormEvent } from 'react';

export function AuthForm({ pending, error, message, submit }: {
  pending: boolean; error: string; message?: string;
  submit: (mode: 'login' | 'register', email: string, password: string) => Promise<boolean>;
}) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState(''), [password, setPassword] = useState('');
  const [localError, setLocalError] = useState('');
  const passwordInput = useRef<HTMLInputElement>(null), errorBox = useRef<HTMLDivElement>(null);
  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const count = [...password].length;
    if (count < 15 || count > 128 || new TextEncoder().encode(password).length > 512) {
      setLocalError('Use a password of 15–128 characters, at most 512 UTF-8 bytes.'); passwordInput.current?.focus(); return;
    }
    setLocalError('');
    const value = password; setPassword('');
    const success = await submit(mode, email, value);
    if (success && mode === 'register') { setMode('login'); passwordInput.current?.focus(); }
    if (!success) errorBox.current?.focus();
  }
  const shownError = localError || error;
  useEffect(() => { if (shownError && !pending) errorBox.current?.focus(); }, [shownError, pending]);
  return <main id="main" className="auth-layout">
    <section className="auth-intro"><p className="eyebrow">A place for your sources</p><h1>{mode === 'login' ? 'Return to your research.' : 'Make room for your sources.'}</h1><p className="intro-copy">Keep your documents together, in a library that belongs to you.</p><p className="local-notice">Local version · Email verification and password recovery are unavailable. Keep your password somewhere safe.</p></section>
    <section className="auth-panel" aria-labelledby="auth-heading">
      <h2 id="auth-heading">{mode === 'login' ? 'Log in' : 'Register'}</h2>
      {message && <div className="message" role="status"><p>{message}</p></div>}
      {shownError && <div ref={errorBox} tabIndex={-1} id="auth-error" className="message error" role="alert"><p>{shownError}</p></div>}
      <form onSubmit={send} aria-describedby={shownError ? 'auth-error' : undefined} aria-busy={pending}>
        <label htmlFor="email">Email</label><input id="email" type="email" autoComplete="email" maxLength={320} required disabled={pending} value={email} onChange={e => setEmail(e.target.value)} />
        <label htmlFor="password">Password</label><input ref={passwordInput} id="password" type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} required disabled={pending} value={password} onChange={e => setPassword(e.target.value)} aria-describedby="password-help" aria-invalid={!!shownError} />
        <p id="password-help" className="field-help">15–128 characters. Spaces are welcome.</p>
        <button type="submit" className="button primary" disabled={pending}>{pending ? mode === 'login' ? 'Logging in…' : 'Registering…' : mode === 'login' ? 'Log in' : 'Register'}</button>
      </form>
      <div className="auth-switch"><p>{mode === 'login' ? 'New here?' : 'Already have an account?'}</p><button className="button" disabled={pending} onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setPassword(''); setLocalError(''); }}>{mode === 'login' ? 'Create an account' : 'Back to log in'}</button></div>
    </section>
  </main>;
}
