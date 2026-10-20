import { useRef, useState, type ReactNode } from 'react';
import { ResearchWorkspace } from './ResearchWorkspace';
import { DocumentList, formatSize } from './DocumentList';
import { fileProblem } from './api';
import { AuthForm } from './AuthForm';
import { useAuth, type LibrarySession } from './useAuth';
import { useLibrary } from './useLibrary';

function Message({ title, children, kind = '', id }: { title: string; children: ReactNode; kind?: string; id?: string }) {
  return <section id={id} className={`message ${kind}`} role={kind === 'error' || kind === 'warning' ? 'alert' : 'status'}><strong>{title}</strong>{children}</section>;
}
export function AuthenticatedLibrary({ session }: { session: LibrarySession }) {
  const library = useLibrary(session);
  const [researchOpen, setResearchOpen] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const refreshButton = useRef<HTMLButtonElement>(null);
  const { documents, loading, listError, refreshed, file, uploadStatus, uploadMessage, newId } = library;
  const busy = uploadStatus === 'uploading';
  const uncertain = uploadStatus === 'uncertain';
  const initial = documents === null;
  const empty = documents?.length === 0;
  const uploadDisabled = !file || !!fileProblem(file) || busy || uncertain || uploadStatus === 'success';
  function openPicker() {
    if (picker.current) { picker.current.value = ''; picker.current.click(); }
  }
  function refreshFromMessage() { refreshButton.current?.focus(); void library.refresh(); }
  return <>
    <div className={empty ? "is-empty" : ""}>
      <main id="main">
        <header className="intro"><div><p className="eyebrow">A place for your sources</p><h1>Document library.</h1><p className="intro-copy">Keep the material behind your work together.</p></div></header>
        <form className="upload-section" aria-labelledby="upload-heading" aria-describedby={`upload-limits${uploadMessage ? ' upload-feedback' : ''}`} onSubmit={e => { e.preventDefault(); void library.upload(); }}>
          <div><h2 id="upload-heading">Add a document</h2><p className="upload-limits" id="upload-limits">UTF-8 TXT or text-based PDF · Up to 1 MiB per file</p></div>
          <div className="upload-controls">
            <input ref={picker} id="document-file" className="sr-only" type="file" accept=".txt,.pdf,text/plain,application/pdf" aria-label="Choose a document" aria-describedby="upload-limits selected-file" disabled={busy || uncertain} onClick={e => { e.currentTarget.value = ''; }} onChange={e => library.choose(e.currentTarget.files?.[0] ?? null)} />
            <div className="upload-actions"><button className="button" type="button" disabled={busy || uncertain} onClick={openPicker}>{uploadStatus === 'success' ? 'Choose another file' : 'Choose a file'}</button><button className="button primary" type="submit" disabled={uploadDisabled}>{busy ? 'Processing and saving…' : uploadStatus === 'success' ? 'Saved' : uploadStatus === 'retry-ready' ? 'Upload again' : 'Upload document'}</button></div>
            <p className="selected-file" id="selected-file" role="status">{file ? <><strong>{file.name}</strong><span className="file-size">{formatSize(file.size)}</span></> : 'No file selected'}</p>
          </div>
        </form>
        {uploadMessage && <div className="upload-message"><Message id="upload-feedback" title={uploadStatus === 'success' ? 'Document saved' : uncertain ? 'Save not confirmed' : uploadStatus === 'retry-ready' ? 'Review before retrying' : busy ? 'Saving your document' : 'File not saved'} kind={uncertain || uploadStatus === 'retry-ready' ? 'warning' : uploadStatus === 'rejected' ? 'error' : busy ? 'info' : ''}>
          <p>{uploadMessage}</p>{uncertain && <button className="button" type="button" disabled={loading} onClick={refreshFromMessage}>{loading ? 'Refreshing…' : 'Refresh library'}</button>}
        </Message></div>}
        <p className="upload-limits pdf-notice">PDFs: up to 100 pages. Images are not read; extracted text may have reading-order or OCR errors.</p>
        <section className="library" id="library" aria-labelledby="library-heading" tabIndex={-1}>
          <div className="library-header"><h2 id="library-heading">Your documents</h2><div className="library-tools"><p className="document-count">{documents ? `${documents.length} ${documents.length === 1 ? 'document' : 'documents'}` : loading ? 'Loading…' : 'Not loaded'}</p><button ref={refreshButton} className="button refresh" type="button" aria-disabled={loading || busy} onClick={() => { if (!loading && !busy) void library.refresh(); }}><svg aria-hidden="true" viewBox="0 0 20 20" fill="none"><path d="M16 7a6.5 6.5 0 1 0 .4 5M16 3v4h-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg><span id="refresh-label">{loading ? initial ? 'Loading…' : 'Refreshing…' : 'Refresh'}</span></button></div></div>
          <div className="library-message">
            {loading && <Message title={initial ? 'Loading your library' : 'Refreshing your library'} kind="info"><p>{initial ? 'Please wait while your documents are loaded.' : 'Your existing documents remain available while the list is updated.'}</p></Message>}
            {listError && <Message title={initial ? 'Couldn’t load your library' : 'Couldn’t refresh'} kind="error"><p>{initial ? 'Try again to see your saved documents.' : 'Showing your previously loaded documents. Please try again.'}</p><button className="button" type="button" onClick={refreshFromMessage}>Try refreshing again</button></Message>}
            {!loading && !listError && refreshed && <Message title="Library refreshed"><p>Your document list is up to date.</p></Message>}
          </div>
          {!!documents?.length && <DocumentList documents={documents} newId={newId} />}
          {initial && <div className="state-panel">{loading ? <><div className="skeleton" aria-hidden="true"><span /><span /><span /></div><h3>Gathering your library.</h3></> : <><h3>Your library couldn’t be loaded.</h3><p>A connection problem doesn’t mean your library is empty.</p></>}</div>}
          {empty && <div className="state-panel"><h3>Start with your first source.</h3><p>Add a document. Its filename, size and upload time will appear here.</p><button className="button" type="button" disabled={busy || uncertain} onClick={openPicker}>Choose a document file</button></div>}
          <p className="library-foot">TXT and text-based PDF · Times shown in WAT</p>
        </section>
        {researchOpen && documents?.length ? <ResearchWorkspace session={session} documents={documents} /> : <section className="research-intro" aria-labelledby="research-intro-heading"><div><p className="eyebrow">Work with the evidence</p><h2 id="research-intro-heading">Ask a question. Check the source.</h2><p>Choose documents, find relevant passages and inspect the support for an answer.</p></div><button className="button" type="button" disabled={!documents?.length} onClick={() => setResearchOpen(true)}>Start research</button></section>}
      </main>
    </div>
  </>;
}

