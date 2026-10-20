import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from './App';
import { ResearchWorkspace } from './ResearchWorkspace';
import type { DocumentMetadata } from './api';
import type { LibrarySession } from './useAuth';

const context = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const doc: DocumentMetadata = { id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', original_filename: 'same.pdf', byte_size: 100,
  created_at: '2026-10-18T10:00:00Z', source_format: 'pdf', page_count: 3, textless_pages: [2] };
const duplicate = { ...doc, id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd' };
const quotation = '😀 Solar costs fell.';
const citation = { id: 'E1', document_id: doc.id, original_filename: doc.original_filename, source_format: 'pdf',
  page_number: 3, extraction_version: 'synthetic:plain-v1', start: 0, end: Array.from(quotation).length, quote: quotation };
const answer = { status: 'answered', question: 'solar costs?', claims: [{ text: 'Costs fell in the source.', citation_ids: ['E1'] }], citations: [citation], warnings: ['Check each claim against the evidence.'] };
const passage = { ...citation, before: '', after: ' More context.' };
const reply = (body: unknown, status = 200, token = context) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', 'X-Session-Context': token } });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
let fetchMock: ReturnType<typeof vi.fn<(path: string, init?: any) => Promise<Response>>>;
let invalidate: ReturnType<typeof vi.fn<(message: string) => void>>, current: boolean;
let session: LibrarySession;
beforeEach(() => {
  current = true; invalidate = vi.fn();
  session = { context, csrf: 'synthetic-csrf', signal: new AbortController().signal, isCurrent: () => current, invalidate };
  fetchMock = vi.fn((path: string) => {
    if (path === '/research/status') return Promise.resolve(reply({ enabled: true, provider: 'Groq', model: 'openai/gpt-oss-120b' }));
    if (path.startsWith('/documents/')) return Promise.resolve(reply(passage));
    return Promise.resolve(reply(answer));
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());
async function ready(documents = [doc]) {
  render(<ResearchWorkspace session={session} documents={documents} />);
  const user = userEvent.setup();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Ask AI' })).toBeInTheDocument());
  await user.click(screen.getAllByRole('checkbox')[0]);
  await user.type(screen.getByLabelText('2. Your research question'), 'solar costs?');
  return user;
}

it('requires explicit source selection, distinguishes duplicate names and bounds the selection', async () => {
  const docs = [doc, duplicate, ...[1, 2, 3, 4].map((n) => ({ ...doc, id: `00000000-0000-4000-8000-00000000000${n}` }))];
  render(<ResearchWorkspace session={session} documents={docs} />);
  const user = userEvent.setup();
  expect(screen.getAllByRole('checkbox')).toHaveLength(6);
  expect(screen.getByText('Source 1 · PDF · 3 pages')).toBeInTheDocument();
  expect(screen.getByText('Source 2 · PDF · 3 pages')).toBeInTheDocument();
  for (const box of screen.getAllByRole('checkbox').slice(0, 5)) await user.click(box);
  expect(screen.getAllByRole('checkbox')[5]).toBeDisabled();
  expect(screen.getByText('(5 of 5)')).toBeInTheDocument();
});
it('submits explicit JSON and CSRF, renders claims and supports keyboard citation inspection', async () => {
  const user = await ready();
  await user.click(screen.getByRole('button', { name: 'Ask AI' }));
  expect(await screen.findByText('Costs fell in the source.')).toBeInTheDocument();
  const call = fetchMock.mock.calls.find(([path]) => path === '/research/questions')!;
  expect(JSON.parse(call[1].body)).toEqual({ question: 'solar costs?', document_ids: [doc.id] });
  expect(call[1].headers).toEqual({ 'Content-Type': 'application/json', 'X-CSRF-Token': 'synthetic-csrf' });
  const button = screen.getAllByRole('button', { name: 'E1 · same.pdf · PDF page 3' })[0];
  button.focus(); await user.keyboard('{Enter}');
  expect(await screen.findByText('More context.', { exact: false })).toBeInTheDocument();
  expect(document.querySelector('mark')?.textContent).toBe(quotation);
  expect(document.getElementById('source-inspector')).toHaveFocus();
  await user.click(screen.getByRole('button', { name: 'Return to citation' }));
  expect(button).toHaveFocus(); expect(document.getElementById('source-inspector')).toBeNull();
});
it('offers local search with AI disabled and never calls the answer endpoint', async () => {
  fetchMock.mockImplementation((path: string) => Promise.resolve(reply(path === '/research/status' ? { enabled: false, provider: null, model: null } : { ...answer, status: 'evidence_only', claims: [] })));
  render(<ResearchWorkspace session={session} documents={[doc]} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole('checkbox')); await user.type(screen.getByLabelText('2. Your research question'), 'solar costs?');
  await user.click(screen.getByRole('button', { name: 'Find passages locally' }));
  expect(await screen.findByText('Matching passages')).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([path]) => path === '/research/questions')).toBe(false);
});
it('prevents duplicate requests while pending and does not replay failures', async () => {
  const user = await ready(); const pending = deferred<Response>(); fetchMock.mockReturnValueOnce(pending.promise);
  await user.dblClick(screen.getByRole('button', { name: 'Ask AI' }));
  expect(fetchMock.mock.calls.filter(([path]) => path === '/research/questions')).toHaveLength(1);
  expect(screen.getByRole('button', { name: 'Ask AI' })).toBeDisabled();
  await act(async () => pending.resolve(reply({ message: 'private raw details' }, 503)));
  expect(await screen.findByText('Research could not be completed')).toBeInTheDocument();
  expect(document.body.textContent).not.toContain('private raw details');
  expect(fetchMock.mock.calls.filter(([path]) => path === '/research/questions')).toHaveLength(1);
});
it.each(['selection', 'question', 'session'])('discards delayed answers after a %s change, including stale 401', async change => {
  const user = await ready([doc, duplicate]); const pending = deferred<Response>(); fetchMock.mockReturnValueOnce(pending.promise);
  await user.click(screen.getByRole('button', { name: 'Ask AI' }));
  if (change === 'selection') await user.click(screen.getAllByRole('checkbox')[1]);
  if (change === 'question') await user.type(screen.getByLabelText('2. Your research question'), ' more');
  if (change === 'session') current = false;
  await act(async () => pending.resolve(reply({}, 401)));
  expect(invalidate).not.toHaveBeenCalled(); expect(screen.queryByText('Costs fell in the source.')).not.toBeInTheDocument();
});
it('discards an old source context response after the question changes', async () => {
  const user = await ready(); await user.click(screen.getByRole('button', { name: 'Ask AI' }));
  await screen.findByText('Costs fell in the source.');
  const pending = deferred<Response>(); fetchMock.mockReturnValueOnce(pending.promise);
  await user.click(screen.getAllByRole('button', { name: 'E1 · same.pdf · PDF page 3' })[0]);
  await user.type(screen.getByLabelText('2. Your research question'), ' more');
  await act(async () => pending.resolve(reply(passage)));
  expect(document.querySelector('mark')).toBeNull(); expect(screen.queryByText('Costs fell in the source.')).not.toBeInTheDocument();
});
it.each([400, 403, 404, 409, 429, 503])('handles HTTP %s safely without replaying a question', async status => {
  const user = await ready(); fetchMock.mockResolvedValueOnce(reply({ detail: 'private internal details' }, status));
  await user.click(screen.getByRole('button', { name: 'Ask AI' }));
  if (status === 403) await waitFor(() => expect(invalidate).toHaveBeenCalled());
  else await screen.findByText('Research could not be completed');
  expect(document.body.textContent).not.toContain('private internal');
  expect(fetchMock.mock.calls.filter(([path]) => path === '/research/questions')).toHaveLength(1);
});
it.each([
  { ...answer, claims: [{ text: 'Unsupported', citation_ids: ['E99'] }] },
  { ...answer, citations: [{ ...citation, document_id: duplicate.id }] },
  { ...answer, citations: [{ ...citation, end: 1 }] },
  { ...answer, status: 'answered', claims: [] },
])('rejects malformed or out-of-selection answer evidence', async malformed => {
  const user = await ready(); fetchMock.mockResolvedValueOnce(reply(malformed));
  await user.click(screen.getByRole('button', { name: 'Ask AI' }));
  expect(await screen.findByText('Research could not be completed')).toBeInTheDocument();
  expect(screen.queryByText('Answer with evidence')).not.toBeInTheDocument();
});
it('renders model text as text, never HTML or executable links', async () => {
  const user = await ready();
  fetchMock.mockResolvedValueOnce(reply({ ...answer, claims: [{ text: '<img src=x onerror=alert(1)>', citation_ids: ['E1'] }] }));
  await user.click(screen.getByRole('button', { name: 'Ask AI' }));
  expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
  expect(document.querySelector('.research-results img')).toBeNull();
});
it.each(['no_evidence', 'insufficient_evidence'])('shows explicit %s rather than inventing an answer', async status => {
  const user = await ready(); fetchMock.mockResolvedValueOnce(reply({ ...answer, status, claims: [], citations: status === 'no_evidence' ? [] : [citation] }));
  await user.click(screen.getByRole('button', { name: 'Ask AI' }));
  expect(await screen.findByText(status === 'no_evidence' ? 'No matching passages found' : 'The evidence is insufficient for an answer')).toBeInTheDocument();
  expect(screen.queryByText('Costs fell in the source.')).not.toBeInTheDocument();
});
it('clears research selections, question, answers and context on an actual logout boundary', async () => {
  const identity = { user: { id: '11111111-1111-4111-8111-111111111111', email: 'synthetic@example.com' }, expires_at: '2030-01-01T12:00:00Z', session_context: context };
  let loggedIn = true;
  const old = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation((path: string, init?: RequestInit) => {
    if (path === '/auth/csrf') return Promise.resolve(reply({ csrf_token: 'synthetic_12345678901234567890123456' }));
    if (path === '/auth/me') return Promise.resolve(reply(loggedIn ? identity : {}, loggedIn ? 200 : 401));
    if (path === '/documents') return Promise.resolve(reply([doc]));
    if (path === '/auth/logout') { loggedIn = false; return Promise.resolve(new Response(null, { status: 204 })); }
    return old(path, init);
  });
  render(<App />); const user = userEvent.setup(); await screen.findByText(doc.original_filename);
  await user.click(screen.getByRole('button', { name: 'Start research' }));
  await user.click(screen.getByRole('checkbox')); await user.type(screen.getByLabelText('2. Your research question'), 'solar costs?');
  await user.click(screen.getByRole('button', { name: 'Ask AI' })); await screen.findByText('Costs fell in the source.');
  await user.click(screen.getByRole('button', { name: 'Log out' }));
  await screen.findByRole('heading', { name: 'Log in' });
  expect(document.body.textContent).not.toContain('Costs fell in the source.');
  expect(document.querySelector('textarea')).toBeNull(); expect(screen.queryByRole('checkbox')).toBeNull();
});
