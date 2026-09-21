/** A QR code, drawn as an SVG, for the pairing code on the counter screen.
 *
 *  WHY NOT THE CODE 128 THIS PRODUCT ALREADY DRAWS
 *
 *  Because it was tried and it is the wrong symbol for this job. A six
 *  character pairing code is 121 modules of Code 128, and the panel it sits
 *  in is about 250px wide, which puts a bar at roughly two pixels. Two pixels
 *  on a glossy monitor, photographed at arm's length by a phone running its
 *  decoder at eight frames a second, is inside the margin where it sometimes
 *  works and sometimes does not — and "sometimes" is the worst possible
 *  behaviour for the first thing a new user is asked to do.
 *
 *  A QR of the same payload is 21x21 modules. In that same 250px it gets
 *  nearly twelve pixels a module, it carries error correction so a reflection
 *  costs nothing, it needs no particular orientation, and it cannot be
 *  stretched into unreadability by a CSS width. Every one of those is the
 *  difference between a feature that demos well and one that works in a shop.
 *
 *  WHY IT IS WRITTEN OUT HERE
 *
 *  `zxing-wasm` is already a dependency and can encode, but its writer loads
 *  a second wasm binary and its own documentation says the writer API is
 *  "subject to change a lot". Loading a megabyte of WebAssembly to draw a
 *  21x21 grid, against an API that is expected to break, is a poor trade.
 *  This file is the same choice `code128.ts` made, for the same reason.
 *
 *  WHAT IT SUPPORTS, AND WHAT IT DOES NOT
 *
 *  Version 1 through 4 at error correction level M, alphanumeric mode only:
 *  digits, capitals, space and `$%*+-./:`. That covers the pairing alphabet
 *  with room to spare and nothing else. It is deliberately not a general QR
 *  encoder, because a general one is a great deal more code to get wrong and
 *  nothing here needs it. `qrSvg` returns "" for anything it cannot encode,
 *  so a caller falls back to showing the characters rather than drawing a
 *  symbol that will not read.
 */

/** Alphanumeric mode's character set. The index IS the value. */
const ALNUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:";

/** Data codewords available at error correction level M, by version. */
const DATA_CODEWORDS: Record<number, number> = { 1: 16, 2: 28, 3: 44, 4: 64 };

/** Error correction codewords per block at level M, by version. */
const EC_CODEWORDS: Record<number, number> = { 1: 10, 2: 16, 3: 26, 4: 18 };

/** How many blocks the data is split into at level M, by version. */
const EC_BLOCKS: Record<number, number> = { 1: 1, 2: 1, 3: 1, 4: 2 };

/** Where the alignment pattern centres sit, by version. Version 1 has none. */
const ALIGN: Record<number, number[]> = { 1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26] };

// ----------------------------------------------------------------- GF(256)
//
// The Reed-Solomon field QR uses: modulo 0x11d, generator 2.

