import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const buildRoot = path.resolve(__dirname, "..", "build");

if (!fs.existsSync(buildRoot)) {
  process.exit(0);
}

const runtimePrefix = `window.__QYM_DOCS_BASE_URL__=(function(){var p=window.location.pathname;var m=p.match(/^(.*?\\/docs)(?:\\/|$)/);return m?m[1]+"/":"/docs/";})();window.__QYM_DOCS_REWRITE_URL__=function(value){if(value==null){return value;}if(typeof value!=="string"){return value;}if(!value.startsWith("/docs")||window.__QYM_DOCS_BASE_URL__==="/docs/"){return value;}var suffix=value.replace(/^\\/docs\\/?/,"");return window.__QYM_DOCS_BASE_URL__+suffix;};`;
const historyPatch = `history.pushState=(function(orig){return function(state,title,url){return orig.call(this,state,title,window.__QYM_DOCS_REWRITE_URL__(url));};})(history.pushState);history.replaceState=(function(orig){return function(state,title,url){return orig.call(this,state,title,window.__QYM_DOCS_REWRITE_URL__(url));};})(history.replaceState);`;
const navigationPatch = `document.addEventListener("click",function(e){var a=e.target&&e.target.closest?e.target.closest("a[href]"):null;if(!a){return;}var href=a.getAttribute("href");if(!href||href.startsWith("#")||href.startsWith("mailto:")||href.startsWith("tel:")){return;}if(/^[a-z]+:/i.test(href)&&!href.startsWith(window.location.origin)){return;}var u=new URL(href,window.location.origin);if(!u.pathname.startsWith("/docs/")&&u.pathname!=="/docs"){return;}if(window.__QYM_DOCS_BASE_URL__==="/docs/"){return;}e.preventDefault();var next=window.__QYM_DOCS_REWRITE_URL__(u.pathname);if(u.search){next+=u.search;}if(u.hash){next+=u.hash;}window.location.assign(next);},true);`;
const canonicalPatch = `document.addEventListener("DOMContentLoaded",function(){document.querySelectorAll('a[href]').forEach(function(link){var href=link.getAttribute("href")||"";if(href.startsWith("/docs")&&window.__QYM_DOCS_BASE_URL__!=="/docs/"){link.setAttribute("href",window.__QYM_DOCS_REWRITE_URL__(href));}});var rels=["canonical","alternate"];rels.forEach(function(rel){document.querySelectorAll('link[rel="'+rel+'"]').forEach(function(link){var href=link.getAttribute("href")||"";if(href.startsWith("/docs/")||href==="/docs"){link.setAttribute("href",window.__QYM_DOCS_REWRITE_URL__(href));}});});document.querySelectorAll('meta[property="og:url"],meta[name="twitter:url"]').forEach(function(meta){var content=meta.getAttribute("content")||"";if(content.includes("/docs/")){meta.setAttribute("content",window.location.origin+window.__QYM_DOCS_REWRITE_URL__("/docs/"+content.replace(/^.*\\/docs\\/?/,"")));}});});`;
const bootstrapScript = `<script>${runtimePrefix}${historyPatch}${navigationPatch}${canonicalPatch}</script>`;

function walk(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(fullPath);
      continue;
    }
    if (entry.isFile()) {
      rewriteFile(fullPath);
    }
  }
}

function relativePrefix(filePath) {
  const relativeDir = path.relative(buildRoot, path.dirname(filePath));
  if (!relativeDir) {
    return "./";
  }
  const depth = relativeDir.split(path.sep).filter(Boolean).length;
  return "../".repeat(depth);
}

function replaceAbsoluteDocsPaths(content, prefix) {
  return content
    .replace(/(["'(])\/docs\//g, `$1${prefix}`)
    .replace(/(["'(])\/docs"/g, `$1${prefix}"`)
    .replace(/https:\/\/docs\.qym\.local\/docs\//g, prefix)
    .replace(/https:\/\/docs\.qym\.local\/docs\b/g, prefix);
}

function rewriteHtml(filePath) {
  const prefix = relativePrefix(filePath);
  let content = fs.readFileSync(filePath, "utf8");
  content = replaceAbsoluteDocsPaths(content, prefix);
  if (!content.includes("window.__QYM_DOCS_BASE_URL__")) {
    content = content.replace("</head>", `${bootstrapScript}</head>`);
  }
  fs.writeFileSync(filePath, content, "utf8");
}

function rewriteJs(filePath) {
  let content = fs.readFileSync(filePath, "utf8");
  content = content.replace(
    /([A-Za-z_$][\w$]*)\.p="\/docs\/"/g,
    `$1.p=(window.__QYM_DOCS_BASE_URL__||"/docs/")`
  );
  fs.writeFileSync(filePath, content, "utf8");
}

function rewriteCss(filePath) {
  const prefix = relativePrefix(filePath);
  const content = replaceAbsoluteDocsPaths(fs.readFileSync(filePath, "utf8"), prefix);
  fs.writeFileSync(filePath, content, "utf8");
}

function rewriteFile(filePath) {
  if (filePath.endsWith(".html")) {
    rewriteHtml(filePath);
    return;
  }
  if (filePath.endsWith(".js")) {
    rewriteJs(filePath);
    return;
  }
  if (filePath.endsWith(".css")) {
    rewriteCss(filePath);
  }
}

walk(buildRoot);
