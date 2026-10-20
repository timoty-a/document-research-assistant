import { ApiError } from './api';
import { uuid } from './authApi';
import type { LibrarySession } from './useAuth';

export interface Citation {
  id: string; document_id: string; original_filename: string; source_format: 'txt' | 'pdf';
  page_number: number | null; extraction_version: string; start: number; end: number; quote: string;
}
export interface ResearchAnswer {
  status: 'answered' | 'insufficient_evidence' | 'no_evidence' | 'evidence_only';
  question: string; claims: { text: string; citation_ids: string[] }[]; citations: Citation[]; warnings: string[];
}
export interface Passage extends Omit<Citation, 'id'> { before: string; after: string }
export interface ResearchStatus { enabled: boolean; provider: string | null; model: string | null }

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid response');
  return value as Record<string, unknown>;
}
function text(value: unknown, max: number): value is string { return typeof value === 'string' && value.length <= max && !value.includes('\0'); }
function citation(value: unknown): Citation {
  const c = object(value);
  if (!text(c.id, 3) || !/^E[1-6]$/.test(c.id) || !uuid(c.document_id) || !text(c.original_filename, 2_097_152) ||
      !c.original_filename || !['txt', 'pdf'].includes(c.source_format as string) || !text(c.extraction_version, 100) || !c.extraction_version ||
      !Number.isInteger(c.start) || !Number.isInteger(c.end) || (c.start as number) < 0 || (c.end as number) > 1_048_576 ||
      (c.end as number) <= (c.start as number) || !text(c.quote, 2000) || Array.from(c.quote).length !== (c.end as number) - (c.start as number) ||
      Array.from(c.quote).length > 1000 ||
      (c.source_format === 'txt' ? c.page_number !== null : !Number.isInteger(c.page_number) || (c.page_number as number) < 1 || (c.page_number as number) > 100)) throw new Error('Invalid citation');
  return { id: c.id, document_id: c.document_id.toLowerCase(), original_filename: c.original_filename,
    source_format: c.source_format as 'txt' | 'pdf', page_number: c.page_number as number | null,
    extraction_version: c.extraction_version, start: c.start as number, end: c.end as number, quote: c.quote };
}
function answer(value: unknown, question: string, selected: string[]): ResearchAnswer {
  const a = object(value);
  if (!['answered', 'insufficient_evidence', 'no_evidence', 'evidence_only'].includes(a.status as string) || a.question !== question ||
      !Array.isArray(a.citations) || a.citations.length > 6 || !Array.isArray(a.claims) || a.claims.length > 5 ||
      !Array.isArray(a.warnings) || a.warnings.length > 8 || !a.warnings.every(w => text(w, 1000))) throw new Error('Invalid answer');
  const citations = a.citations.map(citation);
  const ids = new Set(citations.map(c => c.id));
  if (ids.size !== citations.length || citations.some(c => !selected.includes(c.document_id))) throw new Error('Invalid source scope');
  const claims = a.claims.map(value => {
    const c = object(value);
    if (!text(c.text, 1600) || !c.text.trim() || !Array.isArray(c.citation_ids) || !c.citation_ids.length || c.citation_ids.length > 6 ||
        new Set(c.citation_ids).size !== c.citation_ids.length || c.citation_ids.some(id => typeof id !== 'string' || !ids.has(id))) throw new Error('Invalid claim');
    return { text: c.text, citation_ids: c.citation_ids as string[] };
  });
  if ((a.status === 'answered') !== (claims.length > 0) || (a.status === 'no_evidence' && citations.length > 0)) throw new Error('Invalid answer status');
  return { status: a.status as ResearchAnswer['status'], question, claims, citations, warnings: a.warnings as string[] };
}
async function request(path: string, init: RequestInit, session: LibrarySession, signal: AbortSignal): Promise<Response> {
  try {
    const response = await fetch(path, { ...init, credentials: 'same-origin', cache: 'no-store',
      signal: AbortSignal.any([session.signal, signal, AbortSignal.timeout(40_000)]) });
    if (response.status === 401) throw new ApiError('session', 'Your session ended. Please log in again.');
    if ((response.headers.has('X-Session-Context') || response.status < 500) && response.headers.get('X-Session-Context') !== session.context) throw new ApiError('session', 'Your session changed. Checking it before showing sources.');
    if (response.status === 403) throw new ApiError('session', 'Your session verification changed. Check the session before submitting again.');
    if (response.status === 429) throw new ApiError('rejected', 'Research limits were reached. Wait before trying again; no automatic retry was made.');
    if (response.status === 404 || response.status === 409) throw new ApiError('rejected', 'A selected source or passage is no longer available. Refresh your library and ask again.');
    if ([400, 413, 415, 422].includes(response.status)) throw new ApiError('rejected', 'Use a question of 1–1,000 characters and select one to five sources. A smaller selection may help.');
    if (response.status !== 200) throw new Error('Unavailable');
    return response;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError('unavailable', 'The request could not be completed. No automatic retry was made. AI requests may still use your provider quota.');
  }
}
export async function researchStatus(session: LibrarySession, signal: AbortSignal): Promise<ResearchStatus> {
  const response = await request('/research/status', {}, session, signal);
  const value = object(await response.json());
  if (typeof value.enabled !== 'boolean' || (value.enabled ? value.provider !== 'Groq' || value.model !== 'openai/gpt-oss-120b' : value.provider !== null || value.model !== null)) throw new ApiError('unavailable', 'The answering service could not be checked. Local passage search is still available.');
  return { enabled: value.enabled, provider: value.provider as string | null, model: value.model as string | null };
}
export async function askQuestion(question: string, selected: string[], mode: 'search' | 'questions', session: LibrarySession, signal: AbortSignal): Promise<ResearchAnswer> {
  try {
    const response = await request(`/research/${mode}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf },
      body: JSON.stringify({ question, document_ids: selected }) }, session, signal);
    return answer(await response.json(), question, selected);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError('unavailable', 'The response could not be verified. No automatic retry was made.');
  }
}
export async function inspectPassage(c: Citation, session: LibrarySession, signal: AbortSignal): Promise<Passage> {
  const query = new URLSearchParams({ start: String(c.start), end: String(c.end), version: c.extraction_version, page: String(c.page_number ?? 0) });
  try {
    const response = await request(`/documents/${encodeURIComponent(c.document_id)}/passage?${query}`, {}, session, signal);
    const p = object(await response.json());
    const verified = citation({ ...p, id: c.id });
    if (verified.document_id !== c.document_id || verified.extraction_version !== c.extraction_version || verified.quote !== c.quote ||
        verified.start !== c.start || verified.end !== c.end || verified.page_number !== c.page_number || verified.source_format !== c.source_format ||
        verified.original_filename !== c.original_filename || !text(p.before, 400) || !text(p.after, 400)) throw new Error('Invalid context');
    return { ...verified, before: p.before, after: p.after };
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError('unavailable', 'The source passage could not be verified. Try inspecting it again.');
  }
}
