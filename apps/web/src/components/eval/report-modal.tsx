"use client";

interface ReportModalProps {
  reportMarkdown: string;
  onCopy: () => void;
  onDownload: () => void;
  onClose: () => void;
  title?: string;
}

export function ReportModal({
  reportMarkdown,
  onCopy,
  onDownload,
  onClose,
  title = "Evaluation Report",
}: ReportModalProps) {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-white dark:bg-slate-900 rounded-xl shadow-xl w-full max-w-4xl max-h-[85vh] flex flex-col mx-4">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-slate-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">{title}</h2>
          <div className="flex items-center gap-2">
            <button
              onClick={onCopy}
              className="px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-slate-800 text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors"
            >
              Copy Markdown
            </button>
            <button
              onClick={onDownload}
              className="px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-slate-800 text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors"
            >
              Download
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4">
          <pre className="text-sm text-gray-800 dark:text-slate-200 whitespace-pre-wrap font-mono leading-relaxed">{reportMarkdown}</pre>
        </div>
      </div>
    </div>
  );
}
