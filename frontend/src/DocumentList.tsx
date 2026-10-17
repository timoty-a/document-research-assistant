import type { DocumentMetadata } from './api';
export function formatSize(bytes: number) {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KiB`;
}
export function FileIcon() {
  return <svg className="file-icon" aria-hidden="true" viewBox="0 0 20 25" fill="none"><path d="M3 1h9l5 5v18H3zM12 1v6h5M6 12h8M6 16h8" stroke="currentColor" strokeWidth="1.2" /></svg>;
}
const dateFormat = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Africa/Lagos' });
const timeFormat = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Africa/Lagos' });
export function DocumentList({ documents, newId }: { documents: DocumentMetadata[]; newId: string | null }) {
  return <><div className="column-head" aria-hidden="true"><span>Document</span><span>Size</span><span>Added</span><span>Metadata</span></div>
    <ol className="records">{documents.map(d => <li key={d.id}>
      <details className={`record${d.id === newId ? ' new-record' : ''}`}>
        <summary className="record-summary">
          <span className="document-name"><FileIcon /><span className="filename">{d.original_filename}</span></span>
          <span className="meta"><span className="meta-label" aria-hidden="true">Size</span><span className="sr-only">File size: </span>{formatSize(d.byte_size)}</span>
          <span className="meta"><span className="meta-label" aria-hidden="true">Added</span><span className="sr-only">Added: </span><time dateTime={d.created_at}>{dateFormat.format(new Date(d.created_at))}<span className="time">{timeFormat.format(new Date(d.created_at))} WAT</span></time></span>
          <span className="details-label">Details <svg aria-hidden="true" viewBox="0 0 12 12" fill="none"><path d="m3 4.5 3 3 3-3" stroke="currentColor" strokeWidth="1.3" /></svg></span>
        </summary>
        <div className="record-expanded"><dl><div><dt>Record ID</dt><dd>{d.id}</dd></div><div><dt>Exact file size</dt><dd>{d.byte_size.toLocaleString('en-GB')} bytes</dd></div></dl></div>
      </details>
    </li>)}</ol></>;
}
