import { StrictMode } from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { MAX_BYTES, reconcile, type DocumentMetadata } from './api';

const first: DocumentMetadata = { id: 'c2158240-1860-4416-8f9d-f1fe537ce001', original_filename: 'same.txt', byte_size: 4, created_at: '2026-10-13T09:10:00Z' };
const second = { ...first, id: 'c2158240-1860-4416-8f9d-f1fe537ce002', created_at: '2026-10-13T09:11:00Z' };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock); });
afterEach(() => vi.unstubAllGlobals());
async function loaded(rows: DocumentMetadata[] = []) {
  fetchMock.mockResolvedValueOnce(response(rows));
  const user = userEvent.setup({ applyAccept: false });
  render(<App />);
  await screen.findByText(`${rows.length} ${rows.length === 1 ? 'document' : 'documents'}`);
  return user;
}
async function select(user: ReturnType<typeof userEvent.setup>, file = new File(['text'], 'same.txt', { type: 'text/plain' })) {
  await user.upload(screen.getByLabelText('Choose a text document'), file);
}

describe('library and upload behaviour (mocked HTTP)', () => {
  it('distinguishes initial loading from an empty successful list', async () => {
    const pending = deferred<Response>(); fetchMock.mockReturnValue(pending.promise);
    render(<App />);
    expect(screen.getByText('Gathering your library.')).toBeInTheDocument();
    expect(screen.queryByText('Start with your first source.')).not.toBeInTheDocument();
    await act(async () => pending.resolve(response([])));
    expect(await screen.findByText('Start with your first source.')).toBeInTheDocument();
  });
  it('keeps duplicate filenames as separate records, ordered by timestamp then ID', async () => {
    await loaded([second, first]);
    expect(screen.getAllByText('same.txt')).toHaveLength(2);
    expect([...document.querySelectorAll('dd')].filter(e => e.textContent?.startsWith('c215')).map(e => e.textContent)).toEqual([first.id, second.id]);
  });
  it('renders filenames as text, including HTML-like text and long names', async () => {
    await loaded([{ ...first, original_filename: '<img src=x onerror=alert(1)>' + 'a'.repeat(300) + '.txt' }]);
    expect(document.querySelector('.filename img')).toBeNull();
    expect(document.querySelector('.filename')?.textContent).toBe('<img src=x onerror=alert(1)>' + 'a'.repeat(300) + '.txt');
  });
  it.each([
    [new File([], 'empty.txt'), 'Choose a non-empty text file.'],
    [new File(['a'], 'wrong.pdf'), 'Choose a .txt file.'],
    [new File([new Uint8Array(MAX_BYTES + 1)], 'large.txt'), 'Choose a file no larger than 1 MiB (1,048,576 bytes).'],
  ])('rejects invalid local selection without POST', async (file, message) => {
    const user = await loaded(); await select(user, file);
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Upload document' })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it.each(['same.TXT', 'boundary.txt'])('submits multipart without a Content-Type header and accepts valid 201: %s', async name => {
    const user = await loaded();
    const file = new File([name === 'boundary.txt' ? new Uint8Array(MAX_BYTES).fill(120) : 'text'], name);
    const saved = { ...first, original_filename: name, byte_size: file.size };
    fetchMock.mockResolvedValueOnce(response(saved, 201)); await select(user, file);
    await user.click(screen.getByRole('button', { name: 'Upload document' }));
    expect(await screen.findByText('Document saved')).toBeInTheDocument();
    expect(screen.getByText('1 document')).toBeInTheDocument();
    expect(screen.getByText(`“${name}” is now in your library.`)).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toBe('/documents'); expect(init.method).toBe('POST'); expect(init.headers).toBeUndefined();
    expect(init.body.get('file').name).toBe(name);
  });
  it('prevents duplicate submissions while an upload is pending', async () => {
    const user = await loaded(); const pending = deferred<Response>(); fetchMock.mockReturnValueOnce(pending.promise);
    await select(user); const upload = screen.getByRole('button', { name: 'Upload document' });
    await user.dblClick(upload); expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: 'Uploading…' })).toBeDisabled();
    await act(async () => pending.resolve(response(first, 201)));
  });
  it('preserves confirmed metadata and acknowledgement after a failed refresh', async () => {
    const user = await loaded(); fetchMock.mockResolvedValueOnce(response(first, 201)); await select(user);
    await user.click(screen.getByRole('button', { name: 'Upload document' })); await screen.findByText('Document saved');
    fetchMock.mockRejectedValueOnce(new Error('private internal failure'));
    await user.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(await screen.findByText('Couldn’t refresh')).toBeInTheDocument();
    expect(screen.getByText('Document saved')).toBeInTheDocument(); expect(screen.getByText('1 document')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('private internal');
  });
  it('preserves rows and expanded Details during refresh and failure', async () => {
    const user = await loaded([first]); const details = document.querySelector('details')!;
    await user.click(document.querySelector('summary')!); expect(details.open).toBe(true);
    const pending = deferred<Response>(); fetchMock.mockReturnValueOnce(pending.promise);
    await user.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(screen.getByText('same.txt')).toBeInTheDocument(); expect(details.open).toBe(true);
    await act(async () => pending.resolve(response({}, 503)));
    expect(await screen.findByText('Couldn’t refresh')).toBeInTheDocument(); expect(details.open).toBe(true);
  });
  it('merges a stale list snapshot without hiding an upload committed while it was pending', async () => {
    const user = await loaded([first]); const stale = deferred<Response>(); fetchMock.mockReturnValueOnce(stale.promise);
    await user.click(screen.getByRole('button', { name: 'Refresh' }));
    fetchMock.mockResolvedValueOnce(response(second, 201)); await select(user);
    await user.click(screen.getByRole('button', { name: 'Upload document' })); await screen.findByText('Document saved');
    await act(async () => stale.resolve(response([first])));
    expect(screen.getByText('2 documents')).toBeInTheDocument();
    expect(document.querySelectorAll('details')).toHaveLength(2);
    fetchMock.mockResolvedValueOnce(response([first, second])); await user.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Refresh' })).toHaveAttribute('aria-disabled', 'false'));
    expect(document.querySelectorAll('details')).toHaveLength(2);
  });
  it.each([400, 413, 422])('handles definitive HTTP %s without exposing raw details', async status => {
    const user = await loaded(); fetchMock.mockResolvedValueOnce(response({ detail: 'secret SQL internals' }, status));
    await select(user); await user.click(screen.getByRole('button', { name: 'Upload document' }));
    expect(await screen.findByText('File not saved')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('secret SQL'); expect(screen.queryByText('Document saved')).not.toBeInTheDocument();
  });
  it.each(['network', '503', '500', '200', 'malformed', 'mismatch'])('treats %s as uncertain; refresh before explicit retry, never automatic', async failure => {
    const user = await loaded();
    if (failure === 'network') fetchMock.mockRejectedValueOnce(new Error('private network error'));
    else fetchMock.mockResolvedValueOnce(failure === 'malformed' ? response({}, 201) : failure === 'mismatch' ? response({ ...first, byte_size: 6 }, 201) : response(first, Number(failure)));
    await select(user); await user.click(screen.getByRole('button', { name: 'Upload document' }));
    expect(await screen.findByText('Save not confirmed')).toBeInTheDocument();
    expect(screen.queryByText('Document saved')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Upload document' })).toBeDisabled();
    const calls = fetchMock.mock.calls.length;
    fetchMock.mockResolvedValueOnce(response([first])); await user.click(screen.getByRole('button', { name: 'Refresh library' }));
    expect(await screen.findByText('Review before retrying')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(calls + 1);
    expect(screen.getByRole('button', { name: 'Upload again' })).toBeEnabled();
  });
  it.each([{}, [{...first, id: 'bad'}], [{...first, byte_size: -1}], [{...first, created_at: 'bad'}], [first, first]])('does not mistake an invalid list response for empty', async body => {
    fetchMock.mockResolvedValueOnce(response(body)); render(<App />);
    expect(await screen.findByText('Couldn’t load your library')).toBeInTheDocument();
    expect(screen.queryByText('Start with your first source.')).not.toBeInTheDocument();
  });
  it('offers keyboard access to native picker, submit, refresh, and disclosures', async () => {
    const user = await loaded([first]); await select(user);
    const choose = screen.getByRole('button', { name: 'Choose a file' }); choose.focus(); await user.tab();
    expect(screen.getByRole('button', { name: 'Upload document' })).toHaveFocus(); await user.tab();
    expect(screen.getByRole('button', { name: 'Refresh' })).toHaveFocus(); await user.tab();
    expect(document.querySelector('summary')).toHaveFocus();
  });
});
it('preserves PostgreSQL microsecond ordering and ID tie-breaks', () => {
  const a = {...first, created_at: '2026-10-13T09:10:00.000002Z'};
  const b = {...second, created_at: '2026-10-13T09:10:00.000001Z'};
  expect(reconcile([a, b]).map(d => d.id)).toEqual([b.id, a.id]);
  expect(reconcile([second, {...first, created_at: second.created_at}]).map(d => d.id)).toEqual([first.id, second.id]);
});

it('ignores an older initial response after StrictMode starts a newer request', async () => {
  const old = deferred<Response>();
  fetchMock.mockReturnValueOnce(old.promise).mockResolvedValueOnce(response([second]));
  render(<StrictMode><App /></StrictMode>);
  await screen.findByText('1 document');
  await act(async () => old.resolve(response([])));
  expect(screen.getByText('1 document')).toBeInTheDocument();
});
it('keeps an uncertain save blocked if the recommended refresh also fails', async () => {
  const user = await loaded(); await select(user);
  fetchMock.mockRejectedValueOnce(new Error('lost'));
  await user.click(screen.getByRole('button', {name: 'Upload document'}));
  await screen.findByText('Save not confirmed');
  fetchMock.mockResolvedValueOnce(response({},503));
  await user.click(screen.getByRole('button', {name: 'Refresh library'}));
  await screen.findByText('Couldn’t refresh');
  expect(screen.getByRole('button', {name: 'Upload document'})).toBeDisabled();
  expect(screen.getByText('Save not confirmed')).toBeInTheDocument();
});
it('does not confirm a 201 with a non-JSON body', async () => {
  const user = await loaded(); await select(user);
  fetchMock.mockResolvedValueOnce(new Response('<html>internal</html>',{status:201}));
  await user.click(screen.getByRole('button', {name:'Upload document'}));
  await screen.findByText('Save not confirmed');
  expect(document.body.textContent).not.toContain('<html>');
});
it('allows deliberate reselection of the same filename after a confirmed upload', async () => {
  const user = await loaded(); await select(user);
  fetchMock.mockResolvedValueOnce(response(first,201));
  await user.click(screen.getByRole('button', {name:'Upload document'}));
  await screen.findByText('Document saved'); await select(user);
  expect(screen.getByRole('button', {name:'Upload document'})).toBeEnabled();
});
