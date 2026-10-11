/* ============================================================
   Restricted Markdown for notes (R-62)

   The "evidence or notes" fields and a checkpoint's rationale accept a small
   subset of Markdown: **bold**, *italic* (or _italic_), "- " and "1. " lists,
   and [text](https://address) links. Nothing else is formatting. In particular
   no raw HTML, no images, no tables and no headings: a line that looks like
   one is shown as the text it is.

   The text stays what the person typed. It is parsed into a small tree (blocks
   of inline runs), and BOTH outputs are written from that tree, never from the
   source: mdHTML() escapes every run, and mdMarkdown() writes the subset back
   with every other character escaped. So a value cannot reach either output as
   anything the parser did not build, whatever it contains. A link's address
   goes through safeUrl() (http and https only) and is always printed beside the
   link, so a reader sees where a click goes.

   Bounded: only the first MD_MAX_CHARS characters are parsed (the rest is shown
   as plain text), and nesting stops at MD_MAX_DEPTH.
   ============================================================ */
const MD_MAX_CHARS = 50000;
const MD_MAX_DEPTH = 3;
const MdKind = Object.freeze({
  TEXT: "text", STRONG: "strong", EM: "em", LINK: "link", BREAK: "break",
});
const MdBlock = Object.freeze({ PARA: "para", UL: "ul", OL: "ol" });

