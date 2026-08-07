// Entry for the vendored CodeMirror bundle used by trace_viewer.js.
// Rebuild with:
//   npm i @codemirror/state@6 @codemirror/view@6 @codemirror/language@6 \
//         @codemirror/lang-json@6 @codemirror/commands@6 @lezer/highlight@1 esbuild
//   npx esbuild cm-entry.js --bundle --format=esm --minify \
//       --outfile=../../qym_platform/_static/dashboard/codemirror-bundle.js
export * as state from "@codemirror/state";
export * as view from "@codemirror/view";
export * as language from "@codemirror/language";
export * as langJson from "@codemirror/lang-json";
export * as commands from "@codemirror/commands";
export * as highlight from "@lezer/highlight";