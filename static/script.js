'use strict';
/* Hephaestus — local-first notes. Modules: Icons, Store, Md, UI, Editor, App */
(() => {
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const uid = () => Math.random().toString(36).slice(2, 9) + Date.now().toString(36).slice(-4);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pad = n => String(n).padStart(2, '0');

/* ===================== Icons (Lucide paths, inlined so it works offline) ===================== */
const Icons = (() => {
  const P = {
    sprout: '<path d="M7 20h10"/><path d="M10 20c5.5-2.5.8-6.4 3-10"/><path d="M9.5 9.4c1.1.8 1.8 2.2 2.3 3.7-2 .4-3.5.4-4.8-.3-1.2-.6-2.3-1.9-3-4.2 2.8-.5 4.4 0 5.5.8z"/><path d="M14.1 6a7 7 0 0 0-1.1 4c1.9-.1 3.3-.6 4.3-1.4 1-1 1.6-2.3 1.7-4.6-2.7.1-4 1-4.9 2z"/>',
    home: '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    star: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
    plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/>',
    settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
    bold: '<path d="M6 12h9a4 4 0 0 1 0 8H7a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h7a4 4 0 0 1 0 8"/>',
    italic: '<line x1="19" x2="10" y1="4" y2="4"/><line x1="14" x2="5" y1="20" y2="20"/><line x1="15" x2="9" y1="4" y2="20"/>',
    underline: '<path d="M6 4v6a6 6 0 0 0 12 0V4"/><line x1="4" x2="20" y1="20" y2="20"/>',
    strike: '<path d="M16 4H9a3 3 0 0 0-2.83 4"/><path d="M14 12a4 4 0 0 1 0 8H6"/><line x1="4" x2="20" y1="12" y2="12"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    image: '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
    table: '<path d="M12 3v18"/><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18M3 15h18"/>',
    'list-ordered': '<path d="M10 12h11M10 18h11M10 6h11M4 10h2M4 6h1v4M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"/>',
    'check-square': '<path d="m9 11 3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    undo: '<path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/>',
    redo: '<path d="M21 7v6h-6"/><path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6 2.3l3 2.7"/>',
    maximize: '<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3"/>',
    minimize: '<path d="M8 3v3a2 2 0 0 1-2 2H3M21 8h-3a2 2 0 0 1-2-2V3M3 16h3a2 2 0 0 1 2 2v3M16 21v-3a2 2 0 0 1 2-2h3"/>',
    'file-text': '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><path d="M14 2v4a2 2 0 0 0 2 2h4M10 9H8M16 13H8M16 17H8"/>',
    'chevron-down': '<path d="m6 9 6 6 6-6"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
    'rotate-ccw': '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    pencil: '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
    tag: '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    'arrow-left': '<path d="m12 19-7-7 7-7M19 12H5"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
  };
  const svg = (n, s = 18) => `<svg class="ic" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[n] || ''}</svg>`;
  const hydrate = (root = document) => $$('[data-icon]', root).forEach(el => { el.innerHTML = svg(el.dataset.icon, +el.dataset.size || 18); });
  return { svg, hydrate };
})();
const ic = Icons.svg;

/* ===================== Store ===================== */
const Store = (() => {
  const KEY = 'hephaestus.v1', QUOTA = 5 * 1024 * 1024;
  const day = 864e5;
  const seed = () => {
    const now = Date.now(), t = { study: uid(), work: uid(), life: uid(), other: uid() };
    const mk = (title, html, tags, ago, extra = {}) => ({ id: uid(), title, html, tags, fav: false, trashed: false, created: now - ago, updated: now - ago, ...extra });
    return {
      tags: [{ id: t.study, name: '学习', color: '#f5a524' }, { id: t.work, name: '工作', color: '#7c83e6' }, { id: t.life, name: '生活', color: '#f2c230' }, { id: t.other, name: '其他', color: '#8b8f94' }],
      notes: [
        mk('欢迎使用赫淮斯托斯', '<h2>开始记录</h2><p>这是你的第一个笔记。试试下面的功能：</p><ul class="todo"><li><input type="checkbox" checked>&nbsp;新建一篇笔记（Ctrl + N 或 Alt + N）</li><li><input type="checkbox">&nbsp;给笔记添加标签</li><li><input type="checkbox">&nbsp;用 Markdown 快捷输入：行首输入 <code>#</code> 加空格变标题</li></ul><p>所有内容保存在浏览器本地，刷新不会丢失。</p>', [t.study], 60e3, { fav: true }),
        mk('学习计划', '<h2>本周计划</h2><p>Python 是未来的核心技能，每天保持练习。</p><ol><li>语法基础与数据结构</li><li>文件与异常处理</li><li>小项目实践</li></ol>', [t.study], 3 * 36e5),
        mk('项目想法', '<p>一个有趣的项目想法：做一个本地优先的记事本，支持标签与全文搜索。</p>', [t.work], day + 36e5, { fav: true }),
        mk('生活随笔', '<p>一些日常的思考，记录下来，慢慢整理。</p>', [t.life], 3 * day),
        mk('工作备忘', '<p>下周需要完成的任务：整理需求、同步进度。</p>', [t.work], 4 * day),
        mk('读书笔记', '<p>《人类简史》读书笔记：认知革命、农业革命与科学革命。</p>', [t.other], 6 * day),
        mk('旧草稿', '<p>这篇笔记在回收站中，可以恢复。</p>', [], 9 * day, { trashed: true }),
      ],
      ui: { theme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light', layout: 'list', sort: 'updated' },
    };
  };
  let data;
  const load = () => {
    try { data = JSON.parse(localStorage.getItem(KEY)); } catch { data = null; }
    if (!data || !Array.isArray(data.notes)) data = seed();
    data.ui = { theme: 'light', layout: 'list', sort: 'updated', ...data.ui };
  };
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(data)); return true; } catch { return false; } };
  const size = () => (localStorage.getItem(KEY) || '').length * 2;
  load();
  return { get data() { return data; }, save, size, QUOTA, day };
})();