const EXP = new Uint8Array(512);
const LOG = new Uint8Array(256);
(() => {
  let x = 1;
  for (let i = 0; i < 255; i++) {
    EXP[i] = x;
    LOG[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11d;
  }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
})();

function mul(a: number, b: number): number {
  return a === 0 || b === 0 ? 0 : EXP[LOG[a] + LOG[b]];
}

/** The generator polynomial for `count` error correction codewords. */
function generator(count: number): number[] {
  let poly = [1];
  for (let i = 0; i < count; i++) {
    const next = new Array(poly.length + 1).fill(0);
    for (let j = 0; j < poly.length; j++) {
      next[j] ^= poly[j];
      next[j + 1] ^= mul(poly[j], EXP[i]);
    }
    poly = next;
  }
  return poly;
}

/** The error correction codewords for one block. */
function remainder(data: number[], count: number): number[] {
  const gen = generator(count);
  const out = new Array(count).fill(0);
  for (const byte of data) {
    const factor = byte ^ out[0];
    out.shift();
    out.push(0);
    for (let j = 0; j < count; j++) out[j] ^= mul(gen[j + 1], factor);
  }
  return out;
}

// ------------------------------------------------------------- format info
//
// Fifteen bits: five of level and mask, ten of BCH(15,5), then masked with
// 0x5412 so an all-zero format is not a valid pattern.

function formatBits(mask: number): number {
  // 0b00 is level M in the two-bit level encoding used by the format info.
  let value = (0b00 << 3) | mask;
  let rest = value << 10;
  for (let i = 4; i >= 0; i--) {
    if (rest & (1 << (i + 10))) rest ^= 0b10100110111 << i;
  }
  return ((value << 10) | rest) ^ 0b101010000010010;
}

// ------------------------------------------------------------------ bits

class Bits {
  readonly out: number[] = [];
  push(value: number, width: number): void {
    for (let i = width - 1; i >= 0; i--) this.out.push((value >> i) & 1);
  }
  get length(): number { return this.out.length; }
}

/** The payload as alphanumeric-mode bits, or null if it does not fit. */
function encode(text: string, version: number): number[] | null {
  const values: number[] = [];
  for (const ch of text) {
    const at = ALNUM.indexOf(ch);
    if (at < 0) return null;
    values.push(at);
  }
  const capacity = DATA_CODEWORDS[version] * 8;
  const countBits = version <= 9 ? 9 : 11;      // alphanumeric, versions 1-9

  const bits = new Bits();
  bits.push(0b0010, 4);                          // alphanumeric mode
  bits.push(values.length, countBits);
  for (let i = 0; i + 1 < values.length; i += 2) {
    bits.push(values[i] * 45 + values[i + 1], 11);
  }
  if (values.length % 2) bits.push(values[values.length - 1], 6);

  if (bits.length > capacity) return null;

  // Terminator, then pad to a byte, then the alternating pad bytes.
  bits.push(0, Math.min(4, capacity - bits.length));
  while (bits.length % 8) bits.out.push(0);

  const words: number[] = [];
  for (let i = 0; i < bits.out.length; i += 8) {
    let byte = 0;
    for (let j = 0; j < 8; j++) byte = (byte << 1) | bits.out[i + j];
    words.push(byte);
  }
  const pads = [0xec, 0x11];
  let p = 0;
  while (words.length < DATA_CODEWORDS[version]) words.push(pads[p++ % 2]);
  return words;
}

/** Data and error correction codewords, interleaved as the spec requires. */
function codewords(text: string, version: number): number[] | null {
  const data = encode(text, version);
  if (!data) return null;

  const blocks = EC_BLOCKS[version];
  const ecCount = EC_CODEWORDS[version];
  const short = Math.floor(data.length / blocks);
  const longer = data.length % blocks;         // this many blocks get one more

  const dataBlocks: number[][] = [];
  const ecBlocks: number[][] = [];
  let at = 0;
  for (let b = 0; b < blocks; b++) {
    const size = short + (b >= blocks - longer ? 1 : 0);
    const chunk = data.slice(at, at + size);
    at += size;
    dataBlocks.push(chunk);
    ecBlocks.push(remainder(chunk, ecCount));
  }

  const out: number[] = [];
  const widest = Math.max(...dataBlocks.map((b) => b.length));
  for (let i = 0; i < widest; i++) {
    for (const block of dataBlocks) if (i < block.length) out.push(block[i]);
  }
  for (let i = 0; i < ecCount; i++) {
    for (const block of ecBlocks) out.push(block[i]);
  }
  return out;
}

// ----------------------------------------------------------------- matrix

type Grid = (0 | 1 | null)[][];

function blank(size: number): Grid {
  return Array.from({ length: size }, () => new Array(size).fill(null) as (0 | 1 | null)[]);
}

function finder(grid: Grid, row: number, col: number): void {
  for (let r = -1; r <= 7; r++) {
    for (let c = -1; c <= 7; c++) {
      const y = row + r;
      const x = col + c;
      if (y < 0 || x < 0 || y >= grid.length || x >= grid.length) continue;
      // The ring at -1 and 7 is the SEPARATOR and is always light. Folding it
      // into the edge test below painted it dark, which destroys the one
      // feature every decoder looks for first: a 1:1:3:1:1 finder with clear
      // space around it. The symbols encoded perfectly and read as nothing.
      if (r < 0 || r > 6 || c < 0 || c > 6) { grid[y][x] = 0; continue; }
      const edge = r === 0 || r === 6 || c === 0 || c === 6;
      const core = r >= 2 && r <= 4 && c >= 2 && c <= 4;
      grid[y][x] = edge || core ? 1 : 0;
    }
  }
}

function skeleton(version: number): { grid: Grid; taken: boolean[][] } {
  const size = version * 4 + 17;
  const grid = blank(size);
  const taken = Array.from({ length: size }, () => new Array(size).fill(false));

  const reserve = (y: number, x: number) => {
    if (y >= 0 && x >= 0 && y < size && x < size) taken[y][x] = true;
  };

  finder(grid, 0, 0);
  finder(grid, 0, size - 7);
  finder(grid, size - 7, 0);
  for (let r = -1; r <= 7; r++) {
    for (let c = -1; c <= 7; c++) {
      reserve(r, c);
      reserve(r, size - 7 + c);
      reserve(size - 7 + r, c);
    }
  }

  // Timing patterns.
  for (let i = 8; i < size - 8; i++) {
    const on: 0 | 1 = i % 2 === 0 ? 1 : 0;
    grid[6][i] = on; taken[6][i] = true;
    grid[i][6] = on; taken[i][6] = true;
  }

  // Alignment patterns, skipping the three that collide with the finders.
  const centres = ALIGN[version];
  for (const cy of centres) {
    for (const cx of centres) {
      const nearFinder =
        (cy <= 8 && cx <= 8) ||
        (cy <= 8 && cx >= size - 9) ||
        (cy >= size - 9 && cx <= 8);
      if (nearFinder) continue;
      for (let r = -2; r <= 2; r++) {
        for (let c = -2; c <= 2; c++) {
          const ring = Math.max(Math.abs(r), Math.abs(c));
          grid[cy + r][cx + c] = ring === 1 ? 0 : 1;
          taken[cy + r][cx + c] = true;
        }
      }
    }
  }

  // The dark module, and the format information area.
  grid[size - 8][8] = 1;
  taken[size - 8][8] = true;
  for (let i = 0; i < 9; i++) {
    if (!taken[8][i]) { taken[8][i] = true; grid[8][i] = 0; }
    if (!taken[i][8]) { taken[i][8] = true; grid[i][8] = 0; }
  }
  for (let i = 0; i < 8; i++) {
    taken[8][size - 1 - i] = true;
    taken[size - 1 - i][8] = true;
  }

  return { grid, taken };
}

/** The eight mask conditions, by number. */
function masked(mask: number, row: number, col: number): boolean {
  switch (mask) {
    case 0: return (row + col) % 2 === 0;
    case 1: return row % 2 === 0;
    case 2: return col % 3 === 0;
    case 3: return (row + col) % 3 === 0;
    case 4: return (Math.floor(row / 2) + Math.floor(col / 3)) % 2 === 0;
    case 5: return ((row * col) % 2) + ((row * col) % 3) === 0;
    case 6: return (((row * col) % 2) + ((row * col) % 3)) % 2 === 0;
    default: return (((row + col) % 2) + ((row * col) % 3)) % 2 === 0;
  }
}

/** Lay the codewords into the grid, up the two-module columns, zig-zagging. */
function place(grid: Grid, taken: boolean[][], words: number[], mask: number): void {
  const size = grid.length;
  const bits: number[] = [];
  for (const word of words) {
    for (let i = 7; i >= 0; i--) bits.push((word >> i) & 1);
  }

  let at = 0;
  let upward = true;
  for (let right = size - 1; right > 0; right -= 2) {
    if (right === 6) right--;                    // the vertical timing column
    for (let step = 0; step < size; step++) {
      const row = upward ? size - 1 - step : step;
      for (const col of [right, right - 1]) {
        if (taken[row][col]) continue;
        const bit = at < bits.length ? bits[at++] : 0;
        grid[row][col] = (masked(mask, row, col) ? bit ^ 1 : bit) as 0 | 1;
      }
    }
    upward = !upward;
  }
}

function writeFormat(grid: Grid, mask: number): void {
  const size = grid.length;
  const bits = formatBits(mask);
  const bit = (i: number): 0 | 1 => ((bits >> i) & 1) as 0 | 1;

  // Both copies in one pass, bit 0 first, exactly as the spec orders them.
  //
  // Written the other way round first: bits 0-5 along row 8 and the rest down
  // column 8, which is the same fifteen bits MIRRORED. It looks right, it is
  // symmetric, and a decoder reads the format as garbage and gives up before
  // it ever reaches the data. Found by diffing against a known-good encoder,
  // not by reading it back.
  for (let i = 0; i < 15; i++) {
    const m = bit(i);

    // Down the left of the top-left finder, continuing at the bottom-left.
    // The gap at row 6 is the timing column, and row `size - 8` is the dark
    // module, which is why this jumps rather than running straight down.
    if (i < 6) grid[i][8] = m;
    else if (i < 8) grid[i + 1][8] = m;
    else grid[size - 15 + i][8] = m;

    // Along the top of the top-left finder, continuing at the top-right.
    if (i < 8) grid[8][size - 1 - i] = m;
    else if (i === 8) grid[8][7] = m;
    else grid[8][14 - i] = m;
  }
}

/** The penalty score the spec uses to choose a mask. Lower is better. */
function penalty(grid: Grid): number {
  const size = grid.length;
  let score = 0;

  const run = (get: (i: number, j: number) => number) => {
    for (let i = 0; i < size; i++) {
      let length = 1;
      for (let j = 1; j < size; j++) {
        if (get(i, j) === get(i, j - 1)) {
          length++;
        } else {
          if (length >= 5) score += 3 + (length - 5);
          length = 1;
        }
      }
      if (length >= 5) score += 3 + (length - 5);
    }
  };
  run((i, j) => grid[i][j] ?? 0);
  run((i, j) => grid[j][i] ?? 0);

  for (let r = 0; r < size - 1; r++) {
    for (let c = 0; c < size - 1; c++) {
      const a = grid[r][c], b = grid[r][c + 1];
      const d = grid[r + 1][c], e = grid[r + 1][c + 1];
      if (a === b && a === d && a === e) score += 3;
    }
  }

  const pattern = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0];
  const look = (get: (k: number) => number) => {
    for (let i = 0; i + 11 <= size; i++) {
      let hit = true;
      for (let k = 0; k < 11; k++) if (get(i + k) !== pattern[k]) { hit = false; break; }
      if (hit) score += 40;
    }
  };
  for (let r = 0; r < size; r++) look((k) => grid[r][k] ?? 0);
  for (let c = 0; c < size; c++) look((k) => grid[k][c] ?? 0);

  let dark = 0;
  for (let r = 0; r < size; r++) for (let c = 0; c < size; c++) dark += grid[r][c] ?? 0;
  const ratio = (dark * 100) / (size * size);
  score += Math.floor(Math.abs(ratio - 50) / 5) * 10;

  return score;
}

