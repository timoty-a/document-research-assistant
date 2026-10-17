import { useEffect, useRef, useState } from 'react';
import { ApiError, fileProblem, listDocuments, reconcile, uploadDocument, type DocumentMetadata } from './api';

type UploadStatus = 'idle' | 'uploading' | 'success' | 'rejected' | 'uncertain' | 'retry-ready';
export function useLibrary() {
  const [documents, setDocuments] = useState<DocumentMetadata[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState(false);
  const [refreshed, setRefreshed] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>('idle');
  const [uploadMessage, setUploadMessage] = useState('');
  const [newId, setNewId] = useState<string | null>(null);
  const requestId = useRef(0);
  const mounted = useRef(false);
  const uploading = useRef(false);
  const refreshing = useRef(false);
  const status = useRef<UploadStatus>('idle');
  // No delete endpoint exists. Keep every acknowledged upload for this session;
  // neither a stale snapshot nor a failed refresh can erase that evidence.
  const confirmed = useRef(new Map<string, DocumentMetadata>());
  function updateStatus(next: UploadStatus) { status.current = next; setUploadStatus(next); }

  async function refresh() {
    if (uploading.current || refreshing.current) return;
    refreshing.current = true;
    const id = ++requestId.current;
    setLoading(true); setListError(false); setRefreshed(false);
    try {
      const rows = await listDocuments();
      if (!mounted.current || id !== requestId.current) return;
      setDocuments(reconcile(rows, [...confirmed.current.values()]));
      setRefreshed(documents !== null);
      if (status.current === 'uncertain') {
        updateStatus('retry-ready');
        setUploadMessage('Library refreshed. Check filenames, sizes and times before uploading again; another upload may create a duplicate.');
      }
    } catch {
      if (mounted.current && id === requestId.current) setListError(true);
    } finally {
      if (mounted.current && id === requestId.current) { refreshing.current = false; setLoading(false); }
    }
  }
  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => { mounted.current = false; requestId.current++; refreshing.current = false; };
  }, []);

  function choose(next: File | null) {
    if (uploading.current || status.current === 'uncertain') return;
    setFile(next);
    const problem = next ? fileProblem(next) : null;
    updateStatus(problem ? 'rejected' : 'idle');
    setUploadMessage(problem ?? '');
  }
  async function upload() {
    if (!file || uploading.current || status.current === 'uncertain' || status.current === 'success') return;
    const problem = fileProblem(file);
    if (problem) { updateStatus('rejected'); setUploadMessage(problem); return; }
    uploading.current = true; updateStatus('uploading'); setUploadMessage('Saving your document. Please wait.');
    try {
      const saved = await uploadDocument(file);
      if (!mounted.current) return;
      confirmed.current.set(saved.id, saved);
      setDocuments(previous => reconcile(previous ?? [], [saved]));
      setNewId(saved.id); updateStatus('success');
      setUploadMessage(`“${saved.original_filename}” is now in your library.`);
    } catch (error) {
      if (!mounted.current) return;
      const safe = error instanceof ApiError ? error : new ApiError('uncertain', 'Saving could not be confirmed. Refresh your library before retrying.');
      updateStatus(safe.kind === 'rejected' ? 'rejected' : 'uncertain'); setUploadMessage(safe.message);
    } finally { uploading.current = false; }
  }
  return { documents, loading, listError, refreshed, file, choose, upload, refresh,
    uploadStatus, uploadMessage, newId };
}