/* ===================== Markdown conversion ===================== */
const Md = (() => {
  const inline = n => {
    if (n.nodeType === 3) return n.textContent.replace(/\u00a0/g, ' ');
    if (n.nodeType !== 1) return '';
    const c = [...n.childNodes].map(inline).join('');
    switch (n.tagName) {
      case 'B': case 'STRONG': return c.trim() ? `**${c}**` : c;
      case 'I': case 'EM': return c.trim() ? `*${c}*` : c;
      case 'S': case 'STRIKE': case 'DEL': return `~~${c}~~`;
      case 'A': return `[${c}](${n.getAttribute('href') || ''})`;
      case 'IMG': return `![](${n.getAttribute('src')})`;
      case 'BR': return '\n';
      case 'CODE': return '`' + c + '`';
      case 'INPUT': return n.checked ? '[x] ' : '[ ] ';
      default: return c;
    }
  };
  const blocks = root => {
    const out = [];
    root.childNodes.forEach(n => {
      if (n.nodeType === 3) { const t = n.textContent.trim(); if (t) out.push(t); return; }
      if (n.nodeType !== 1) return;
      const t = n.tagName;
      if (/^H[1-6]$/.test(t)) out.push('#'.repeat(+t[1]) + ' ' + inline(n).trim());
      else if (t === 'UL' || t === 'OL') out.push([...n.children].map((li, i) => (t === 'OL' ? `${i + 1}. ` : '- ') + inline(li).trim()).join('\n'));
      else if (t === 'BLOCKQUOTE') out.push(inline(n).trim().split('\n').map(l => '> ' + l).join('\n'));
      else if (t === 'HR') out.push('---');
      else if (t === 'PRE') out.push('```\n' + n.textContent + '\n```');
      else if (t === 'TABLE') {
        const rows = $$('tr', n).map(tr => [...tr.children].map(td => inline(td).trim().replace(/\|/g, '\\|').replace(/\n/g, ' ')));
        if (rows.length) out.push([rows[0], rows[0].map(() => '---'), ...rows.slice(1)].map(r => '| ' + r.join(' | ') + ' |').join('\n'));
      } else if (t === 'DIV' && n.querySelector('p,div,ul,ol,h1,h2,h3,table')) out.push(blocks(n));
      else { const s = inline(n).trim(); if (s) out.push(s); }
    });
    return out.join('\n\n');
  };
  const toMd = html => { const d = document.createElement('div'); d.innerHTML = html; return blocks(d); };
  const toText = html => {
    const d = document.createElement('div'); d.style.cssText = 'position:fixed;left:-9999px;top:0;white-space:pre-wrap';
    d.innerHTML = html; $$('input[type=checkbox]', d).forEach(i => i.replaceWith(i.checked ? '[x] ' : '[ ] '));
    document.body.appendChild(d); const t = d.innerText.replace(/\u00a0/g, ' ').trim(); d.remove(); return t;
  };
  const inl = s => esc(s)
    .replace(/!\[([^\]]*)\]\(((?:https?:|data:image\/)[^)\s]+)\)/g, '<img alt="$1" src="$2">')
    .replace(/\[([^\]]+)\]\(((?:https?:|mailto:|#)[^)\s]*)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<i>$2</i>').replace(/~~(.+?)~~/g, '<s>$1</s>');
  const LI = /^\s*([-*+]|\d+\.)\s+/;
  const fromMd = src => {
    const L = src.replace(/\r/g, '').split('\n'); let h = '', i = 0, m; const para = [];
    const flush = () => { if (para.length) { h += `<p>${para.map(inl).join('<br>')}</p>`; para.length = 0; } };
    while (i < L.length) {
      const l = L[i];
      if (/^```/.test(l)) { flush(); const c = []; i++; while (i < L.length && !/^```/.test(L[i])) c.push(L[i++]); h += `<pre>${esc(c.join('\n'))}</pre>`; }
      else if ((m = l.match(/^(#{1,6})\s+(.*)/))) { flush(); const n = Math.min(m[1].length, 3); h += `<h${n}>${inl(m[2])}</h${n}>`; }
      else if (/^(-{3,}|\*{3,})\s*$/.test(l)) { flush(); h += '<hr>'; }
      else if (LI.test(l)) {
        flush(); const ord = /^\s*\d+\./.test(l); let todo = false; const items = [];
        while (i < L.length && LI.test(L[i])) {
          let t = L[i].replace(LI, ''); const k = t.match(/^\[( |x|X)\]\s*/);
          if (k) { todo = true; t = `<input type="checkbox"${k[1] !== ' ' ? ' checked' : ''}>&nbsp;` + inl(t.slice(k[0].length)); } else t = inl(t);
          items.push(`<li>${t}</li>`); i++;
        }
        i--; const tag = ord ? 'ol' : 'ul'; h += `<${tag}${todo ? ' class="todo"' : ''}>${items.join('')}</${tag}>`;
      }
      else if ((m = l.match(/^>\s?(.*)/))) { flush(); h += `<blockquote>${inl(m[1])}</blockquote>`; }
      else if (/^\|.*\|\s*$/.test(l)) {
        flush(); const rows = [];
        while (i < L.length && /^\|.*\|\s*$/.test(L[i])) { if (!/^\|[\s:|-]+\|$/.test(L[i])) rows.push(L[i].trim().slice(1, -1).split(/(?<!\\)\|/).map(c => inl(c.trim().replace(/\\\|/g, '|')))); i++; }
        i--; h += '<table><tbody>' + rows.map(r => '<tr>' + r.map(c => `<td>${c}</td>`).join('') + '</tr>').join('') + '</tbody></table><p><br></p>';
      }
      else if (!l.trim()) flush();
      else para.push(l);
      i++;
    }
    flush(); return h;
  };
  return { toMd, toText, fromMd };
})();

/* ===================== UI helpers (modal, menu, toast, confirm) ===================== */
const UI = (() => {
  const modals = []; let openMenu = null;
  const closeMenu = () => { if (openMenu) { openMenu.remove(); openMenu = null; } };
  const modal = ({ title, body, actions = [], onClose }) => {
    const back = document.createElement('div'); back.className = 'modal-back';
    back.innerHTML = `<div class="modal" role="dialog" aria-modal="true"><header><h2>${esc(title)}</h2><button class="icon-btn" data-x title="关闭">${ic('x')}</button></header><div class="m-body"></div><footer></footer></div>`;
    const mb = $('.m-body', back); typeof body === 'string' ? (mb.innerHTML = body) : mb.appendChild(body);
    const close = () => { const k = modals.indexOf(entry); if (k > -1) modals.splice(k, 1); back.remove(); onClose?.(); };
    const entry = { close };
    actions.forEach(a => {
      const b = document.createElement('button'); b.className = 'btn' + (a.kind ? ' ' + a.kind : ''); b.textContent = a.label;
      b.onclick = () => { if (!a.onClick || a.onClick(close) !== false) close(); }; $('footer', back).appendChild(b);
    });
    if (!actions.length) $('footer', back).remove();
    $('[data-x]', back).onclick = close;
    back.addEventListener('mousedown', e => { if (e.target === back) close(); });
    back.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('input') && actions.length) { e.preventDefault(); $('footer .primary', back)?.click(); } });
    document.body.appendChild(back); modals.push(entry);
    ($('input,button.primary', mb) || $('.btn.primary', back))?.focus();
    return { close, el: back };
  };
  const confirmBox = (title, msg, okLabel = '确定', kind = 'primary') => new Promise(res => {
    let done = false; const fin = v => { if (!done) { done = true; res(v); } };
    modal({ title, body: `<p>${esc(msg)}</p>`, onClose: () => fin(false), actions: [{ label: '取消' }, { label: okLabel, kind, onClick: () => fin(true) }] });
  });
  const menu = (anchor, items) => {
    closeMenu(); const m = document.createElement('div'); m.className = 'menu';
    items.forEach(it => {
      if (it === '-') return m.appendChild(document.createElement('hr'));
      const b = document.createElement('button'); b.className = it.on ? 'on' : ''; b.innerHTML = (it.icon ? ic(it.icon, 16) : '') + `<span>${esc(it.label)}</span>` + (it.on ? `<span style="margin-left:auto">${ic('check', 16)}</span>` : '');
      b.onclick = () => { closeMenu(); it.onClick(); }; m.appendChild(b);
    });
    document.body.appendChild(m); const r = anchor.getBoundingClientRect(), w = m.offsetWidth;
    m.style.top = Math.min(r.bottom + 6, innerHeight - m.offsetHeight - 8) + 'px';
    m.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + 'px'; openMenu = m;
    setTimeout(() => document.addEventListener('mousedown', function h(e) { if (!m.contains(e.target)) { closeMenu(); } document.removeEventListener('mousedown', h); }), 0);
  };
  const toast = msg => { const t = document.createElement('div'); t.className = 'toast'; t.textContent = msg; document.body.appendChild(t); setTimeout(() => t.remove(), 2200); };
  const escape = () => { if (openMenu) { closeMenu(); return true; } if (modals.length) { modals[modals.length - 1].close(); return true; } return false; };
  return { modal, confirmBox, menu, toast, escape };
})();

/* ===================== App ===================== */
const D = Store.data;
const state = { view: 'all', tag: null, q: '', sel: null };
const el = {
  app: $('#app'), main: $('#main'), nav: $('#nav'), tagList: $('#tagList'), storage: $('#storage'), list: $('#noteList'),
  search: $('#search'), listTitle: $('#listTitle'), empty: $('#empty'), editor: $('#editor'), title: $('#title'), content: $('#content'),
  noteTags: $('#noteTags'), wc: $('#wordCount'), saveState: $('#saveState'), fav: $('#favBtn'), del: $('#delBtn'), restore: $('#restoreBtn'),
  heading: $('#headingSel'), fs: $('#fsBtn'), toolbar: $('#toolbar'),
};
const now = () => Date.now();
const noteById = id => D.notes.find(n => n.id === id);
const tagById = id => D.tags.find(t => t.id === id);
const plain = html => (new DOMParser().parseFromString(html || '', 'text/html').body.textContent || '').replace(/\s+/g, ' ').trim();
const countWords = t => (t.match(/[\u4e00-\u9fff]/g) || []).length + (t.match(/[A-Za-z0-9_]+/g) || []).length;
const fmtTime = ts => {
  const d = new Date(ts), n = new Date(), dayOf = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((dayOf(n) - dayOf(d)) / 864e5), hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (diff === 0) return '今天 ' + hm; if (diff === 1) return '昨天 ' + hm;
  return d.getFullYear() === n.getFullYear() ? `${d.getMonth() + 1}月${d.getDate()}日` : `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
};
const VIEWS = [['all', 'home', '全部笔记'], ['fav', 'star', '我的收藏'], ['recent', 'clock', '最近编辑'], ['trash', 'trash', '回收站']];
const SORTS = { updated: '最近更新', created: '创建时间', title: '标题' };
const live = n => !n.trashed;
const counts = () => ({
  all: D.notes.filter(live).length, fav: D.notes.filter(n => live(n) && n.fav).length,
  recent: D.notes.filter(n => live(n) && now() - n.updated < 7 * Store.day).length, trash: D.notes.filter(n => n.trashed).length,
});
const visible = () => {
  let r = D.notes.filter(n => state.view === 'trash' ? n.trashed : live(n));
  if (state.view === 'fav') r = r.filter(n => n.fav);
  if (state.view === 'recent') r = r.filter(n => now() - n.updated < 7 * Store.day);
  if (state.tag) r = r.filter(n => n.tags.includes(state.tag));
  const q = state.q.trim().toLowerCase();
  if (q) r = r.filter(n => (n.title + ' ' + plain(n.html)).toLowerCase().includes(q));
  const s = D.ui.sort;
  return r.sort((a, b) => s === 'title' ? (a.title || '').localeCompare(b.title || '', 'zh') : b[s] - a[s]);
};

/* ---- persistence ---- */
let saveTimer = null, dirty = false;
const setStatus = t => { el.saveState.textContent = t; };
const commit = () => {
  clearTimeout(saveTimer); saveTimer = null; dirty = false;
  const ok = Store.save(); const d = new Date();
  setStatus(ok ? `已保存 ${pad(d.getHours())}:${pad(d.getMinutes())}` : '保存失败：存储空间不足（请删除大图或笔记）');
  if (!ok) UI.toast('保存失败：浏览器存储空间已满');
  renderAll(false);
};
const touch = () => { dirty = true; setStatus('保存中…'); clearTimeout(saveTimer); saveTimer = setTimeout(commit, 600); };
const flush = (manual = false) => { if (dirty || manual) { commit(); if (manual) UI.toast('已保存'); } };

/* ---- rendering ---- */
const renderNav = () => {
  const c = counts();
  el.nav.innerHTML = VIEWS.map(([id, i, label]) => `<button class="nav-item${state.view === id && !state.tag ? ' active' : ''}" data-view="${id}">${ic(i, 20)}<span>${label}</span><span class="cnt">${c[id]}</span></button>`).join('');
  el.tagList.innerHTML = D.tags.length ? D.tags.map(t => `<li><button class="tag-item${state.tag === t.id ? ' active' : ''}" data-tag="${t.id}"><span class="dot" style="background:${esc(t.color)}"></span><span>${esc(t.name)}</span><span class="cnt">${D.notes.filter(n => live(n) && n.tags.includes(t.id)).length}</span></button></li>`).join('') : '<li class="list-empty" style="padding:8px 14px;text-align:left">暂无标签</li>';
};
const renderStorage = () => {
  const used = Store.size(), pct = Math.min(100, used / Store.QUOTA * 100), f = b => b > 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' KB';
  el.storage.innerHTML = `<div class="ring" style="--p:${pct.toFixed(1)}"></div><div class="st-text"><b>存储空间</b>${f(used)} / 5 MB<div class="st-bar"><i style="width:${pct.toFixed(1)}%"></i></div></div>`;
};
const renderList = () => {
  const list = visible(), grid = D.ui.layout === 'grid';
  el.list.className = 'note-list' + (grid ? ' grid' : '');
  $$('#layoutSeg button').forEach(b => b.classList.toggle('on', b.dataset.layout === D.ui.layout));
  el.listTitle.textContent = state.tag ? `标签：${tagById(state.tag)?.name || ''}` : VIEWS.find(v => v[0] === state.view)[2];
  if (!list.length) {
    el.list.innerHTML = `<div class="list-empty">${state.q ? '没有找到匹配的笔记' : state.view === 'trash' ? '回收站是空的' : '还没有笔记，点击下方“新建笔记”开始'}</div>`; return;
  }
  el.list.innerHTML = list.map(n => {
    const dots = n.tags.map(tagById).filter(Boolean).slice(0, 3).map(t => `<span class="dot" style="background:${esc(t.color)};width:8px;height:8px" title="${esc(t.name)}"></span>`).join('');
    const acts = n.trashed
      ? `<button data-act="restore" title="恢复">${ic('rotate-ccw', 15)}</button><button class="danger" data-act="purge" title="永久删除">${ic('trash', 15)}</button>`
      : `<button class="${n.fav ? 'on' : ''}" data-act="fav" title="${n.fav ? '取消收藏' : '收藏'}">${ic('star', 15)}</button><button class="danger" data-act="del" title="删除">${ic('trash', 15)}</button>`;
    return `<article class="note-card${n.id === state.sel ? ' active' : ''}" data-id="${n.id}" tabindex="0"><span class="note-ico">${ic('file-text', 18)}</span><div class="note-body"><h3>${esc(n.title || '无标题笔记')}</h3><p>${esc(plain(n.html).slice(0, 80) || '空白笔记')}</p><div class="note-foot">${dots}<time>${fmtTime(n.updated)}</time></div></div><div class="note-acts">${acts}</div></article>`;
  }).join('');
};
const renderAll = (full = true) => { renderNav(); renderList(); renderStorage(); if (full) renderEditor(); else renderNoteMeta(); };

/* ---- editor state ---- */
const renderNoteMeta = () => {
  const n = noteById(state.sel); if (!n) return;
  el.noteTags.innerHTML = n.tags.map(tagById).filter(Boolean).map(t => `<span class="chip"><span class="dot" style="background:${esc(t.color)}"></span>${esc(t.name)}</span>`).join('') +
    (n.trashed ? '' : `<button class="chip add" id="editTagsBtn">${ic('tag', 13)}${n.tags.length ? '编辑标签' : '添加标签'}</button>`);
  el.fav.classList.toggle('on', n.fav); el.fav.innerHTML = ic('star'); el.fav.title = n.fav ? '取消收藏' : '收藏';
  el.del.innerHTML = ic(n.trashed ? 'trash' : 'trash'); el.del.title = n.trashed ? '永久删除' : '移到回收站';
  el.restore.hidden = !n.trashed; el.fav.hidden = n.trashed;
};
const updateCounters = () => {
  const t = el.content.textContent; el.wc.textContent = `${countWords(t)} 字`;
  el.content.classList.toggle('is-empty', !t.trim() && !el.content.querySelector('img,table,li,input,hr'));
};
function renderEditor() {
  const n = noteById(state.sel);
  el.empty.hidden = !!n; el.editor.hidden = !n;
  if (!n) { el.main.classList.remove('editing'); return; }
  el.title.value = n.title; el.content.innerHTML = n.html;
  const ro = n.trashed; el.title.disabled = ro; el.content.contentEditable = String(!ro);
  $$('button,select', el.toolbar).forEach(b => { if (b.id !== 'fsBtn') b.disabled = ro; });
  renderNoteMeta(); updateCounters(); setStatus(ro ? '回收站中的笔记为只读，可恢复后编辑' : '已保存');
}
const select = (id, open = true) => {
  flush(); state.sel = id; renderList(); renderEditor();
  if (open && id) el.main.classList.add('editing');
};

/* ---- note actions ---- */
const createNote = (init = {}) => {
  flush(); if (state.view === 'trash' || state.view === 'recent' || state.view === 'fav') { state.view = 'all'; }
  state.q = ''; el.search.value = '';
  const n = { id: uid(), title: '', html: '', tags: state.tag ? [state.tag] : [], fav: false, trashed: false, created: now(), updated: now(), ...init };
  D.notes.unshift(n); Store.save(); state.sel = n.id; renderAll(); el.main.classList.add('editing');
  if (!init.title && !init.html) el.title.focus(); return n;
};
const setTrash = (n, v) => { n.trashed = v; n.updated = v ? n.updated : now(); if (state.sel === n.id && v) state.sel = null; Store.save(); renderAll(); UI.toast(v ? '已移到回收站' : '已恢复笔记'); };
const purge = async n => {
  if (!(await UI.confirmBox('永久删除', `“${n.title || '无标题笔记'}”将被永久删除，无法恢复。`, '永久删除', 'danger'))) return;
  D.notes.splice(D.notes.indexOf(n), 1); if (state.sel === n.id) state.sel = null; Store.save(); renderAll();
};
const toggleFav = n => { n.fav = !n.fav; Store.save(); renderNav(); renderList(); if (state.sel === n.id) renderNoteMeta(); };
const download = (name, text, mime) => {
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type: mime + ';charset=utf-8' }));
  a.download = name.replace(/[\\/:*?"<>|]/g, '_') + (mime === 'text/markdown' ? '.md' : '.txt'); document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};
const exportNote = (n, kind) => {
  flush(); const t = n.title || '无标题笔记';
  kind === 'md' ? download(t, `# ${t}\n\n${Md.toMd(n.html)}\n`, 'text/markdown') : download(t, `${t}\n\n${Md.toText(n.html)}\n`, 'text/plain');
};
const importFiles = async files => {
  let c = 0;
  for (const f of files) {
    const txt = await f.text(), name = f.name.replace(/\.(md|markdown|txt)$/i, ''), m = txt.match(/^\s*#\s+(.+)\n?/);
    const n = { id: uid(), title: m ? m[1].trim() : name, html: Md.fromMd(m ? txt.slice(m[0].length) : txt), tags: [], fav: false, trashed: false, created: now(), updated: now() };
    D.notes.unshift(n); state.sel = n.id; c++;
  }
  if (c) { state.view = 'all'; state.tag = null; if (!Store.save()) UI.toast('导入内容过大，保存失败'); renderAll(); el.main.classList.add('editing'); UI.toast(`已导入 ${c} 篇笔记`); }
};

/* ---- tags ---- */
const PALETTE = ['#f5a524', '#7c83e6', '#f2c230', '#8b8f94', '#3fae71', '#e5677a', '#3b9ede'];
const openTagManager = () => {
  const box = document.createElement('div'); box.style.cssText = 'display:flex;flex-direction:column;gap:10px';
  const draw = () => {
    box.innerHTML = D.tags.map(t => `<div class="tag-row" data-id="${t.id}"><input type="color" value="${esc(t.color)}" aria-label="颜色"><input type="text" value="${esc(t.name)}" maxlength="12" aria-label="标签名称"><span class="cnt">${D.notes.filter(n => n.tags.includes(t.id)).length} 篇</span><button class="icon-btn" data-del title="删除标签">${ic('trash', 16)}</button></div>`).join('') +
      `<div class="tag-row" style="margin-top:6px"><input type="color" id="ntColor" value="${PALETTE[D.tags.length % PALETTE.length]}"><input type="text" id="ntName" placeholder="新标签名称" maxlength="12"><button class="btn primary" id="ntAdd" style="height:34px">添加</button></div>`;
  };
  draw();
  const addTag = () => { const name = $('#ntName', box).value.trim(); if (!name) return $('#ntName', box).focus(); if (D.tags.some(t => t.name === name)) return UI.toast('标签已存在'); D.tags.push({ id: uid(), name, color: $('#ntColor', box).value }); Store.save(); draw(); renderAll(false); };
  box.addEventListener('click', async e => {
    if (e.target.closest('#ntAdd')) return addTag();
    const row = e.target.closest('[data-id]'); if (!row || !e.target.closest('[data-del]')) return;
    const t = tagById(row.dataset.id); if (!(await UI.confirmBox('删除标签', `删除标签“${t.name}”？笔记不会被删除。`, '删除', 'danger'))) return;
    D.tags.splice(D.tags.indexOf(t), 1); D.notes.forEach(n => { n.tags = n.tags.filter(x => x !== t.id); }); if (state.tag === t.id) state.tag = null;
    Store.save(); draw(); renderAll(false);
  });
  box.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'ntName') { e.preventDefault(); e.stopPropagation(); addTag(); } });
  box.addEventListener('change', e => {
    const row = e.target.closest('[data-id]'); if (!row) return; const t = tagById(row.dataset.id);
    if (e.target.type === 'color') t.color = e.target.value;
    else { const v = e.target.value.trim(); if (!v || D.tags.some(x => x !== t && x.name === v)) { e.target.value = t.name; return; } t.name = v; }
    Store.save(); renderAll(false);
  });
  UI.modal({ title: '标签管理', body: box, actions: [{ label: '完成', kind: 'primary' }] });
};
const openNoteTags = n => {
  const box = document.createElement('div'); box.style.cssText = 'display:flex;flex-direction:column;gap:12px';
  const draw = () => {
    box.innerHTML = `<div class="chip-pick">${D.tags.map(t => `<button class="chip${n.tags.includes(t.id) ? ' on' : ''}" data-t="${t.id}"><span class="dot" style="background:${esc(t.color)}"></span>${esc(t.name)}</button>`).join('') || '<span style="color:var(--muted)">还没有标签，先创建一个</span>'}</div>
      <div class="tag-row"><input type="text" id="nn" placeholder="创建并添加新标签" maxlength="12"><button class="btn" id="nnAdd" style="height:34px">创建</button></div>`;
  };
  const touchNote = () => { n.updated = now(); Store.save(); draw(); renderAll(false); };
  draw();
  const add = () => { const name = $('#nn', box).value.trim(); if (!name) return; let t = D.tags.find(x => x.name === name); if (!t) { t = { id: uid(), name, color: PALETTE[D.tags.length % PALETTE.length] }; D.tags.push(t); } if (!n.tags.includes(t.id)) n.tags.push(t.id); touchNote(); };
  box.addEventListener('click', e => {
    const c = e.target.closest('[data-t]'); if (c) { const id = c.dataset.t; n.tags = n.tags.includes(id) ? n.tags.filter(x => x !== id) : [...n.tags, id]; return touchNote(); }
    if (e.target.closest('#nnAdd')) add();
  });
  box.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'nn') { e.preventDefault(); e.stopPropagation(); add(); } });
  UI.modal({ title: '编辑标签', body: box, actions: [{ label: '完成', kind: 'primary' }] });
};

