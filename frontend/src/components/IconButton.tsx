/** A row action drawn as an icon.
 *
 *  The action is named, not the icon: `<IconButton action="edit" />`, never
 *  `<IconButton icon={PencilSimple} />`. One table then cannot use a pencil for
 *  editing while another uses a note-pad, which is how icon sets rot — and the
 *  accessible name travels with the glyph instead of being remembered at each
 *  of the seventy-nine call sites.
 *
 *  Only the verbs everybody already reads as a picture are here: edit, view,
 *  delete, download, print, adjust, add, copy, cancel. A consequential domain
 *  action — "Write off", "Bill patient", "Hand over 2" — keeps its words. An
 *  icon meaning "write this debt off" does not exist, and inventing one asks a
 *  pharmacist to guess with somebody's money.
 *
 *  An icon-only control is invisible to a screen reader without a name, so the
 *  name is not optional: `aria-label` and `title` both come from the action.
 */
import {
  ArrowCounterClockwise, ArrowSquareOut, Copy, DownloadSimple, Eye,
  PencilSimple, Plus, Printer, SlidersHorizontal, Trash, X,
} from "@phosphor-icons/react";
import ClaudeIcon from "./ClaudeIcon";

const ACTIONS = {
  edit:     { Icon: PencilSimple,        label: "Edit" },
  view:     { Icon: Eye,                 label: "View" },
  open:     { Icon: ArrowSquareOut,      label: "Open" },
  delete:   { Icon: Trash,               label: "Delete" },
  remove:   { Icon: X,                   label: "Remove" },
  cancel:   { Icon: X,                   label: "Cancel" },
  download: { Icon: DownloadSimple,      label: "Download" },
  print:    { Icon: Printer,             label: "Print" },
  adjust:   { Icon: SlidersHorizontal,   label: "Adjust" },
  add:      { Icon: Plus,                label: "Add" },
  copy:     { Icon: Copy,                label: "Duplicate" },
  undo:     { Icon: ArrowCounterClockwise, label: "Undo" },
  review:   { Icon: ClaudeIcon,          label: "AI review" },
} as const;

export type IconAction = keyof typeof ACTIONS;

export default function IconButton({
  action, onClick, disabled, title, danger, type = "button",
}: {
  action: IconAction;
  onClick?: (e: React.MouseEvent) => void;
  disabled?: boolean;
  /** Overrides the default name where the row needs to be specific —
   *  "Edit this branch" rather than "Edit". Never omit it to save space. */
  title?: string;
  /** Destructive actions read red on hover, so the pointer warns before the click. */
  danger?: boolean;
  type?: "button" | "submit";
}) {
  const { Icon, label } = ACTIONS[action];
  const name = title ?? label;
  return (
    <button
      type={type}
      className={`icon-btn${danger ? " is-danger" : ""}`}
      onClick={onClick}
      disabled={disabled}
      aria-label={name}
      title={name}
    >
      <Icon size={16} weight="bold" aria-hidden="true" />
    </button>
  );
}
