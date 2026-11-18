import { useEffect, useRef } from "react";

const FOCUSABLE = "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]";

// A modal dialog. Focus moves into it once, when it opens; Tab and Shift+Tab stay inside it; Escape closes it.
export function Dialog({ title, onClose, children }) {
  const box = useRef(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    box.current?.querySelector(FOCUSABLE)?.focus();
    const onKey = (e) => {
      if (e.key === "Escape") close.current();
      if (e.key !== "Tab" || !box.current) return;
      const items = [...box.current.querySelectorAll(FOCUSABLE)];
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      const inside = box.current.contains(document.activeElement);
      if (e.shiftKey && (document.activeElement === first || !inside)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || !inside)) { e.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title} ref={box}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

// "Are you sure?" for irreversible actions. The dialog is a form, so Enter confirms and Escape cancels.
export function Confirm({ title, children, confirmLabel, onConfirm, onClose, busy }) {
  return (
    <Dialog title={title} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); onConfirm(); }}>
        {children}
        <div className="actions">
          <button type="submit" className="primary" disabled={busy}>{busy ? "Working..." : confirmLabel}</button>
          <button type="button" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </Dialog>
  );
}

export function ErrorNote({ error }) {
  if (!error) return null;
  return <p className="error" role="alert">{typeof error === "string" ? error : error.message}</p>;
}