/* ===================== Editor module ===================== */
const Editor = (() => {
  let range = null; const ed = el.content;
  document.execCommand('defaultParagraphSeparator', false, 'p');
  const inEditor = n => n && ed.contains(n.nodeType === 3 ? n.parentNode : n);
  const restore = () => { ed.focus(); if (range) { const s = getSelection(); s.removeAllRanges(); s.addRange(range); } };
  const edited = () => { const n = noteById(state.sel); if (!n || n.trashed) return; n.title = el.title.value; n.html = ed.innerHTML; n.updated = now(); updateCounters(); touch(); };
  const exec = (cmd, val) => { restore(); document.execCommand(cmd, false, val); edited(); };
  const insertHTML = html => exec('insertHTML', html);
  const syncToolbar = () => {
    const s = getSelection(); if (!s.rangeCount || !inEditor(s.anchorNode)) return;
    range = s.getRangeAt(0).cloneRange(); const e = s.anchorNode.nodeType === 3 ? s.anchorNode.parentElement : s.anchorNode;
    const h = e.closest('h1,h2,h3'); el.heading.value = h ? h.tagName.toLowerCase() : '';
    ['bold', 'italic', 'underline', 'strikeThrough'].forEach(c => $(`[data-cmd=${c}]`)?.classList.toggle('on', document.queryCommandState(c)));
  };
  const compress = file => new Promise((res, rej) => {
    const r = new FileReader(); r.onerror = rej;
    r.onload = () => { const img = new Image(); img.onerror = rej; img.onload = () => {
      const k = Math.min(1, 1200 / img.width), c = document.createElement('canvas'); c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height); g.drawImage(img, 0, 0, c.width, c.height); res(c.toDataURL('image/jpeg', .82));
    }; img.src = r.result; }; r.readAsDataURL(file);
  });
  const insertImage = async f => { try { insertHTML(`<img src="${await compress(f)}" alt="">`); } catch { UI.toast('图片读取失败'); } };
  const linkDialog = () => {
    restore(); const saved = range, sel = String(getSelection());
    const body = document.createElement('div'); body.innerHTML = `<label class="field">链接地址<input type="url" id="lu" placeholder="https://" value="https://"></label><label class="field">显示文字（可选）<input type="text" id="lt" value="${esc(sel)}"></label>`;
    UI.modal({ title: '插入超链接', body, actions: [{ label: '取消' }, { label: '插入', kind: 'primary', onClick: () => {
      let u = $('#lu', body).value.trim(); if (!u) return false; if (!/^(https?:|mailto:|#)/i.test(u)) u = 'https://' + u;
      const t = $('#lt', body).value.trim() || u; range = saved; insertHTML(`<a href="${esc(u)}" target="_blank" rel="noopener">${esc(t)}</a>&nbsp;`);
    } }] });
  };
  const tableDialog = () => {
    restore(); const saved = range, body = document.createElement('div');
    body.innerHTML = '<div class="row"><label class="field">行数<input type="number" id="tr" min="1" max="20" value="3"></label><label class="field">列数<input type="number" id="tc" min="1" max="8" value="3"></label></div><p style="color:var(--muted);font-size:12.5px">第一行将作为表头样式显示。</p>';
    UI.modal({ title: '插入表格', body, actions: [{ label: '取消' }, { label: '插入', kind: 'primary', onClick: () => {
      const r = Math.min(20, Math.max(1, +$('#tr', body).value || 3)), c = Math.min(8, Math.max(1, +$('#tc', body).value || 3));
      range = saved; insertHTML('<table><tbody>' + `<tr>${'<td><br></td>'.repeat(c)}</tr>`.repeat(r) + '</tbody></table><p><br></p>');
    } }] });
  };
  const toggleFs = () => { const on = el.app.classList.toggle('fs'); el.fs.innerHTML = ic(on ? 'minimize' : 'maximize'); el.fs.title = on ? '退出全屏' : '全屏编辑'; };
  const run = c => ({
    bold: () => exec('bold'), italic: () => exec('italic'), underline: () => exec('underline'), strikeThrough: () => exec('strikeThrough'),
    ol: () => exec('insertOrderedList'), ul: () => exec('insertUnorderedList'), undo: () => exec('undo'), redo: () => exec('redo'),
    task: () => insertHTML('<ul class="todo"><li><input type="checkbox">&nbsp;</li></ul>'),
    link: linkDialog, table: tableDialog, image: () => { restore(); $('#imgInput').click(); }, fullscreen: toggleFs,
  }[c]?.());

  el.toolbar.addEventListener('mousedown', e => { if (e.target.closest('button')) e.preventDefault(); });
  el.toolbar.addEventListener('click', e => { const b = e.target.closest('[data-cmd]'); if (b) run(b.dataset.cmd); });
  el.heading.addEventListener('change', () => exec('formatBlock', el.heading.value ? `<${el.heading.value}>` : '<p>'));
  $('#imgInput').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; if (f) insertImage(f); });
  document.addEventListener('selectionchange', syncToolbar);
  el.title.addEventListener('input', edited);
  el.title.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); ed.focus(); } });

  /* Markdown shortcuts: type marker + space at line start */
  const MD = [[/^(#{1,3})[ \u00a0]$/, m => ['formatBlock', `<h${m[1].length}>`]], [/^[-*+][ \u00a0]$/, () => ['insertUnorderedList']], [/^1\.[ \u00a0]$/, () => ['insertOrderedList']],
    [/^>[ \u00a0]$/, () => ['formatBlock', '<blockquote>']], [/^\[\][ \u00a0]$/, () => ['task']]];
  const mdShortcut = () => {
    const s = getSelection(); if (!s.rangeCount || s.anchorNode.nodeType !== 3 || !inEditor(s.anchorNode)) return;
    const node = s.anchorNode, text = node.textContent;
    for (const [re, f] of MD) { const m = text.match(re); if (m && s.anchorOffset === text.length) {
      const r = document.createRange(); r.selectNodeContents(node); s.removeAllRanges(); s.addRange(r); document.execCommand('delete');
      const [cmd, val] = f(m); cmd === 'task' ? document.execCommand('insertHTML', false, '<ul class="todo"><li><input type="checkbox">&nbsp;</li></ul>') : document.execCommand(cmd, false, val); return;
    } }
  };
  ed.addEventListener('input', e => { if (e.inputType === 'insertText' && e.data === ' ') mdShortcut(); edited(); });
  ed.addEventListener('change', e => { if (e.target.matches('input[type=checkbox]')) { e.target.toggleAttribute('checked', e.target.checked); edited(); } });
  ed.addEventListener('click', e => { const a = e.target.closest('a'); if (a && (e.ctrlKey || e.metaKey)) window.open(a.href, '_blank', 'noopener'); });
  ed.addEventListener('paste', e => {
    e.preventDefault(); const cd = e.clipboardData, f = [...cd.files].find(x => x.type.startsWith('image/'));
    if (f) insertImage(f); else document.execCommand('insertText', false, cd.getData('text/plain')); edited();
  });
  ed.addEventListener('keydown', e => {
    if (e.key !== 'Enter' || e.shiftKey) return; const s = getSelection(); if (!s.rangeCount) return;
    const x = s.anchorNode.nodeType === 3 ? s.anchorNode.parentElement : s.anchorNode, li = x.closest?.('ul.todo > li'); if (!li) return;
    e.preventDefault(); const caret = node => { const r = document.createRange(); r.selectNodeContents(node); r.collapse(false); s.removeAllRanges(); s.addRange(r); };
    if (!li.textContent.replace(/[\u00a0\s]/g, '')) {
      const ul = li.parentElement, p = document.createElement('p'); p.innerHTML = '<br>'; ul.after(p); li.remove(); if (!ul.children.length) ul.remove(); caret(p);
    } else { const nl = document.createElement('li'); nl.innerHTML = '<input type="checkbox">&nbsp;'; li.after(nl); caret(nl); }
    edited();
  });
  return { exec, toggleFs, edited };
})();

