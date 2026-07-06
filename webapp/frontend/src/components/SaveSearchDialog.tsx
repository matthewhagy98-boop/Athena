import { useState } from "react";

export function SaveSearchDialog({
  open,
  onSave,
  onClose,
  disabled,
}: {
  open: boolean;
  onSave: (name: string) => void;
  onClose: () => void;
  disabled: boolean;
}) {
  const [name, setName] = useState("");
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-primary-container/40" role="dialog" aria-modal="true" aria-labelledby="save-search-title">
      <div className="w-80 rounded-lg border border-hairline bg-surface-container-lowest p-5">
        <p id="save-search-title" className="mb-3 text-sm font-semibold">Save this search</p>
        <label className="mb-1 block text-xs font-medium text-on-surface-variant" htmlFor="save-search-name">Name</label>
        <input
          id="save-search-name"
          className="mb-4 w-full rounded border border-outline-variant p-1.5 text-sm"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Machine learning in hematology"
        />
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded border border-outline-variant px-3 py-1.5 text-xs font-semibold">
            Cancel
          </button>
          <button
            onClick={() => name.trim() && onSave(name.trim())}
            disabled={disabled || !name.trim()}
            className="rounded bg-secondary px-3 py-1.5 text-xs font-semibold text-on-secondary disabled:opacity-50"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