const MD_UL_ITEM = /^ {0,3}[-*+] +(\S.*)$/;
const MD_OL_ITEM = /^ {0,3}\d{1,9}[.)] +(\S.*)$/;
const MD_LINK = /^\[([^\[\]\n]{1,300})\]\(([^()\s]{1,2000})\)/;
const MD_STRONG = /^\*\*(?=\S)([^\n]*?\S)\*\*(?!\*)/;
const MD_EM_STAR = /^\*(?=[^\s*])([^*\n]*?[^\s*])\*(?!\*)/;
const MD_EM_UNDER = /^_(?=[^\s_])([^_\n]*?[^\s_])_(?![A-Za-z0-9])/;
const MD_ESCAPABLE = /^\\([\\`*_\[\]()<>|!~#+\-.{}])/;

/* Inline runs of one line (or several joined by BREAK). */
function mdInline(src, depth){
  const out = [];
  let text = "";
  const flush = () => { if(text){ out.push({kind: MdKind.TEXT, text}); text = ""; } };
  let i = 0;
  while(i < src.length){
    const rest = src.slice(i);
    const prev = i ? src[i - 1] : "";
    let m;
    if(rest[0] === "\n"){ flush(); out.push({kind: MdKind.BREAK}); i++; continue; }
    if((m = MD_ESCAPABLE.exec(rest))){ text += m[1]; i += m[0].length; continue; }
    if(rest[0] === "[" && depth < MD_MAX_DEPTH && (m = MD_LINK.exec(rest))){
      const url = safeUrl(m[2]);
      if(url){ flush(); out.push({kind: MdKind.LINK, text: m[1], url}); i += m[0].length; continue; }
    }
    if(rest[0] === "*" && depth < MD_MAX_DEPTH){
      if((m = MD_STRONG.exec(rest))){ flush(); out.push({kind: MdKind.STRONG, children: mdInline(m[1], depth + 1)}); i += m[0].length; continue; }
      if((m = MD_EM_STAR.exec(rest))){ flush(); out.push({kind: MdKind.EM, children: mdInline(m[1], depth + 1)}); i += m[0].length; continue; }
    }
    if(rest[0] === "_" && !/[A-Za-z0-9]/.test(prev) && depth < MD_MAX_DEPTH && (m = MD_EM_UNDER.exec(rest))){
      flush(); out.push({kind: MdKind.EM, children: mdInline(m[1], depth + 1)}); i += m[0].length; continue;
    }
    text += src[i]; i++;
  }
  flush();
  return out;
}

/* The tree: an array of {block, items|inline}. */
function mdParse(source){
  const all = String(source ?? "").replace(/\r\n?|\u2028|\u2029/g, "\n");
  const head = all.slice(0, MD_MAX_CHARS);
  const tail = all.slice(MD_MAX_CHARS);
  const blocks = [];
  let para = [];
  let list = null;
  const endPara = () => { if(para.length){ blocks.push({block: MdBlock.PARA, inline: mdInline(para.join("\n"), 0)}); para = []; } };
  const endList = () => { if(list){ blocks.push(list); list = null; } };
  for(const line of head.split("\n")){
    let m;
    if(!line.trim()){ endPara(); endList(); continue; }
    if((m = MD_UL_ITEM.exec(line))){ endPara(); if(!list || list.block !== MdBlock.UL){ endList(); list = {block: MdBlock.UL, items: []}; } list.items.push(mdInline(m[1], 0)); continue; }
    if((m = MD_OL_ITEM.exec(line))){ endPara(); if(!list || list.block !== MdBlock.OL){ endList(); list = {block: MdBlock.OL, items: []}; } list.items.push(mdInline(m[1], 0)); continue; }
    endList();
    para.push(line);
  }
  endPara(); endList();
  if(tail){ blocks.push({block: MdBlock.PARA, inline: [{kind: MdKind.TEXT, text: tail}]}); }
  return blocks;
}

/* Whether the text uses any formatting, so an editor can show a preview only
   when there is something to preview. */
function mdHasMarkup(source){
  const plain = n => n.kind === MdKind.TEXT || n.kind === MdKind.BREAK;
  return mdParse(source).some(b => b.block !== MdBlock.PARA || b.inline.some(n => !plain(n)));
}

/* ---- HTML ----------------------------------------------------------- */
function mdRunHTML(nodes){
  return nodes.map(n => {
    switch(n.kind){
      case MdKind.TEXT: return esc(n.text);
      case MdKind.BREAK: return "<br>";
      case MdKind.STRONG: return `<strong>${mdRunHTML(n.children)}</strong>`;
      case MdKind.EM: return `<em>${mdRunHTML(n.children)}</em>`;
      case MdKind.LINK: return `<a href="${esc(n.url)}" target="_blank" rel="noopener noreferrer nofollow">${esc(n.text)}</a>${n.text === n.url ? "" : ` <span class="md-url">(${esc(n.url)})</span>`}`;  // url-ok: the address went through safeUrl() when the tree was built
      default: return assertNever(n.kind);
    }
  }).join("");
}
function mdHTML(source){
  return mdParse(source).map(b => {
    switch(b.block){
      case MdBlock.PARA: return `<p><bdi>${mdRunHTML(b.inline)}</bdi></p>`;
      case MdBlock.UL: return `<ul>${b.items.map(i => `<li><bdi>${mdRunHTML(i)}</bdi></li>`).join("")}</ul>`;
      case MdBlock.OL: return `<ol>${b.items.map(i => `<li><bdi>${mdRunHTML(i)}</bdi></li>`).join("")}</ol>`;
      default: return assertNever(b.block);
    }
  }).join("");
}

/* ---- Markdown ------------------------------------------------------- */
const MD_SPECIAL = /[\\`*_\[\]()<>|!~]/g;
const mdEscape = s => stripAddressCredentials(String(s)).text.replace(MD_SPECIAL, c => "\\" + c);  // credentials never reach the report (R-70)
const MD_URL_ESCAPE = Object.freeze({ "<": "%3C", ">": "%3E", "(": "%28", ")": "%29" });

function mdRunMarkdown(nodes, joiner){
  return nodes.map(n => {
    switch(n.kind){
      case MdKind.TEXT: return mdEscape(n.text);
      case MdKind.BREAK: return joiner;
      case MdKind.STRONG: return `**${mdRunMarkdown(n.children, joiner)}**`;
      case MdKind.EM: return `*${mdRunMarkdown(n.children, joiner)}*`;
      case MdKind.LINK: {
        const url = n.url.replace(/[<>()]/g, c => MD_URL_ESCAPE[c]);
        return `[${mdEscape(n.text)}](${url})${n.text === n.url ? "" : ` ${mdEscape(`(${n.url})`)}`}`;
      }
      default: return assertNever(n.kind);
    }
  }).join("");
}

/* On one line, for a table cell or a bullet: blocks and list items run
   together with a visible separator, never a newline. */
function mdInlineMarkdown(source){
  // The raw text first (a link's address can only be seen there), then every run
  // again in mdEscape, where a backslash escape has been resolved (R-70).
  return mdParse(stripAddressCredentials(String(source ?? "")).text).map(b => {
    switch(b.block){
      case MdBlock.PARA: return mdRunMarkdown(b.inline, " ");
      case MdBlock.UL: case MdBlock.OL: return b.items.map(i => "• " + mdRunMarkdown(i, " ")).join(" ");
      default: return assertNever(b.block);
    }
  }).join(" ").replace(/[\u2028\u2029]/g, " ");
}

/* ---- the editor ------------------------------------------------------ */
/* Under a notes field: what formatting is accepted, and, when the text uses
   any, how it will read. Hidden for plain text, so most notes show nothing new. */
function mdPreviewHTML(source){
  const on = mdHasMarkup(source);
  return `<div class="md-help"><span class="md-hint">${esc(t("md.hint"))}</span>`
    + `<div class="md-preview md" data-mdpreview${on ? "" : " hidden"} aria-label="${esc(t("md.preview"))}">${on ? mdHTML(source) : ""}</div></div>`;
}
function updateMdPreview(el){
  const box = el.parentElement && el.parentElement.querySelector("[data-mdpreview]");
  if(!box) return;
  const on = mdHasMarkup(el.value);
  box.hidden = !on;
  box.innerHTML = on ? mdHTML(el.value) : "";  // xss-ok: written from the parsed tree, every run escaped (R-62)
}
