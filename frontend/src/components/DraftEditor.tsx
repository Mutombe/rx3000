/** An editable draft that can also be seen the way its reader will see it.
 *
 *  These fields hold text the AI drafted and a person then edits before it goes
 *  out. Rendering them as Markdown outright would be wrong — you cannot edit a
 *  rendered heading — but leaving them as a plain textarea means nobody sees
 *  what the customer will actually receive until it has been sent.
 *
 *  So both, with editing as the default. The toggle is deliberately not sticky:
 *  the field's job is editing, and a preview that persists across drafts leaves
 *  somebody typing into a box that is not showing them their own text.
 */
import { useState } from "react";
import Markdown from "./Markdown";
import IconButton from "./IconButton";

interface Props {
  value: string;
  onChange: (next: string) => void;
  rows?: number;
  placeholder?: string;
  required?: boolean;
  /** What this text becomes, so the preview label says something useful. */
  audience?: string;
}

export default function DraftEditor({
  value, onChange, rows = 5, placeholder, required, audience = "the recipient",
}: Props) {
  const [preview, setPreview] = useState(false);
  const hasMarkup = /(^|\n)\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>)|\*\*|\||`/.test(value || "");

  return (
    <div className="draft">
      <div className="draft-bar">
        {/* Offered only when there is something to preview. A toggle that
            reveals identical text teaches people it does nothing. */}
        {hasMarkup ? (
          <>
            <IconButton action="edit" onClick={() => setPreview(false)} type="button" />
            <button
              type="button"
              className={`btn ghost small${preview ? " is-on" : ""}`}
              onClick={() => setPreview(true)}
            >
              As {audience} sees it
            </button>
          </>
        ) : (
          <span className="draft-hint">
            Headings, <b>**bold**</b>, lists and tables are formatted when sent.
          </span>
        )}
      </div>

      {preview ? (
        <div className="draft-preview">
          <Markdown text={value} />
        </div>
      ) : (
        <textarea
          rows={rows}
          value={value}
          required={required}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </div>
  );
}