/* ===================== Wiring ===================== */
const closeDrawer = () => el.app.classList.remove('nav-open');
const go = (view, tag = null) => { flush(); state.view = view; state.tag = tag; closeDrawer(); const vis = visible(); if (!vis.some(n => n.id === state.sel)) { state.sel = null; el.main.classList.remove('editing'); } renderAll(); };

el.nav.addEventListener('click', e => { const b = e.target.closest('[data-view]'); if (b) go(b.dataset.view); });
el.tagList.addEventListener('click', e => { const b = e.target.closest('[data-tag]'); if (b) go('all', state.tag === b.dataset.tag ? null : b.dataset.tag); });
$('#tagManageBtn').onclick = openTagManager;
$('#menuBtn').onclick = () => el.app.classList.add('nav-open');
$('#scrim').onclick = closeDrawer;
$('#backBtn').onclick = () => { flush(); el.main.classList.remove('editing'); };
$('#newBar').onclick = () => createNote();
$('#emptyNew').onclick = () => createNote();
$$('#layoutSeg button').forEach(b => b.onclick = () => { D.ui.layout = b.dataset.layout; Store.save(); renderList(); });
$('#sortBtn').onclick = e => UI.menu(e.currentTarget, Object.entries(SORTS).map(([k, v]) => ({ label: '按' + v + '排序', on: D.ui.sort === k, onClick: () => { D.ui.sort = k; Store.save(); renderList(); } })));
el.search.addEventListener('input', () => { state.q = el.search.value; renderList(); });

