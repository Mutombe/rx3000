/** What to say when this medicine is handed over.
 *
 *  This existed on the product page, which is the one place a pharmacist is not
 *  standing when they need it. At the counter they have the script in hand, the
 *  patient in front of them, and no reason to open a catalogue page — so the
 *  counselling half of dispensing lived entirely in whatever they happened to
 *  remember about that particular medicine.
 *
 *  Folded shut by default. A dispensing screen with four items on it cannot
 *  carry four expanded blocks of prose without burying the fields somebody is
 *  actually typing into, and counselling is a thing you reach for on the
 *  medicines you are less sure about rather than on all of them.
 *
 *  It never expands on its own. Nothing here should fire an AI call because a
 *  script happens to have six lines — that is somebody's money, spent without
 *  being asked for.
 */
import { useState } from "react";
import { CaretDown, CaretRight } from "@phosphor-icons/react";
import AiStreamBlock from "./AiStreamBlock";
import ClaudeIcon from "./ClaudeIcon";

export default function CounsellingPoints(
  { productId, name, compact }:
  { productId: number; name: string; compact?: boolean },
) {
  const [open, setOpen] = useState(!compact);

  return (
    <div className={compact ? "cp-inline" : "card"}>
      <button
        type="button"
        className={compact ? "cp-toggle" : "card-head cp-toggle"}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        {open ? <CaretDown size={12} weight="bold" />
              : <CaretRight size={12} weight="bold" />}
        <ClaudeIcon size={14} />
        <span>Counselling points</span>
        {!open && (
          <span className="muted small">
            what to say at hand-out
          </span>
        )}
      </button>

      {open && (
        <AiStreamBlock
          path={`/api/ai/counseling/${productId}/stream`}
          label="Draft counselling points"
          title={`Counselling — ${name}`}
          context={name}
          empty="How to take it, common side effects, key warnings, storage — in language that can be read straight to a patient."
        />
      )}
    </div>
  );
}