export function App() {
  const auth = useAuth();
  const state = auth.state;
  const message = 'message' in state ? state.message : undefined;
  return <><a className="skip" href={auth.rechecking ? '#session-check' : '#main'}>Skip to main content</a><div className="page" aria-busy={auth.rechecking}>
    {auth.rechecking && <section id="session-check" className="session-panel" role="status" tabIndex={-1}><h1>Checking your session.</h1><p>Please wait while we check your session.</p></section>}
    <div hidden={auth.rechecking}>
    <header className="identity"><div className="wordmark" aria-label="Document Research"><em>document</em><span>research</span></div>
      {state.status === 'authenticated' ? <div className="account-controls"><span className="account-email">{state.session.user.email}</span><button className="button" onClick={() => void auth.logout()}>Log out</button></div> : <span className="identity-caption">Source library</span>}
    </header>
    {state.status === 'authenticated' && auth.library ? <AuthenticatedLibrary key={`${state.generation}:${state.session.session_context}`} session={auth.library} /> :
      state.status === 'anonymous' ? <AuthForm key="anonymous" pending={auth.pending} error={auth.error} message={state.message} submit={auth.submit} /> :
      <main id="main" className="session-panel" aria-busy={state.status === 'checking' || auth.pending}>
        <p className="eyebrow">Your source library</p><h1>{state.status === 'checking' ? 'Checking your session.' : state.status === 'logout-pending' ? 'Your library is hidden.' : 'Let’s check your session.'}</h1>
        <div role={message ? 'alert' : 'status'}><p>{message || (state.status === 'logout-pending' ? 'Logging out. Please wait.' : 'Please wait while we check your session.')}</p></div>
        {state.status === 'logout-pending' && state.message && <button className="button primary" disabled={auth.pending} onClick={() => void auth.logout()}>Retry logout</button>}
        {(state.status === 'unavailable' || (state.status === 'logout-pending' && !!state.message)) && <button className="button" disabled={auth.pending} onClick={auth.retryCheck}>Check session</button>}
      </main>}
    </div>
  </div></>;
}
