/* Reading the number under the bars, for packs that have no bars.
 *
 * WHY THIS EXISTS
 *
 * Plenty of stock carries the article number printed and no barcode at all:
 * locally repacked units, pharmacy-printed labels, packs whose bars have worn
 * off a blister foil. The digits are the same data the bars would have
 * carried, so reading them gets to the same product.
 *
 * WHY IT IS NOT SIMPLY A SECOND DECODER
 *
 * A barcode decoder either decodes or stays silent, so anything it returns is
 * as good as the print. This fails the other way round: it misreads
 * confidently, and hands back a clean-looking number for a different article.
 * So nothing here is ever sent as a barcode. Everything it produces is
 * labelled `ocr`, and the station at the other end will not act on it until
 * somebody has looked at it.
 *
 * WHAT MAKES IT SAFE ENOUGH TO BE WORTH HAVING
 *
 * The check digit. EAN-13, UPC-A, EAN-8 and ITF-14 all carry a mod-10 digit
 * computed over the rest of the number, and it catches EVERY single-character
 * misread, which is the mistake this actually makes. A reading whose check
 * digit agrees is offered confidently; one that does not is still offered,
 * because a pharmacy's own repack labels are frequently not valid GTINs, but
 * it is offered as a number nothing can vouch for.
 *
 * WHY IT IS LOADED ONLY WHEN ASKED FOR
 *
 * The recogniser is several megabytes. The whole point of this page is that
 * it works on a phone in a shop on a mobile connection, so nothing is fetched
 * until somebody taps the button, and once fetched the browser keeps it.
 *
 * WHY THE CDN, WHEN THE BARCODE DECODER IS VENDORED
 *
 * Deliberate and not an oversight. The decoder is vendored because scanning
 * is the one thing that must work in a shop with a bad line, and it must not
 * depend on a third party being up. This is the fallback for that fallback:
 * if it cannot be fetched, the pack can still be read by typing the number,
 * which is a box already on this screen. Vendoring four megabytes into the
 * repository to guarantee the availability of a convenience is the wrong
 * trade.
 */

const CDN = "https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js";

/** Lengths a printed article number actually comes in. Anything else is the
 *  recogniser having read part of a batch number or a price. */
const WIDTHS = [8, 12, 13, 14];

let loading = null;
let worker = null;

/** Fetch the recogniser once, and hand back the same one afterwards. */
async function ready(onProgress) {
  if (worker) return worker;
  if (loading) return loading;
  loading = (async () => {
    if (!globalThis.Tesseract) {
      await new Promise((go, stop) => {
        const tag = document.createElement("script");
        tag.src = CDN;
        tag.async = true;
        tag.onload = go;
        tag.onerror = () => stop(new Error(
          "The number reader could not be downloaded. Check the connection, "
          + "or type the number instead."));
        document.head.appendChild(tag);
      });
    }
    onProgress?.("Getting the number reader ready…");
    const w = await globalThis.Tesseract.createWorker("eng", 1, {
      logger: (m) => {
        if (m.status === "loading tesseract core") onProgress?.("Loading…");
        else if (m.status === "downloading") onProgress?.("Downloading…");
      },
    });
    // Digits only. The number under a barcode has nothing else in it, and
    // every letter the recogniser is allowed to consider is another way for
    // it to be confidently wrong.
    await w.setParameters({
      tessedit_char_whitelist: "0123456789",
      // One line of text, which is what a number strip is.
      tessedit_pageseg_mode: "7",
    });
    worker = w;
    return w;
  })();
  return loading;
}

/** The mod-10 check digit, computed the way GS1 does.
 *
 *  Weights alternate 3 and 1 from the right. That is what makes it catch
 *  every single-character substitution: changing one digit changes the total
 *  by either the difference or three times it, and neither is a multiple of
 *  ten for a single digit change.
 */
function checkDigit(body) {
  let total = 0;
  const digits = body.split("").reverse();
  for (let i = 0; i < digits.length; i++) {
    total += Number(digits[i]) * (i % 2 === 0 ? 3 : 1);
  }
  return String((10 - (total % 10)) % 10);
}

