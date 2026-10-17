import type { LibrarySession } from "./useAuth";

export const MAX_BYTES = 1_048_576;
export interface DocumentMetadata {
  id: string;
  original_filename: string;
  byte_size: number;
  created_at: string;
}

export class ApiError extends Error {
  constructor(public readonly kind: 'rejected' | 'uncertain' | 'unavailable' | 'session', message: string) {
    super(message);
  }
}

export function fileProblem(file: File): string | null {
  if (!file.name.toLowerCase().endsWith('.txt')) return 'Choose a .txt file.';
  if (file.size === 0) return 'Choose a non-empty text file.';
  if (file.size > MAX_BYTES) return 'Choose a file no larger than 1 MiB (1,048,576 bytes).';
  return null;
}

function metadata(value: unknown): DocumentMetadata {
  if (!value || typeof value !== 'object') throw new Error('Invalid metadata');
  const d = value as Record<string, unknown>;
  if (typeof d.id !== 'string' || !/^[\da-f]{8}(-[\da-f]{4}){3}-[\da-f]{12}$/i.test(d.id) ||
      typeof d.original_filename !== 'string' || !d.original_filename.toLowerCase().endsWith('.txt') ||
      d.original_filename.includes('\0') || typeof d.byte_size !== 'number' ||
      !Number.isSafeInteger(d.byte_size) || d.byte_size < 1 || d.byte_size > MAX_BYTES ||
      typeof d.created_at !== 'string' ||
      !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(d.created_at) ||
      !Number.isFinite(Date.parse(d.created_at))) throw new Error('Invalid metadata');
  // Copy only public metadata. Never forward an unexpected response field to UI state.
  return { id: d.id.toLowerCase(), original_filename: d.original_filename,
    byte_size: d.byte_size, created_at: d.created_at };
}

export async function listDocuments(session: LibrarySession): Promise<DocumentMetadata[]> {
  try {
    const response = await fetch('/documents', { signal: AbortSignal.any([session.signal, AbortSignal.timeout(20_000)]), cache: 'no-store', credentials: 'same-origin' });
    checkContext(response, session);
    if (response.status !== 200) throw new Error('List failed');
    const value: unknown = await response.json();
    if (!Array.isArray(value)) throw new Error('Invalid list');
    const documents = value.map(metadata);
    if (new Set(documents.map(d => d.id)).size !== documents.length) throw new Error('Duplicate ID');
    return documents;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError('unavailable', 'Your library could not be refreshed. Please try again.');
  }
}

export async function uploadDocument(file: File, session: LibrarySession): Promise<DocumentMetadata> {
  const form = new FormData();
  form.append('file', file);
  try {
    const response = await fetch('/documents', {
      method: 'POST', body: form, credentials: 'same-origin', headers: { 'X-CSRF-Token': session.csrf },
      signal: AbortSignal.any([session.signal, AbortSignal.timeout(20_000)]),
    });
    checkContext(response, session);
    if (response.status === 403) throw new ApiError('session', 'Your session verification changed. Check the session and manually choose the file again.');
    if (response.status === 429) throw new ApiError('rejected', 'Too many requests. Wait before trying again.');
    // These validation responses definitively reject this API's upload. Do not
    // display arbitrary server details: they may contain filenames or internals.
    const rejection: Record<number, string> = {
      400: 'File not saved. Use non-empty UTF-8 .txt text without null characters and a valid filename.',
      413: 'File not saved. The maximum size is 1 MiB (1,048,576 bytes).',
      422: 'File not saved. Choose one text file and try again.',
    };
    if (rejection[response.status]) throw new ApiError('rejected', rejection[response.status]);
    if (response.status !== 201) throw new Error('Unconfirmed save');
    const saved = metadata(await response.json());
    if (saved.original_filename !== file.name || saved.byte_size !== file.size) throw new Error('Mismatched save');
    return saved;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError('uncertain', 'Saving could not be confirmed. The document may have been saved. Refresh your library before retrying.');
  }
}

function timestampTail(date: string): string {
  // PostgreSQL timestamps can distinguish microseconds; Date.parse only keeps
  // milliseconds. Preserve the remaining precision when merging uploads.
  return (date.match(/\.(\d+)(?:Z|[+-]\d\d:\d\d)$/)?.[1] ?? '').padEnd(6, '0').slice(3);
}
export function reconcile(...groups: DocumentMetadata[][]): DocumentMetadata[] {
  const unique = new Map(groups.flat().map(d => [d.id, d]));
  return [...unique.values()].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at) ||
    timestampTail(a.created_at).localeCompare(timestampTail(b.created_at)) || a.id.localeCompare(b.id));
}

function checkContext(response: Response, session: LibrarySession) {
  if (response.status === 401) throw new ApiError('session', 'Your session ended. Please log in again.');
  // 503 can occur before authentication/context lookup; treat as unavailable or
  // uncertain, never accept data from it. Successful and definite responses must match.
  if ((response.headers.has('X-Session-Context') || response.status < 500) && response.headers.get('X-Session-Context') !== session.context) {
    throw new ApiError('session', 'Your session changed. Checking it before showing documents.');
  }
}
