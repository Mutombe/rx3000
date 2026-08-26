import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** Put the barcode decoder's WebAssembly where we serve it ourselves.
 *
 *  `zxing-wasm` fetches its module from a CDN unless told otherwise, which
 *  would make camera scanning the one feature that stops working when the
 *  internet does — in a product whose entire argument to a pharmacy is that it
 *  keeps trading when the line is down, and which ships as a desktop app that
 *  may never see the internet at all.
 *
 *  The file is read straight off disk rather than imported, because the
 *  package's export map does not expose it and a deep import fails the build.
 *  Copying it into `public/` on every build also means it cannot drift from the
 *  installed version the way a committed copy would.
 */
function bundleDecoderWasm() {
  return {
    name: "rx3000-bundle-decoder-wasm",
    buildStart() {
      const from = resolve(__dirname, "node_modules/zxing-wasm/dist/reader/zxing_reader.wasm");
      if (!existsSync(from)) {
        // Loud, because the alternative is a camera that silently reaches for
        // a CDN in a pharmacy with no internet.
        throw new Error(
          "zxing_reader.wasm is missing. Run npm install — camera scanning "
          + "cannot work without it, and must not fall back to a CDN.",
        );
      }
      mkdirSync(resolve(__dirname, "public"), { recursive: true });
      copyFileSync(from, resolve(__dirname, "public/zxing_reader.wasm"));
    },
  };
}

export default defineConfig({
  plugins: [react(), bundleDecoderWasm()],
  server: {
    // Overridable so a second dev server can be run against a second backend.
    // Hard-coding both meant that when a stale uvicorn held 8177 there was no way
    // to check anything in a browser without killing somebody else's process.
    port: Number(process.env.RX5000_PORT ?? process.env.RX3000_PORT ?? 5180),
    strictPort: true,
    proxy: {
      "/api": process.env.RX5000_API ?? process.env.RX3000_API ?? "http://localhost:8177",
    },
  },
});