/** The finished module grid for `text`, or null if it cannot be encoded. */
export function qrMatrix(text: string): (0 | 1)[][] | null {
  const want = text.trim().toUpperCase();
  for (const version of [1, 2, 3, 4]) {
    const words = codewords(want, version);
    if (!words) continue;

    let best: Grid | null = null;
    let bestScore = Infinity;
    for (let mask = 0; mask < 8; mask++) {
      const { grid, taken } = skeleton(version);
      place(grid, taken, words, mask);
      writeFormat(grid, mask);
      const score = penalty(grid);
      if (score < bestScore) { bestScore = score; best = grid; }
    }
    return best!.map((row) => row.map((m) => (m ?? 0) as 0 | 1));
  }
  return null;
}

/** `text` as an SVG QR code, sized in modules with a four module quiet zone.
 *
 *  Returns "" when the text cannot be encoded, so a caller shows the
 *  characters instead of an unreadable picture.
 */
export function qrSvg(text: string): string {
  const grid = qrMatrix(text);
  if (!grid) return "";

  const size = grid.length;
  const quiet = 4;
  const span = size + quiet * 2;

  // One path for every dark module. Cheaper for a browser to draw than a
  // rectangle element each, and it scales without seams between neighbours.
  const parts: string[] = [];
  for (let r = 0; r < size; r++) {
    for (let c = 0; c < size; c++) {
      if (grid[r][c]) parts.push(`M${c + quiet} ${r + quiet}h1v1h-1z`);
    }
  }

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${span} ${span}" `
    + `shape-rendering="crispEdges" role="img">`
    + `<rect width="${span}" height="${span}" fill="#ffffff"/>`
    + `<path d="${parts.join("")}" fill="#000000"/>`
    + `</svg>`;
}