export function validGtin(code) {
  if (!/^\d+$/.test(code) || !WIDTHS.includes(code.length)) return false;
  return checkDigit(code.slice(0, -1)) === code.slice(-1);
}

/** Pull the guide box out of the video, bigger and harder-edged.
 *
 *  Three things matter more than the recogniser itself: a tight crop so it is
 *  not reading the pack's artwork, enough pixels that a 2mm-tall digit is not
 *  six of them, and contrast, because printed numbers on a glossy foil are
 *  grey on grey to a phone sensor.
 */
function crop(video, box) {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  if (!vw || !vh) return null;

  // READ WIDER THAN THE BOX THE OPERATOR SEES.
  //
  // The first version cropped exactly to the guide. A number centred in it
  // nearly fills it, so the outermost digits sat on the crop boundary, and
  // the threshold pass ate them: 5449000000996 came back as 5449000000990
  // and 6001234500024 as 0001234500024. Both were caught by the check digit,
  // which is the system working, but a reader that has to be caught half the
  // time is one nobody uses.
  //
  // So the visible guide stays where it is and the crop takes a margin
  // around it. The operator lines the number up inside the box; the
  // recogniser gets the box and a little of what surrounds it.
  const padX = box.w * 0.06;
  const padY = box.h * 0.22;
  const sx = Math.round(Math.max(0, box.x - padX) * vw);
  const sy = Math.round(Math.max(0, box.y - padY) * vh);
  const sw = Math.round(Math.min(1 - box.x + padX, box.w + padX * 2) * vw);
  const sh = Math.round(Math.min(1 - box.y + padY, box.h + padY * 2) * vh);

  // Upscaled: the recogniser is far better on a tall line of text than a
  // short one, and a phone crop of a number strip is short.
  const scale = Math.max(1, Math.min(4, 220 / Math.max(sh, 1)));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(sw * scale);
  canvas.height = Math.round(sh * scale);
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(video, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);

  // Grey, then a threshold taken from the crop's own average rather than a
  // fixed number: a number under a shop light and the same number under a
  // window are different images, and a fixed cut turns one of them to mud.
  const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const px = img.data;
  let sum = 0;
  for (let i = 0; i < px.length; i += 4) {
    const grey = (px[i] * 0.299 + px[i + 1] * 0.587 + px[i + 2] * 0.114);
    px[i] = px[i + 1] = px[i + 2] = grey;
    sum += grey;
  }
  const mean = sum / (px.length / 4);
  // Slightly under the mean: ink is darker than paper, and biasing towards
  // keeping ink loses fewer thin strokes than biasing towards clean paper.
  const cut = mean * 0.82;
  for (let i = 0; i < px.length; i += 4) {
    const on = px[i] < cut ? 0 : 255;
    px[i] = px[i + 1] = px[i + 2] = on;
  }
  ctx.putImageData(img, 0, 0);
  return canvas;
}

/** Read the guide box once.
 *
 *  Returns null rather than a guess when nothing usable is there, because a
 *  frame that will not read is the normal case while somebody is lining a
 *  pack up, not an error worth showing them.
 */
export async function readOnce(video, box, onProgress) {
  const canvas = crop(video, box);
  if (!canvas) return null;
  const w = await ready(onProgress);
  const { data } = await w.recognize(canvas);

  // Everything that is not a digit is the recogniser telling us about the
  // pack's artwork.
  const runs = (data?.text ?? "").match(/\d+/g) ?? [];
  if (!runs.length) return null;

  // The longest run of digits, which on a number strip is the number. A
  // price or a batch fragment alongside it is shorter.
  runs.sort((a, b) => b.length - a.length);
  const best = runs[0];
  if (!WIDTHS.includes(best.length)) {
    return { code: best, verified: false, usable: false,
             confidence: data?.confidence ?? 0 };
  }
  return {
    code: best,
    verified: validGtin(best),
    usable: true,
    confidence: data?.confidence ?? 0,
  };
}

/** Free the recogniser. Called when the reader is switched off, because it
 *  holds a worker and several megabytes and a phone at a counter has other
 *  things to do with both. */
export async function release() {
  const w = worker;
  worker = null;
  loading = null;
  try { await w?.terminate(); } catch {}
}
