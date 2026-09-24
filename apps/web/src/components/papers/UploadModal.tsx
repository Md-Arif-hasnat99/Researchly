import React, { useCallback, useRef, useState } from 'react';
import { Upload, X, FileText, CheckCircle, AlertCircle } from 'lucide-react';
import { Button } from '../ui/Button';
import { uploadPaper } from '../../lib/api';
import type { Paper } from '../../types/paper';

type UploadState = 'idle' | 'uploading' | 'success' | 'error';

interface UploadModalProps {
  onClose: () => void;
  onUploaded: (paper: Paper) => void;
}

const MAX_MB = 50;
const MAX_BYTES = MAX_MB * 1024 * 1024;

export const UploadModal: React.FC<UploadModalProps> = ({ onClose, onUploaded }) => {
  const [uploadState, setUploadState] = useState<UploadState>('idle');
  const [progress, setProgress] = useState(0);
  const [errorMsg, setErrorMsg] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const validateFile = (file: File): string | null => {
    if (file.type !== 'application/pdf') return 'Only PDF files are accepted.';
    if (file.size > MAX_BYTES) return `File must be under ${MAX_MB} MB.`;
    return null;
  };

  const handleFile = (file: File) => {
    const err = validateFile(file);
    if (err) {
      setErrorMsg(err);
      setUploadState('error');
      return;
    }
    setSelectedFile(file);
    setUploadState('idle');
    setErrorMsg('');
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, []);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    setUploadState('uploading');
    setProgress(0);

    // Simulate progress ticks while awaiting the real response
    const ticker = setInterval(() => {
      setProgress((p) => Math.min(p + 8, 85));
    }, 200);

    try {
      const paper = await uploadPaper(selectedFile);
      clearInterval(ticker);
      setProgress(100);
      setUploadState('success');
      setTimeout(() => {
        onUploaded(paper);
        onClose();
      }, 800);
    } catch (err) {
      clearInterval(ticker);
      setErrorMsg(err instanceof Error ? err.message : 'Upload failed. Please try again.');
      setUploadState('error');
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fadeIn"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      role="dialog"
      aria-modal="true"
      aria-label="Upload paper"
    >
      <div className="bg-surface border border-border rounded-2xl shadow-2xl w-full max-w-md mx-4 p-6 relative">
        {/* Close */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-text-muted hover:text-text-primary transition-colors"
          aria-label="Close upload dialog"
        >
          <X className="w-5 h-5" />
        </button>

        <h2 className="text-lg font-semibold text-text-primary mb-1">Upload Research Paper</h2>
        <p className="text-sm text-text-muted mb-5">PDF only · max {MAX_MB} MB</p>

        {/* Drop zone */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-8 flex flex-col items-center justify-center gap-3 cursor-pointer transition-colors select-none ${
            dragOver
              ? 'border-accent bg-accent/5'
              : 'border-border hover:border-accent/50 hover:bg-neutral-50/50'
          }`}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === 'Enter' && fileInputRef.current?.click()}
          id="upload-dropzone"
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            className="hidden"
            onChange={handleInputChange}
            id="paper-file-input"
          />

          {selectedFile ? (
            <>
              <FileText className="w-10 h-10 text-accent" />
              <div className="text-center">
                <p className="text-sm font-medium text-text-primary truncate max-w-xs">
                  {selectedFile.name}
                </p>
                <p className="text-xs text-text-muted mt-0.5">
                  {(selectedFile.size / (1024 * 1024)).toFixed(1)} MB
                </p>
              </div>
            </>
          ) : (
            <>
              <Upload className="w-10 h-10 text-text-muted" />
              <div className="text-center">
                <p className="text-sm font-medium text-text-primary">Drop PDF here</p>
                <p className="text-xs text-text-muted mt-0.5">or click to browse</p>
              </div>
            </>
          )}
        </div>

        {/* Progress bar */}
        {uploadState === 'uploading' && (
          <div className="mt-4">
            <div className="flex justify-between text-xs text-text-muted mb-1">
              <span>Uploading…</span>
              <span>{progress}%</span>
            </div>
            <div className="h-1.5 bg-neutral-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-accent rounded-full transition-all duration-200"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        {/* Success */}
        {uploadState === 'success' && (
          <div className="mt-4 flex items-center gap-2 text-emerald-600 text-sm">
            <CheckCircle className="w-4 h-4" />
            <span>Upload complete!</span>
          </div>
        )}

        {/* Error */}
        {uploadState === 'error' && (
          <div className="mt-4 flex items-center gap-2 text-rose-600 text-sm">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Actions */}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" size="md" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="md"
            onClick={handleUpload}
            disabled={!selectedFile || uploadState === 'uploading' || uploadState === 'success'}
            id="upload-submit-btn"
          >
            {uploadState === 'uploading' ? 'Uploading…' : 'Upload'}
          </Button>
        </div>
      </div>
    </div>
  );
};
