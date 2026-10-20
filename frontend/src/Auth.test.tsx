import { StrictMode } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from './App';
import { type Session } from './authApi';

const a: Session = { user: { id: '11111111-1111-4111-8111-111111111111', email: 'a@example.com' }, session_context: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', expires_at: '2030-01-01T12:00:00Z' };
const b: Session = { ...a, user: { ...a.user, id: '22222222-2222-4222-8222-222222222222', email: 'b@example.com' }, session_context: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb' };
const token = 'synthetic_csrf_12345678901234567890123';
const row = { id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', original_filename: 'private-a.txt', byte_size: 4, source_format: 'txt', page_count: null, textless_pages: [], created_at: '2026-10-17T12:00:00Z' };
const reply = (body: unknown, status = 200, context?: string) => new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...(context ? { 'X-Session-Context': context } : {}) } });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => resolve = r); return { promise, resolve }; }
let identity: Session | null;
let fetchMock: ReturnType<typeof vi.fn>;
let override: (path: string, init?: RequestInit) => Promise<Response> | undefined;
class Channel {
  static instances: Channel[] = [];
  onmessage: ((event: { data: unknown }) => void) | null = null;
  postMessage = vi.fn(); close = vi.fn();
  constructor() { Channel.instances.push(this); }
}
beforeEach(() => {
  identity = a; override = () => undefined; Channel.instances = [];
  vi.stubGlobal('BroadcastChannel', Channel);
  fetchMock = vi.fn((path: string, init?: RequestInit) => {
    const custom = override(path, init); if (custom) return custom;
    if (path === '/auth/csrf') return Promise.resolve(reply({ csrf_token: token }, 200, identity?.session_context));
    if (path === '/auth/me') return Promise.resolve(identity ? reply(identity, 200, identity.session_context) : reply({}, 401));
    if (path === '/documents') return Promise.resolve(reply(identity === a ? [row] : [], 200, identity?.session_context));
    throw new Error('Unexpected mock route');
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());
async function loaded() { render(<App />); await screen.findByText(row.original_filename); return userEvent.setup(); }
async function anonymous() { identity = null; render(<App />); await screen.findByRole('heading', { name: 'Log in' }); return userEvent.setup(); }
async function fill(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Email'), 'a@example.com');
  await user.type(screen.getByLabelText('Password'), 'Synthetic password only 123');
}
function event() { act(() => Channel.instances.at(-1)?.onmessage?.({ data: 'auth-changed' })); }

it('checks before mounting private data and restores a confirmed session', async () => {
  const pending = deferred<Response>();
  override = path => path === '/auth/csrf' ? pending.promise : undefined;
  render(<App />);
  expect(screen.getByText('Checking your session.')).toBeInTheDocument();
  expect(screen.queryByText('Document library.')).not.toBeInTheDocument();
  await act(async () => pending.resolve(reply({ csrf_token: token }, 200, a.session_context)));
  expect(await screen.findByText('a@example.com')).toBeInTheDocument();
  await screen.findByText(row.original_filename);
  expect(fetchMock.mock.calls.every(([, init]) => init.credentials === 'same-origin')).toBe(true);
});
it('offers labelled fields, autocomplete, local limitations and explicit registration then login', async () => {
  const user = await anonymous();
  expect(screen.getByLabelText('Email')).toHaveAttribute('autocomplete', 'email');
  expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'current-password');
  expect(screen.getByText(/Email verification and password recovery are unavailable/)).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Create an account' }));
  expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'new-password');
  override = path => path === '/auth/register' ? Promise.resolve(reply({ message: 'Registration request processed. Try signing in with your credentials.' }, 202)) : undefined;
  await fill(user); await user.click(screen.getByRole('button', { name: 'Register' }));
  await screen.findByText('Registration request processed. Try signing in with your credentials.');
  expect(screen.getByRole('heading', { name: 'Log in' })).toBeInTheDocument();
  expect(screen.getByLabelText('Password')).toHaveValue('');
  expect(fetchMock.mock.calls.filter(([path]) => path === '/auth/login')).toHaveLength(0);
  override = path => {
    if (path === '/auth/login') { identity = a; return Promise.resolve(reply({ ...a, csrf_token: token }, 200, a.session_context)); }
  };
  await user.type(screen.getByLabelText('Password'), 'Synthetic password only 123');
  await user.click(screen.getByRole('button', { name: 'Log in' }));
  await screen.findByText(row.original_filename);
  const call = fetchMock.mock.calls.find(([path]) => path === '/auth/login')!;
  expect(call[1].headers['X-CSRF-Token']).toBe(token);
  expect(document.querySelector('input[type=password]')).toBeNull();
});
it('shows generic credential errors, clears password and never displays raw details', async () => {
  const user = await anonymous(); override = path => path === '/auth/login' ? Promise.resolve(reply({ detail: 'private SQL password' }, 401)) : undefined;
  await fill(user); await user.click(screen.getByRole('button', { name: 'Log in' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Email or password is incorrect.');
  expect(screen.getByLabelText('Password')).toHaveValue('');
  expect(document.body.textContent).not.toContain('private SQL');
});
it('prevents duplicate login while pending and provides a busy state', async () => {
  const user = await anonymous(), pending = deferred<Response>();
  override = path => path === '/auth/login' ? pending.promise : undefined;
  await fill(user); await user.dblClick(screen.getByRole('button', { name: 'Log in' }));
  expect(screen.getByRole('button', { name: 'Logging in…' })).toBeDisabled();
  expect(fetchMock.mock.calls.filter(([path]) => path === '/auth/login')).toHaveLength(1);
  identity = a; await act(async () => pending.resolve(reply({ ...a, csrf_token: token }, 200, a.session_context)));
  await screen.findByText(row.original_filename);
});
it.each([403, 500, 503, 200])('auth %s failure never automatically replays a mutation', async status => {
  const user = await anonymous(); override = path => path === '/auth/login' ? Promise.resolve(reply({}, status)) : undefined;
  await fill(user); await user.click(screen.getByRole('button', { name: 'Log in' }));
  await screen.findByRole('button', { name: 'Check session' });
  expect(screen.queryByText('Document library.')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Check session' }));
  await screen.findByRole('heading', { name: 'Log in' });
  expect(fetchMock.mock.calls.filter(([path]) => path === '/auth/login')).toHaveLength(1);
});
it('unavailable session is not mistaken for anonymous', async () => {
  override = path => path === '/auth/me' ? Promise.reject(new Error('private error')) : undefined;
  render(<App />); await screen.findByText('Your session could not be checked. Please try again.');
  expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
  expect(screen.queryByText(row.original_filename)).not.toBeInTheDocument();
});
it('hides documents, files and details immediately on logout, with explicit retry after failure', async () => {
  const user = await loaded();
  await user.upload(screen.getByLabelText('Choose a document'), new File(['text'], 'selected-private.txt'));
  await user.click(document.querySelector('summary')!);
  const pending = deferred<Response>(); override = path => path === '/auth/logout' ? pending.promise : undefined;
  await user.click(screen.getByRole('button', { name: 'Log out' }));
  expect(screen.queryByText(row.original_filename)).not.toBeInTheDocument();
  expect(screen.queryByText('selected-private.txt')).not.toBeInTheDocument();
  expect(document.querySelector('details')).toBeNull();
  await act(async () => pending.resolve(reply({}, 503)));
  await screen.findByText(/Logout could not be confirmed/);
  act(() => window.dispatchEvent(new Event('focus')));
  expect(screen.queryByText(row.original_filename)).not.toBeInTheDocument();
  override = path => { if (path === '/auth/logout') { identity = null; return Promise.resolve(reply(null, 204)); } };
  await user.click(screen.getByRole('button', { name: 'Retry logout' }));
  await screen.findByText('You have logged out.');
  expect(fetchMock.mock.calls.filter(([path]) => path === '/auth/logout')).toHaveLength(2);
});
it.each([200, 401])('discards delayed A list %s, including stale 401, after B becomes active', async status => {
  const user = await loaded(), old = deferred<Response>();
  let listCalls = 0;
  override = path => path === '/documents' && listCalls++ === 0 ? old.promise : undefined;
  await user.click(screen.getByRole('button', { name: 'Refresh' }));
  identity = b; event(); await screen.findByText('b@example.com'); await screen.findByText('0 documents');
  await act(async () => old.resolve(reply([row], status, a.session_context)));
  expect(screen.queryByText(row.original_filename)).not.toBeInTheDocument();
  expect(screen.getByText('b@example.com')).toBeInTheDocument();
});
it('discards delayed A upload and confirmations after B login; same filenames are not identity', async () => {
  const user = await loaded(), old = deferred<Response>();
  override = (path, init) => path === '/documents' && init?.method === 'POST' ? old.promise : undefined;
  await user.upload(screen.getByLabelText('Choose a document'), new File(['text'], 'private-a.txt'));
  await user.click(screen.getByRole('button', { name: 'Upload document' }));
  identity = b; event(); await screen.findByText('b@example.com');
  await act(async () => old.resolve(reply(row, 201, a.session_context)));
  expect(screen.queryByText('Document saved')).not.toBeInTheDocument();
  expect(screen.getByText('0 documents')).toBeInTheDocument();
  expect(screen.getByText('No file selected')).toBeInTheDocument();
});
it('context mismatch clears private view and rechecks; no data from another context accepted', async () => {
  const user = await loaded(); identity = b;
  await user.click(screen.getByRole('button', { name: 'Refresh' }));
  await screen.findByText('b@example.com');
  expect(screen.queryByText(row.original_filename)).not.toBeInTheDocument();
});
it('expired session clears private view without automatically replaying an upload', async () => {
  const user = await loaded(); identity = null;
  override = path => path === '/documents' ? Promise.resolve(reply({}, 401)) : undefined;
  await user.upload(screen.getByLabelText('Choose a document'), new File(['text'], 'same.txt'));
  await user.click(screen.getByRole('button', { name: 'Upload document' }));
  await screen.findByText('Your session ended. Please log in again.');
  expect(screen.queryByText(row.original_filename)).not.toBeInTheDocument();
  expect(fetchMock.mock.calls.filter(([path, init]) => path === '/documents' && init?.method === 'POST')).toHaveLength(1);
});
it('same-user new session clears selected files and expanded details on focus revalidation', async () => {
  const user = await loaded();
  await user.upload(screen.getByLabelText('Choose a document'), new File(['text'], 'pending.txt'));
  await user.click(document.querySelector('summary')!);
  identity = { ...a, session_context: b.session_context };
  act(() => window.dispatchEvent(new Event('focus')));
  await screen.findByText('0 documents');
  expect(screen.getByText('No file selected')).toBeInTheDocument();
  expect(document.querySelector('details[open]')).toBeNull();
});
it('does not accept delayed login body after a newer session check', async () => {
  const user = await anonymous(), old = deferred<Response>();
  override = path => path === '/auth/login' ? old.promise : undefined;
  await fill(user); await user.click(screen.getByRole('button', { name: 'Log in' }));
  identity = b; event(); await screen.findByText('b@example.com');
  await act(async () => old.resolve(reply({ ...a, csrf_token: token }, 200, a.session_context)));
  expect(screen.getByText('b@example.com')).toBeInTheDocument();
  expect(screen.queryByText('a@example.com')).not.toBeInTheDocument();
});
it('broadcasts only a non-secret event and never persists credentials', async () => {
  const storage = vi.spyOn(Storage.prototype, 'setItem');
  const user = await loaded(); override = path => { if (path === '/auth/logout') { identity = null; return Promise.resolve(reply(null, 204)); } };
  await user.click(screen.getByRole('button', { name: 'Log out' })); await screen.findByRole('heading', { name: 'Log in' });
  expect(Channel.instances[0].postMessage.mock.calls.every(([message]) => message === 'auth-changed')).toBe(true);
  expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
});
it('rejects a CSRF/bootstrap and me context race', async () => {
  override = path => path === '/auth/csrf' ? Promise.resolve(reply({ csrf_token: token }, 200, b.session_context)) : undefined;
  render(<App />); await screen.findByRole('button', { name: 'Check session' });
  expect(screen.queryByText(row.original_filename)).not.toBeInTheDocument();
});
it('ignores stale initial restoration under StrictMode', async () => {
  const old = deferred<Response>(); let bootstrapCalls = 0;
  override = path => path === '/auth/csrf' && bootstrapCalls++ === 0 ? old.promise : undefined;
  render(<StrictMode><App /></StrictMode>); await screen.findByText(row.original_filename);
  await act(async () => old.resolve(reply({ csrf_token: token }, 200, b.session_context)));
  expect(screen.getByText(row.original_filename)).toBeInTheDocument();
});
it('session changes release an old pending mutation without letting its completion affect the new session', async () => {
  const user = await anonymous(), old = deferred<Response>();
  override = path => path === '/auth/login' ? old.promise : undefined;
  await fill(user); await user.click(screen.getByRole('button', { name: 'Log in' }));
  identity = b; event(); await screen.findByText('b@example.com');
  override = path => { if (path === '/auth/logout') { identity = null; return Promise.resolve(reply(null, 204)); } };
  await user.click(screen.getByRole('button', { name: 'Log out' }));
  await screen.findByRole('heading', { name: 'Log in' });
  await act(async () => old.resolve(reply({ ...a, csrf_token: token }, 200, a.session_context)));
  expect(screen.queryByText('a@example.com')).not.toBeInTheDocument();
});
it('a rejected upload CSRF check clears the selection, rechecks and never replays', async () => {
  const user = await loaded();
  override = (path, init) => path === '/documents' && init?.method === 'POST' ? Promise.resolve(reply({}, 403)) : undefined;
  await user.upload(screen.getByLabelText('Choose a document'), new File(['text'], 'same.txt'));
  await user.click(screen.getByRole('button', { name: 'Upload document' }));
  await screen.findByText('No file selected');
  expect(fetchMock.mock.calls.filter(([path, init]) => path === '/documents' && init?.method === 'POST')).toHaveLength(1);
});

it('keeps the selected file when returning from the picker to the same session, then displays a confirmed upload', async () => {
  const user = await loaded();
  const selected = new File(['text'], 'chosen.txt');
  await user.upload(screen.getByLabelText('Choose a document'), selected);
  act(() => window.dispatchEvent(new Event('focus')));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Upload document' })).toBeEnabled());
  expect(screen.getByText('chosen.txt')).toBeInTheDocument();
  const saved = { ...row, id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', original_filename: 'chosen.txt' };
  override = (path, init) => path === '/documents' && init?.method === 'POST' ? Promise.resolve(reply(saved, 201, a.session_context)) : undefined;
  await user.click(screen.getByRole('button', { name: 'Upload document' }));
  await screen.findByText('Document saved');
  expect(screen.getByText('2 documents')).toBeInTheDocument();
  expect(document.querySelectorAll('details')).toHaveLength(2);
  expect(fetchMock.mock.calls.filter(([path, init]) => path === '/documents' && init?.method === 'POST')).toHaveLength(1);
});

it('retains the native file input when focus arrives before its change event', async () => {
  await loaded();
  const picker = screen.getByLabelText('Choose a document');
  const pending = deferred<Response>();
  override = path => path === '/auth/me' ? pending.promise : undefined;
  act(() => window.dispatchEvent(new Event('focus')));
  expect(screen.getByText(row.original_filename)).not.toBeVisible();
  expect(document.getElementById('document-file')).toBe(picker);
  fireEvent.change(picker, { target: { files: [new File(['text'], 'picker-result.txt')] } });
  await act(async () => pending.resolve(reply(a, 200, a.session_context)));
  expect(screen.getByText('picker-result.txt')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Upload document' })).toBeEnabled();
});
it('preserves an in-flight upload and its confirmed row across same-session focus checks', async () => {
  const user = await loaded(), upload = deferred<Response>(), me = deferred<Response>();
  const saved = { ...row, id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', original_filename: 'focus-upload.txt' };
  override = (path, init) => path === '/auth/me' ? me.promise : path === '/documents' && init?.method === 'POST' ? upload.promise : undefined;
  await user.upload(screen.getByLabelText('Choose a document'), new File(['text'], saved.original_filename));
  await user.click(screen.getByRole('button', { name: 'Upload document' }));
  act(() => window.dispatchEvent(new Event('focus')));
  await act(async () => upload.resolve(reply(saved, 201, a.session_context)));
  expect(screen.getByText('Document saved')).not.toBeVisible();
  await act(async () => me.resolve(reply(a, 200, a.session_context)));
  expect(screen.getByText('Document saved')).toBeVisible();
  expect(screen.getByText('2 documents')).toBeVisible();
  expect(fetchMock.mock.calls.filter(([path, init]) => path === '/documents' && init?.method === 'POST')).toHaveLength(1);
});
it('discards a stale focus check after a cross-tab account change', async () => {
  await loaded(); const old = deferred<Response>(); let calls = 0;
  override = path => path === '/auth/me' && calls++ === 0 ? old.promise : undefined;
  act(() => window.dispatchEvent(new Event('focus')));
  identity = b; event(); await screen.findByText('b@example.com');
  await act(async () => old.resolve(reply(a, 200, a.session_context)));
  expect(screen.getByText('b@example.com')).toBeVisible();
  expect(screen.queryByText(row.original_filename)).not.toBeInTheDocument();
});
it.each([401, 503])('removes cached private data when a focus check returns %s', async status => {
  const user = await loaded();
  await user.upload(screen.getByLabelText('Choose a document'), new File(['text'], 'private-selection.txt'));
  identity = null;
  override = path => path === '/auth/me' ? Promise.resolve(reply({}, status)) : undefined;
  act(() => window.dispatchEvent(new Event('focus')));
  if (status === 401) await screen.findByRole('heading', { name: 'Log in' });
  else await screen.findByRole('button', { name: 'Check session' });
  expect(screen.queryByText(row.original_filename)).not.toBeInTheDocument();
  expect(screen.queryByText('private-selection.txt')).not.toBeInTheDocument();
  expect(document.getElementById('document-file')).toBeNull();
});