el.list.addEventListener('click', e => {
  const card = e.target.closest('.note-card'); if (!card) return; const n = noteById(card.dataset.id), a = e.target.closest('[data-act]');
  if (!a) return select(n.id);
  e.stopPropagation(); ({ fav: () => toggleFav(n), del: () => setTrash(n, true), restore: () => setTrash(n, false), purge: () => purge(n) })[a.dataset.act]();
});
el.list.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('.note-card')) select(e.target.dataset.id); });

el.fav.onclick = () => { const n = noteById(state.sel); if (n) toggleFav(n); };
el.del.onclick = () => { const n = noteById(state.sel); if (n) n.trashed ? purge(n) : setTrash(n, true); };
el.restore.onclick = () => { const n = noteById(state.sel); if (n) setTrash(n, false); };
$('#exportBtn').onclick = e => { const n = noteById(state.sel); if (n) UI.menu(e.currentTarget, [{ label: '导出为 Markdown', icon: 'file-text', onClick: () => exportNote(n, 'md') }, { label: '导出为 TXT', icon: 'file-text', onClick: () => exportNote(n, 'txt') }]); };
el.noteTags.addEventListener('click', e => { if (e.target.closest('#editTagsBtn')) { const n = noteById(state.sel); if (n) openNoteTags(n); } });

