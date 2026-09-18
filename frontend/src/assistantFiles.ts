/** Screenshots and documents on their way to RX-Assistant.
 *
 *  The commonest attachment by far is a screenshot of the very screen somebody
 *  is asking about, which is why pasting has to work: a dispenser presses the
 *  print-screen key and then Ctrl with V, and anything that makes them save a
 *  file first is a feature they will not use.
 *
 *  IMAGES ARE SHRUNK BEFORE THEY LEAVE THE BROWSER.
 *
 *  A modern screen grab is three or four megabytes and several thousand pixels
 *  across. None of that reaches the model: it reads images at about 1568 pixels
 *  on the long edge, so anything larger is bandwidth a pharmacy pays for on a
 *  line it does not have, and tokens the pharmacy pays for twice. Shrunk here,
 *  where there is a canvas, rather than on a server that would have to receive
 *  the whole thing first.
 */

/** What the assistant endpoint takes. */
export interface Attachment {
  name: string;
  media_type: string;
  /** base64, without the data: prefix. */
  data: string;
  /** For the thumbnail in the composer. */
  preview: string;
  bytes: number;
}

const IMAGES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
export const TAKES = [...IMAGES, "application/pdf"];
export const MAX_FILES = 4;
/** What the long edge is worth carrying. Above this the model sees no more. */
const LONG_EDGE = 1568;

const base64 = (blob: Blob): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("That file could not be read."));
    reader.onload = () => {
      const said = String(reader.result ?? "");
      resolve(said.slice(said.indexOf(",") + 1));
    };
    reader.readAsDataURL(blob);
  });

/** One file, ready to send. Throws with a sentence somebody can act on. */
export async function readForAssistant(file: File): Promise<Attachment> {
  const kind = (file.type || "").toLowerCase();
  if (!TAKES.includes(kind)) {
    throw new Error(`${file.name || "That file"} is a ${kind || "kind"} I cannot read. `
                  + "Send a screenshot, a picture or a PDF.");
  }

  if (kind === "application/pdf") {
    if (file.size > 5 * 1024 * 1024) {
      throw new Error(`${file.name} is ${(file.size / 1024 / 1024).toFixed(1)}MB. `
                    + "Five is the most I can take.");
    }
    const data = await base64(file);
    return { name: file.name || "document.pdf", media_type: kind, data,
             preview: "", bytes: file.size };
  }

  // Drawn onto a canvas at the size the model actually reads at. A GIF loses
  // its animation doing this, which is the right trade: a still frame of it
  // answers the question and the whole file does not.
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, LONG_EDGE / Math.max(bitmap.width, bitmap.height));
  const w = Math.max(1, Math.round(bitmap.width * scale));
  const h = Math.max(1, Math.round(bitmap.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("This browser cannot prepare that image.");
  ctx.drawImage(bitmap, 0, 0, w, h);
  bitmap.close?.();

  // PNG for a screenshot, because text and lines are what it will be full of
  // and JPEG smears both. A photograph of a box is sent as JPEG.
  const asPng = kind === "image/png" || kind === "image/gif" || kind === "image/webp";
  const out: Blob = await new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("That image could not be prepared."))),
                  asPng ? "image/png" : "image/jpeg", asPng ? undefined : 0.86));

  return {
    name: file.name || (asPng ? "screenshot.png" : "photo.jpg"),
    media_type: asPng ? "image/png" : "image/jpeg",
    data: await base64(out),
    preview: URL.createObjectURL(out),
    bytes: out.size,
  };
}

/** Everything worth reading out of a paste or a drop. */
export function filesFrom(source: DataTransfer | null | undefined): File[] {
  if (!source) return [];
  const out: File[] = [];
  for (const item of Array.from(source.items ?? [])) {
    if (item.kind !== "file") continue;
    const file = item.getAsFile();
    if (file) out.push(file);
  }
  if (!out.length) out.push(...Array.from(source.files ?? []));
  return out.filter((f) => TAKES.includes((f.type || "").toLowerCase()));
}
