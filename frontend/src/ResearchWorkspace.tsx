import { useEffect, useRef, useState } from 'react';
import { ApiError, type DocumentMetadata } from './api';
import { askQuestion, inspectPassage, researchStatus, type Citation, type Passage, type ResearchAnswer, type ResearchStatus } from './researchApi';
import type { LibrarySession } from './useAuth';

export function ResearchWorkspace({ session, documents }: { session: LibrarySession; documents: DocumentMetadata[] }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [configuration, setConfiguration] = useState<ResearchStatus | null>(null);
  const [configError, setConfigError] = useState('');
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<ResearchAnswer | null>(null);
  const [error, setError] = useState('');
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const [context, setContext] = useState<Passage | null>(null);
  const [contextPending, setContextPending] = useState(false);
  const [contextError, setContextError] = useState('');
  const epoch = useRef(0), contextEpoch = useRef(0), configEpoch = useRef(0);
  const alive = useRef(false), inFlight = useRef(false);
  const controller = useRef(new AbortController());
  const contextController = useRef(new AbortController());
  const inspector = useRef<HTMLElement>(null), returnButton = useRef<HTMLButtonElement | null>(null);
  function valid(generation: number) { return alive.current && session.isCurrent() && epoch.current === generation; }
  function clear() {
    epoch.current++; contextEpoch.current++;
    controller.current.abort(); controller.current = new AbortController();
    contextController.current.abort(); contextController.current = new AbortController();
    inFlight.current = false; setPending(false); setResult(null); setError('');
    setActiveCitation(null); setContext(null); setContextError(''); setContextPending(false);
  }
  function safeFailure(failure: unknown, fallback: string) {
    if (failure instanceof ApiError && failure.kind === 'session') { session.invalidate(failure.message); return ''; }
    return failure instanceof ApiError ? failure.message : fallback;
  }
  async function checkConfiguration() {
    const check = ++configEpoch.current;
    setConfigError('');
    try {
      const status = await researchStatus(session, session.signal);
      if (alive.current && session.isCurrent() && check === configEpoch.current) setConfiguration(status);
    } catch (failure) {
      if (alive.current && session.isCurrent() && check === configEpoch.current) setConfigError(safeFailure(failure, 'The answering service could not be checked. Local passage search is available.'));
    }
  }
  useEffect(() => {
    alive.current = true; void checkConfiguration();
    return () => { alive.current = false; epoch.current++; contextEpoch.current++; configEpoch.current++; controller.current.abort(); contextController.current.abort(); };
  }, []);
  useEffect(() => {
    if (selected.some(id => !documents.some(d => d.id === id))) {
      clear(); setSelected(current => current.filter(id => documents.some(d => d.id === id)));
    }
  }, [documents]);
  function toggle(id: string) {
    clear();
    setSelected(current => current.includes(id) ? current.filter(value => value !== id) : current.length < 5 ? [...current, id] : current);
  }
  async function submit(mode: 'search' | 'questions') {
    if (inFlight.current || !question.trim() || Array.from(question).length > 1000 || !selected.length || (mode === 'questions' && !configuration?.enabled)) return;
    clear(); const generation = epoch.current;
    inFlight.current = true; setPending(true);
    try {
      const next = await askQuestion(question, selected, mode, session, controller.current.signal);
      if (valid(generation)) setResult(next);
    } catch (failure) {
      if (valid(generation)) setError(safeFailure(failure, 'The request could not be completed. Please try again deliberately.'));
    } finally { if (valid(generation)) { inFlight.current = false; setPending(false); } }
  }
  async function inspect(citation: Citation, button: HTMLButtonElement) {
    const generation = epoch.current, attempt = ++contextEpoch.current;
    contextController.current.abort(); contextController.current = new AbortController();
    returnButton.current = button;
    setActiveCitation(citation); setContext(null); setContextError(''); setContextPending(true);
    try {
      const passage = await inspectPassage(citation, session, contextController.current.signal);
      if (valid(generation) && attempt === contextEpoch.current) setContext(passage);
    } catch (failure) {
      if (valid(generation) && attempt === contextEpoch.current) setContextError(safeFailure(failure, 'The passage could not be loaded.'));
    } finally { if (valid(generation) && attempt === contextEpoch.current) setContextPending(false); }
  }
  useEffect(() => { if (activeCitation) inspector.current?.focus(); }, [activeCitation]);
  function closeInspector() { contextEpoch.current++; contextController.current.abort(); setActiveCitation(null); setContext(null); setContextError(''); setContextPending(false); returnButton.current?.focus(); }
  function citationButton(c: Citation) {
    return <button key={c.id} className="button citation-button" type="button" onClick={e => void inspect(c, e.currentTarget)} aria-controls="source-inspector">{c.id} · {c.original_filename} · {c.page_number ? `PDF page ${c.page_number}` : 'Text passage'}</button>;
  }
  const invalid = !question.trim() || Array.from(question).length > 1000 || !selected.length;
  return <section className="research-workspace" aria-labelledby="research-heading">
    <header className="research-header"><p className="eyebrow">From sources to understanding</p><h2 id="research-heading">Ask your sources.</h2><p>Choose the material to investigate, then inspect the evidence behind each claim.</p></header>
    <form aria-busy={pending} onSubmit={e => { e.preventDefault(); void submit('search'); }}>
      <fieldset className="source-selection"><legend>1. Select sources <span>({selected.length} of 5)</span></legend>
        <div className="source-options">{documents.map((document, index) => <label className="source-choice" key={document.id}>
          <input type="checkbox" checked={selected.includes(document.id)} disabled={!selected.includes(document.id) && selected.length === 5} onChange={() => toggle(document.id)} />
          <span><strong>{document.original_filename}</strong><small>Source {index + 1} · {document.source_format.toUpperCase()}{document.page_count ? ` · ${document.page_count} pages` : ''}</small></span>
        </label>)}</div>
      </fieldset>
      <label className="question-label" htmlFor="research-question">2. Your research question</label>
      <textarea id="research-question" rows={3} maxLength={2000} value={question} onChange={e => { clear(); setQuestion(Array.from(e.target.value).slice(0, 1000).join('')); }} aria-describedby="question-help research-disclosure" placeholder="What do these sources say about your question?" />
      <p id="question-help" className="field-help">Select up to five sources · {Array.from(question).length}/1,000 characters. Local search matches words, so use terms from your sources.</p>
      <p id="research-disclosure" className="research-disclosure">{configuration?.enabled ? 'Ask AI sends your question and up to six matching passages to Groq. Passage text may contain private information. Use a free-plan account; quota limits may interrupt requests. Local passage search sends nothing externally.' : 'Local passage search keeps source text on this machine. AI answering is disabled until a private Groq key is configured.'}</p>
      {configError && <div className="message error" role="alert"><p>{configError}</p><button className="button" type="button" onClick={() => void checkConfiguration()}>Check answering service</button></div>}
      <div className="research-actions"><button className="button" type="submit" disabled={invalid || pending}>Find passages locally</button><button className="button primary" type="button" disabled={invalid || pending || !configuration?.enabled} onClick={() => void submit('questions')}>Ask AI</button></div>
    </form>
    {pending && <div className="message info" role="status"><strong>Checking your sources</strong><p>Please wait. If you change the question or sources, this result will be discarded; an AI request may still use quota.</p></div>}
    {error && <div className="message error" role="alert"><strong>Research could not be completed</strong><p>{error}</p></div>}
    {result && <section className="research-results" aria-label="Research result" aria-live="polite">
      <p className="eyebrow">Your question</p><h3>{result.question}</h3>
      <h4>{result.status === 'answered' ? 'Answer with evidence' : result.status === 'evidence_only' ? 'Matching passages' : result.status === 'no_evidence' ? 'No matching passages found' : 'The evidence is insufficient for an answer'}</h4>
      {['no_evidence', 'insufficient_evidence'].includes(result.status) && <p>Try a more specific question or different sources. This does not establish that the documents contain no relevant evidence.</p>}
      {result.claims.map((claim, index) => <div className="answer-claim" key={index}><p>{claim.text}</p><div className="citation-links">{claim.citation_ids.map(id => citationButton(result.citations.find(c => c.id === id)!))}</div></div>)}
      <div className="evidence-list"><h4>Supporting passages</h4>{result.citations.map(c => <article key={c.id}><blockquote>{c.quote}</blockquote>{citationButton(c)}</article>)}</div>
      <div className="research-warnings">{result.warnings.map((warning, index) => <p key={index}>{warning}</p>)}</div>
    </section>}
    {activeCitation && <section ref={inspector} className="source-inspector" id="source-inspector" tabIndex={-1} aria-labelledby="inspector-heading" aria-busy={contextPending}>
      <header><div><p className="eyebrow">Inspect the source</p><h3 id="inspector-heading">{activeCitation.original_filename}</h3><p>{activeCitation.page_number ? `Physical PDF page ${activeCitation.page_number}` : 'Text source · no page numbering'}</p></div><button type="button" className="button" onClick={closeInspector}>Return to citation</button></header>
      {contextPending && <p role="status">Loading the saved passage…</p>}
      {contextError && <p className="message error" role="alert">{contextError}</p>}
      {context && <><p className="source-context">{context.before}<mark>{context.quote}</mark>{context.after}</p><p className="field-help">Highlighted text is the exact saved passage. Surrounding context is limited; PDF layout and images are not reproduced.</p></>}
    </section>}
  </section>;
}