const applyTheme = () => { document.documentElement.dataset.theme = D.ui.theme; $('#themeBtn').innerHTML = ic(D.ui.theme === 'dark' ? 'sun' : 'moon', 20); };
$('#themeBtn').onclick = () => { D.ui.theme = D.ui.theme === 'dark' ? 'light' : 'dark'; Store.save(); applyTheme(); };
$('#moreBtn').onclick = e => UI.menu(e.currentTarget, [
  { label: '新建笔记', icon: 'plus', onClick: () => createNote() },
  { label: '导入 Markdown 文件', icon: 'upload', onClick: () => $('#mdInput').click() },
  { label: '标签管理', icon: 'tag', onClick: openTagManager },
  '-',
  { label: '清空回收站', icon: 'trash', onClick: async () => {
    const c = D.notes.filter(n => n.trashed).length; if (!c) return UI.toast('回收站是空的');
    if (await UI.confirmBox('清空回收站', `将永久删除 ${c} 篇笔记，无法恢复。`, '清空', 'danger')) { D.notes = D.notes.filter(n => !n.trashed); if (!noteById(state.sel)) state.sel = null; Store.save(); renderAll(); }
  } },
]);
$('#mdInput').addEventListener('change', e => { importFiles([...e.target.files]); e.target.value = ''; });

document.addEventListener('keydown', e => {
  const k = e.key.toLowerCase(), mod = e.ctrlKey || e.metaKey;
  if ((mod || e.altKey) && k === 'n') { e.preventDefault(); createNote(); }
  else if (mod && k === 'k') { e.preventDefault(); el.main.classList.remove('editing'); el.search.focus(); el.search.select(); }
  else if (mod && k === 's') { e.preventDefault(); if (state.sel) flush(true); }
  else if (mod && (k === 'b' || k === 'i') && el.content.contains(document.activeElement)) { e.preventDefault(); Editor.exec(k === 'b' ? 'bold' : 'italic'); }
  else if (k === 'escape') {
    if (UI.escape()) return;
    if (document.activeElement === el.search || state.q) { el.search.value = ''; state.q = ''; el.search.blur(); renderList(); }
    else if (el.app.classList.contains('fs')) Editor.toggleFs();
    else closeDrawer();
  }
});
window.addEventListener('beforeunload', () => { if (dirty) Store.save(); });
window.addEventListener('pagehide', () => { if (dirty) Store.save(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) flush(); });

/* ===================== Boot ===================== */
Icons.hydrate(); applyTheme();
state.sel = null; renderAll();
})();
