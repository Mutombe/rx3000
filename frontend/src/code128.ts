/** A script number as a barcode, in bars rather than in a library.
 *
 *  MCAZ expects a dispensed script to carry a barcode, and the thing it has to
 *  encode is the Rx number: a short run of capitals and digits that this system
 *  already issues and already treats as the script's identity. That is exactly
 *  what Code 128 is for, and Code 128 is about eighty lines of table lookup.
 *
 *  WHY NOT A LIBRARY. The obvious ones weigh two to three hundred kilobytes and
 *  draw to a canvas, which is the wrong output: the label goes to a printer as
 *  a PDF, so what is wanted is the widths of the bars, not pixels of them. This
 *  returns the widths and lets the caller draw them at whatever size the paper
 *  is, which is also what makes the same barcode correct on a 203dpi roll and a
 *  300dpi one.
 *
 *  SET B, AND ONLY SET B. Code 128 has three character sets; B covers every
 *  printable ASCII character, which is everything an Rx number contains. Set C
 *  would pack digit pairs and make the barcode shorter, and it would also make
 *  this twice the length and introduce a switching rule to get wrong. A script
 *  number is eleven characters; the saving is not worth the risk on something
 *  an inspector scans.
 */

/** The 107 Code 128 symbols, as bar and space widths.
 *
 *  Each is six digits: bar, space, bar, space, bar, space, in modules. The
 *  table is the standard one and is not derived from anything — it is the
 *  specification, transcribed.
 */
const SYMBOLS = [
  "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312",
  "132212", "221213", "221312", "231212", "112232", "122132", "122231", "113222",
  "123122", "123221", "223211", "221132", "221231", "213212", "223112", "312131",
  "311222", "321122", "321221", "312212", "322112", "322211", "212123", "212321",
  "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
  "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121",
  "313121", "211331", "231131", "213113", "213311", "213131", "311123", "311321",
  "331121", "312113", "312311", "332111", "314111", "221411", "431111", "111224",
  "111422", "121124", "121421", "141122", "141221", "112214", "112412", "122114",
  "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
  "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112",
  "421211", "212141", "214121", "412121", "111143", "111341", "131141", "114113",
  "114311", "411113", "411311", "113141", "114131", "311141", "411131", "211412",
  "211214", "211232",
  // The stop is SEVEN elements, not six: it ends on an extra bar, and that bar
  // is what tells a scanner the symbol has finished. Written as six it drew a
  // barcode that looked entirely correct, measured correctly, and decoded as
  // nothing at all — which is why this file is checked by reading one back
  // rather than by looking at it.
  "2331112",
];

const START_B = 104;
const STOP = 106;

/** The bar and space widths for a string, in modules, starting with a bar.
 *
 *  A scanner reads the quiet zone as part of the symbol, so ten modules of
 *  nothing are added at each end. A barcode printed hard against the edge of a
 *  sticker is one that reads on the bench and fails at the wholesaler.
 */
export function code128Bars(text: string): number[] {
  const value = String(text ?? "")
    // Set B covers 32 to 126. Anything else is not in an Rx number, and
    // silently encoding it as something adjacent would produce a barcode that
    // scans as the wrong script, which is worse than one that does not scan.
    .replace(/[^\x20-\x7E]/g, "")
    .slice(0, 48);
  if (!value) return [];

  const codes = [START_B];
  for (const ch of value) codes.push(ch.charCodeAt(0) - 32);

  // The check digit is the start value plus each symbol times its position,
  // modulo 103. It is part of the symbol, not a suffix on the text.
  let sum = START_B;
  for (let i = 1; i < codes.length; i += 1) sum += codes[i] * i;
  codes.push(sum % 103);
  codes.push(STOP);

  const widths: number[] = [10];                  // leading quiet zone
  for (const code of codes) {
    for (const module of SYMBOLS[code]) widths.push(Number(module));
  }
  widths.push(10);                                // trailing quiet zone
  return widths;
}

/** Where each black bar sits, as {x, width} in modules from the left.
 *
 *  The widths alternate bar, space, bar, space and the first entry is the quiet
 *  zone, which is a space — so the drawing starts on the second. Returning
 *  rectangles rather than a run of widths means a caller cannot get the
 *  alternation wrong, which is the one way to draw a barcode that looks right
 *  and reads as something else.
 */
export function code128Rects(text: string): { x: number; width: number }[] {
  const widths = code128Bars(text);
  const rects: { x: number; width: number }[] = [];
  let x = 0;
  widths.forEach((width, i) => {
    // Index 0 is the quiet zone, so odd indices are the bars.
    if (i % 2 === 1) rects.push({ x, width });
    x += width;
  });
  return rects;
}

/** Total width of the symbol in modules, quiet zones included. */
export function code128Width(text: string): number {
  return code128Bars(text).reduce((n, w) => n + w, 0);
}
