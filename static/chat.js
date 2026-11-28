/* Hephaestus V2 C3 — AI chat workspace.
 *
 * The note UI stays in script.js. This module only uses the DataPort for all
 * network access, keeps the capability token in memory (DataPort handles it),
 * and never writes chat history to localStorage.
 */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.HephaestusChat = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  'use strict';

  const STYLE_OPTIONS = [
    { value: 'professional', label: '专业严谨', hint: '准确、结构化，先结论后论据' },
    { value: 'concise', label: '简洁直接', hint: '少客套，直接给出可执行答案' },
    { value: 'friendly', label: '友好自然', hint: '像可靠的同事，温和但不啰嗦' },
    { value: 'academic', label: '学术研究', hint: '概念、证据与边界条件并重' },
    { value: 'creative', label: '创意探索', hint: '多给方向，鼓励发散与联想' },
    { value: 'custom', label: '自定义', hint: '以下方自定义提示词为主' },
  ];
  const LENGTH_LABELS = { short: '简短', medium: '适中', long: '详细' };
  const DEFAULT_PERSONA = {
    assistant_name: '赫淮斯托斯',
    assistant_style: 'friendly',
    response_length: 'medium',
    assistant_custom_prompt: '',
  };

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function safeHref(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    if (/^https?:\/\//i.test(raw)) return raw;
    if (/^mailto:/i.test(raw)) return raw;
    if (raw.startsWith('#')) return raw;
    return '';
  }

  function uid(prefix) {
    const random = (root.crypto && root.crypto.randomUUID)
      ? root.crypto.randomUUID()
      : Math.random().toString(36).slice(2) + Date.now().toString(36);
    return (prefix || 'id') + '-' + random;
  }

  const KEYWORDS = new Set(('abstract as async await break case catch class const continue def default delete do else elif except export extends false finally for from function global if import in instanceof interface lambda let new none nonlocal not null of pass raise return static super switch this throw true try typeof undefined var void while with yield').split(' '));

  function highlightCode(code, language) {
    const lang = String(language || '').toLowerCase();
    if (!lang || lang === 'text' || lang === 'plaintext') return escapeHtml(code);
    const pattern = /("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\x60(?:\\.|[^\x60\\])*\x60|\/\/[^\n]*|#[^\n]*|\/\*[\s\S]*?\*\/|\b[A-Za-z_$][\w$]*\b|\b\d+(?:\.\d+)?\b)/g;
    let out = '';
    let last = 0;
    String(code).replace(pattern, (match, offset) => {
      out += escapeHtml(String(code).slice(last, offset));
      let cls = '';
      if (match.startsWith('//') || match.startsWith('#') || match.startsWith('/*')) cls = 'tok-com';
      else if (/^["'\x60]/.test(match)) cls = 'tok-str';
      else if (/^\d/.test(match)) cls = 'tok-num';
      else if (KEYWORDS.has(match)) cls = 'tok-key';
      out += cls ? '<span class="' + cls + '">' + escapeHtml(match) + '</span>' : escapeHtml(match);
      last = offset + match.length;
      return match;
    });
    out += escapeHtml(String(code).slice(last));
    return out;
  }

  function codeBlock(code, language) {
    const lang = String(language || 'code').toLowerCase();
    return '<div class="code-block"><div class="code-head"><span>' + escapeHtml(lang) +
      '</span><button class="code-copy" type="button" data-code="' + encodeURIComponent(String(code)) +
      '" aria-label="复制代码">复制</button></div><pre><code>' + highlightCode(code, lang) + '</code></pre></div>';
  }

  function renderInline(raw) {
    let text = escapeHtml(raw);
    const codes = [];
    text = text.replace(/\x60([^\x60\n]+)\x60/g, (_, code) => {
      const token = '\u0000C' + codes.length + '\u0000';
      codes.push('<code>' + code + '</code>');
      return token;
    });
    text = text.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label, href) => {
      const safe = safeHref(href);
      if (!safe) return label;
      return '<a href="' + escapeHtml(safe) + '" target="_blank" rel="noopener noreferrer nofollow">' + label + '</a>';
    });
    text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/~~([^~]+)~~/g, '<del>$1</del>');
    text = text.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    text = text.replace(/\u0000C(\d+)\u0000/g, (_, index) => codes[Number(index)] || '');
    return text;
  }

  function isBlockStart(line) {
    return /^\s*(#{1,3})\s+/.test(line)
      || /^\s*\x60\x60\x60/.test(line)
      || /^\s*>\s?/.test(line)
      || /^\s*([-*+]|\d+[.)])\s+/.test(line)
      || /^\s*(---|\*\*\*|___)\s*$/.test(line);
  }

  function renderMarkdown(markdown) {
    const lines = String(markdown == null ? '' : markdown).replace(/\r\n?/g, '\n').split('\n');
    const out = [];
    let index = 0;
    let list = null;
    const closeList = () => {
      if (list) { out.push('</' + list + '>'); list = null; }
    };
    while (index < lines.length) {
      const line = lines[index];
      if (/^\s*\x60\x60\x60/.test(line)) {
        closeList();
        const language = line.replace(/^\s*\x60\x60\x60/, '').trim();
        const code = [];
        index += 1;
        while (index < lines.length && !/^\s*\x60\x60\x60/.test(lines[index])) {
          code.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        out.push(codeBlock(code.join('\n'), language));
        continue;
      }
      if (!line.trim()) { closeList(); index += 1; continue; }
      const heading = line.match(/^\s*(#{1,3})\s+(.+)$/);
      if (heading) {
        closeList();
        const level = heading[1].length;
        out.push('<h' + level + '>' + renderInline(heading[2].trim()) + '</h' + level + '>');
        index += 1;
        continue;
      }
      if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) { closeList(); out.push('<hr>'); index += 1; continue; }
      if (/^\s*>\s?/.test(line)) {
        closeList();
        const quote = [];
        while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
          quote.push(lines[index].replace(/^\s*>\s?/, ''));
          index += 1;
        }
        out.push('<blockquote>' + quote.map(renderInline).join('<br>') + '</blockquote>');
        continue;
      }
      const bullet = line.match(/^\s*[-*+]\s+(.+)$/);
      const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
      if (bullet || ordered) {
        const type = bullet ? 'ul' : 'ol';
        if (list !== type) { closeList(); out.push('<' + type + '>'); list = type; }
        out.push('<li>' + renderInline((bullet || ordered)[1]) + '</li>');
        index += 1;
        continue;
      }
      closeList();
      const paragraph = [line.trim()];
      index += 1;
      while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index])) {
        paragraph.push(lines[index].trim());
        index += 1;
      }
      out.push('<p>' + paragraph.map(renderInline).join('<br>') + '</p>');
    }
    closeList();
    return out.join('');
  }

  function createSseParser(onEvent) {
    let buffer = '';
    function emit(block) {
      const data = block.split(/\r?\n/)
        .filter(line => line.startsWith('data:'))
        .map(line => line.slice(5).replace(/^ /, ''))
        .join('\n');
      if (!data) return;
      let event;
      try { event = JSON.parse(data); }
      catch (error) { onEvent({ type: 'parse_error', message: '流式数据解析失败', raw: data }); return; }
      onEvent(event);
    }
    return {
      push(chunk) {
        buffer += String(chunk == null ? '' : chunk);
        for (;;) {
          const match = buffer.match(/\r?\n\r?\n/);
          if (!match) break;
          const index = match.index;
          const block = buffer.slice(0, index);
          buffer = buffer.slice(index + match[0].length);
          emit(block);
        }
      },
      flush() {
        if (buffer.trim()) emit(buffer);
        buffer = '';
      },
    };
  }

  function normalizeMessage(message) {
    const source = message && typeof message === 'object' ? message : {};
    return {
      id: String(source.id || ''),
      role: source.role === 'assistant' ? 'assistant' : 'user',
      content: String(source.content || ''),
      status: source.status || 'complete',
      errorCode: source.error_code || '',
      clientId: source.client_id || '',
      sequence: Number(source.sequence) || 0,
      optimistic: Boolean(source.optimistic),
    };
  }

  function applyChatEvent(messages, event) {
    const list = (Array.isArray(messages) ? messages : []).map(message => ({ ...message }));
    const replaceAt = (position, message) => {
      const normalized = { ...normalizeMessage(message), optimistic: false };
      if (position >= 0 && position < list.length) list.splice(position, 1, normalized);
      else list.push(normalized);
    };
    const findByClient = clientId => list.findIndex(message => message.clientId && message.clientId === clientId);
    const findLastAssistant = () => {
      for (let i = list.length - 1; i >= 0; i -= 1) if (list[i].role === 'assistant') return i;
      return -1;
    };
    if (!event || typeof event !== 'object') return { messages: list, streaming: true, finished: false };
    if (event.type === 'start') {
      const user = event.user_message;
      if (user) {
        const position = findByClient(user.client_id || '');
        if (position >= 0) replaceAt(position, user); else list.push({ ...normalizeMessage(user), optimistic: false });
      }
      const assistant = event.assistant_message;
      if (assistant) {
        const pending = list.findIndex(message => message.role === 'assistant' && message.optimistic);
        const target = pending >= 0 ? pending : findLastAssistant();
        replaceAt(target, assistant);
      }
      return { messages: list, streaming: true, finished: false };
    }
    if (event.type === 'delta') {
      let position = list.findIndex(message => message.id === event.message_id);
      if (position < 0) position = findLastAssistant();
      if (position >= 0) {
        list[position] = { ...list[position], content: String(list[position].content || '') + String(event.text || ''), status: 'streaming', optimistic: false };
      }
      return { messages: list, streaming: true, finished: false };
    }
    if (event.type === 'done') {
      const assistant = event.reply && event.reply.assistant_message;
      if (assistant) {
        const position = list.findIndex(message => message.id === assistant.id);
        replaceAt(position >= 0 ? position : findLastAssistant(), assistant);
      } else {
        const position = findLastAssistant();
        if (position >= 0) list[position] = { ...list[position], status: 'complete' };
      }
      return { messages: list, streaming: false, finished: true };
    }
    if (event.type === 'stopped') {
      const message = event.message;
      if (message) {
        const position = list.findIndex(item => item.id === message.id);
        replaceAt(position >= 0 ? position : findLastAssistant(), message);
      } else {
        const position = findLastAssistant();
        if (position >= 0) list[position] = { ...list[position], status: 'stopped' };
      }
      return { messages: list, streaming: false, finished: true, stopped: true };
    }
    if (event.type === 'error') {
      const position = findLastAssistant();
      if (position >= 0) {
        list[position] = { ...list[position], status: 'error', errorCode: String(event.error || 'error') };
      }
      return { messages: list, streaming: false, finished: true, error: String(event.message || '生成失败') };
    }
    return { messages: list, streaming: true, finished: false };
  }

  function personaPreview(settings) {
    const source = { ...DEFAULT_PERSONA, ...(settings || {}) };
    const style = STYLE_OPTIONS.find(item => item.value === source.assistant_style) || STYLE_OPTIONS[2];
    const length = LENGTH_LABELS[source.response_length] || '适中';
    const custom = String(source.assistant_custom_prompt || '').trim();
    return '以「' + (source.assistant_name || DEFAULT_PERSONA.assistant_name) + '」的身份回答，风格：' +
      style.label + '（' + style.hint + '），长度：' + length + '。' +
      (custom ? ' 自定义要求：' + custom : ' 使用默认人格。') +
      ' 安全约束始终优先。';
  }

  function initChat() {
    if (typeof document === 'undefined') return null;
    const byId = id => document.getElementById(id);
    const E = {};
    [
      'chatWorkspace', 'chatSide', 'assistantBtn', 'chatCloseBtn', 'chatNewBtn', 'chatConvList',
      'chatPersonaBtn', 'chatProviderBtn', 'chatRefreshBtn', 'chatMenuBtn', 'chatTitle', 'chatMeta',
      'chatProviderSel', 'chatModelSel', 'chatArchiveBtn', 'chatRenameBtn', 'chatDeleteBtn', 'chatNotice', 'chatMessages',
      'chatEmpty', 'chatEmptyNew', 'chatInput', 'chatStatus', 'chatStopBtn', 'chatSendBtn',
      'personaModal', 'personaName', 'personaStyle', 'personaLength', 'personaPrompt', 'personaCount',
      'personaPreview', 'personaResetBtn', 'personaSaveBtn', 'personaStatus',
      'providerModal', 'providerList', 'providerForm', 'providerKind', 'providerLabel', 'providerBaseUrl',
      'providerModel', 'providerKey', 'providerClearKey', 'providerCancelEdit', 'providerStatus',
      'providerHint',
    ].forEach(id => { E[id] = byId(id); });
    if (!E.chatWorkspace || !E.assistantBtn) return null;

    const state = {
      port: null,
      open: false,
      providers: [],
      providerId: '',
      model: '',
      conversations: [],
      conversationId: '',
      conversation: null,
      messages: [],
      streaming: false,
      stopRequested: false,
      abort: null,
      finished: false,
      persona: { ...DEFAULT_PERSONA },
      editingProviderId: '',
      initialised: false,
      renderQueued: false,
    };

    STYLE_OPTIONS.forEach(option => {
      const el = document.createElement('option');
      el.value = option.value;
      el.textContent = option.label;
      E.personaStyle.appendChild(el);
    });

    function showNotice(text, options = {}) {
      if (!E.chatNotice) return;
      E.chatNotice.textContent = '';
      E.chatNotice.classList.toggle('error', Boolean(options.error));
      E.chatNotice.hidden = false;
      const label = document.createElement('span');
      label.textContent = text;
      E.chatNotice.appendChild(label);
      if (options.actionLabel && typeof options.action === 'function') {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = options.actionLabel;
        button.addEventListener('click', options.action);
        E.chatNotice.appendChild(button);
      }
    }

    function clearNotice() { if (E.chatNotice) { E.chatNotice.hidden = true; E.chatNotice.textContent = ''; } }

    function selectedProvider() {
      return state.providers.find(provider => provider.id === state.providerId) || null;
    }

    function providerLabel(provider) {
      if (!provider) return '未配置';
      const local = provider.kind === 'ollama';
      return (provider.label || provider.kind) + (local ? ' · 本机' : ' · 在线');
    }

    function updateStatus(text, kind) {
      if (!E.chatStatus) return;
      E.chatStatus.textContent = text;
      E.chatStatus.className = 'chat-status' + (kind ? ' ' + kind : '');
    }

    function updateComposer() {
      const hasProvider = Boolean(selectedProvider());
      const archived = Boolean(state.conversation && state.conversation.archived);
      E.chatSendBtn.disabled = state.streaming || !hasProvider || archived;
      E.chatStopBtn.hidden = !state.streaming;
      E.chatInput.disabled = state.streaming || archived;
      updateStatus(state.streaming ? (state.stopRequested ? '正在停止…' : '正在生成…') : (archived ? '该对话已归档，取消归档后可继续' : (hasProvider ? '就绪' : '请先配置 AI')), state.streaming ? 'busy' : '');
    }

    function setSideOpen(open) {
      E.chatWorkspace.classList.toggle('side-open', Boolean(open));
    }

    function scrollToBottom() {
      const box = E.chatMessages;
      if (!box) return;
      box.scrollTop = box.scrollHeight;
    }

    function renderMessages() {
      const box = E.chatMessages;
      if (!box) return;
      box.querySelectorAll('.msg').forEach(node => node.remove());
      E.chatEmpty.hidden = state.messages.length > 0;
      for (const message of state.messages) {
        const row = document.createElement('article');
        row.className = 'msg ' + (message.role === 'assistant' ? 'assistant' : 'user');
        row.dataset.messageId = message.id;
        const avatar = document.createElement('div');
        avatar.className = 'msg-avatar';
        avatar.textContent = message.role === 'assistant' ? 'H' : '我';
        const body = document.createElement('div');
        body.className = 'msg-body';
        const bubble = document.createElement('div');
        bubble.className = 'msg-bubble';
        if (message.role === 'assistant') bubble.innerHTML = renderMarkdown(message.content || '');
        else bubble.textContent = message.content || '';
        if (message.status === 'streaming') bubble.classList.add('typing-cursor');
        body.appendChild(bubble);
        const meta = document.createElement('div');
        meta.className = 'msg-meta';
        const label = document.createElement('span');
        label.className = 'msg-state' + (message.status === 'error' ? ' error' : message.status === 'stopped' ? ' stopped' : '');
        label.textContent = message.role === 'assistant'
          ? (message.status === 'streaming' ? '生成中' : message.status === 'stopped' ? '已停止' : message.status === 'error' ? '生成失败' : '赫淮斯托斯')
          : '你';
        meta.appendChild(label);
        if (message.role === 'assistant' && message.status !== 'streaming' && message.content) {
          const actions = document.createElement('span');
          actions.className = 'msg-actions';
          const copy = document.createElement('button');
          copy.type = 'button';
          copy.dataset.action = 'copy-message';
          copy.textContent = '复制';
          actions.appendChild(copy);
          const regen = document.createElement('button');
          regen.type = 'button';
          regen.dataset.action = 'regenerate';
          regen.dataset.messageId = message.id;
          regen.textContent = '重新生成';
          actions.appendChild(regen);
          meta.appendChild(actions);
        }
        body.appendChild(meta);
        row.appendChild(avatar);
        row.appendChild(body);
        box.appendChild(row);
      }
      scrollToBottom();
    }

    function scheduleRender() {
      if (state.renderQueued) return;
      state.renderQueued = true;
      (root.requestAnimationFrame || (callback => setTimeout(callback, 16)))(() => {
        state.renderQueued = false;
        renderMessages();
      });
    }

    function renderConversations() {
      const list = E.chatConvList;
      if (!list) return;
      list.textContent = '';
      if (!state.conversations.length) {
        const empty = document.createElement('div');
        empty.className = 'chat-conv-empty';
        empty.textContent = '还没有对话。新建一个对话开始。';
        list.appendChild(empty);
        return;
      }
      for (const conversation of state.conversations) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'chat-conv' + (conversation.id === state.conversationId ? ' active' : '') + (conversation.archived ? ' archived' : '');
        button.setAttribute('role', 'listitem');
        const title = document.createElement('span');
        title.textContent = (conversation.title || '新对话') + (conversation.archived ? '（已归档）' : '');
        button.appendChild(title);
        if (conversation.messageCount) {
          const count = document.createElement('small');
          count.textContent = String(conversation.messageCount);
          button.appendChild(count);
        }
        button.addEventListener('click', () => { setSideOpen(false); loadConversation(conversation.id); });
        list.appendChild(button);
      }
    }

    function renderHeader() {
      const name = (state.persona && state.persona.assistant_name) || DEFAULT_PERSONA.assistant_name;
      E.chatTitle.textContent = state.conversation ? state.conversation.title : name;
      const provider = selectedProvider();
      E.chatMeta.textContent = provider
        ? providerLabel(provider) + (state.model ? ' · ' + state.model : '') + ' · 对话保存在本地'
        : '本地优先 · 尚未配置 AI';
      E.chatArchiveBtn.disabled = !state.conversation;
      E.chatArchiveBtn.textContent = state.conversation && state.conversation.archived ? '取消归档' : '归档';
      E.chatRenameBtn.disabled = !state.conversation;
      E.chatDeleteBtn.disabled = !state.conversation;
    }

    function renderProviderOptions() {
      const select = E.chatProviderSel;
      select.textContent = '';
      if (!state.providers.length) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = '未配置';
        select.appendChild(option);
        select.disabled = true;
        return;
      }
      select.disabled = false;
      for (const provider of state.providers) {
        const option = document.createElement('option');
        option.value = provider.id;
        option.textContent = provider.label + (provider.enabled === false ? '（已停用）' : '');
        select.appendChild(option);
      }
      select.value = state.providerId;
    }

    function renderModelOptions(models) {
      const select = E.chatModelSel;
      select.textContent = '';
      const provider = selectedProvider();
      const values = [];
      if (state.model) values.push({ id: state.model, name: state.model });
      for (const model of (models || [])) {
        if (model && model.id && !values.some(item => item.id === model.id)) values.push(model);
      }
      if (!values.length && provider && provider.model) values.push({ id: provider.model, name: provider.model });
      if (!values.length) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = '默认模型';
        select.appendChild(option);
        select.disabled = true;
        return;
      }
      select.disabled = false;
      for (const model of values) {
        const option = document.createElement('option');
        option.value = model.id;
        option.textContent = model.name || model.id;
        select.appendChild(option);
      }
      select.value = state.model || values[0].id;
    }

    async function ensurePort() {
      const store = root.HephaestusStore;
      if (!store) throw new Error('前端存储模块尚未加载');
      await store.init();
      state.port = store.port;
      if (!state.port) throw new Error('数据接口尚未就绪');
      if (state.port.adapter !== 'v2') {
        showNotice('AI 对话需要 V2 数据模式。当前数据库尚未迁移，笔记功能不受影响。', {
          error: true, actionLabel: '查看说明', action: () => showNotice('请先在桌面端完成 V2 数据库迁移，然后重新打开 AI 助手。'),
        });
        E.chatSendBtn.disabled = true;
        return false;
      }
      return true;
    }

    async function refreshProviders() {
      if (!state.port) return;
      state.providers = (await state.port.listAIProviders()).filter(provider => provider && provider.id);
      if (!state.providers.some(provider => provider.id === state.providerId)) {
        const preferred = state.providers.find(provider => provider.enabled !== false) || state.providers[0];
        state.providerId = preferred ? preferred.id : '';
      }
      const provider = selectedProvider();
      state.model = state.conversation && state.conversation.providerId === state.providerId
        ? (state.conversation.model || '')
        : (provider ? (provider.model || '') : '');
      renderProviderOptions();
      await refreshModels();
      if (!state.providers.length) {
        showNotice('还没有可用的 AI 配置。添加本机 Ollama 或在线 API 后即可开始对话。', {
          actionLabel: '添加 AI 配置', action: () => openProviderModal(),
        });
      }
      updateComposer();
      renderHeader();
    }

    async function refreshModels() {
      const provider = selectedProvider();
      if (!provider) { state.model = ''; renderModelOptions([]); return; }
      let models = [];
      try {
        models = await state.port.listAIProviderModels(provider.id);
      } catch (error) {
        models = [];
      }
      const model = state.model || (state.conversation && state.conversation.providerId === provider.id ? state.conversation.model : '') || provider.model || '';
      state.model = model || (models[0] && models[0].id) || '';
      renderModelOptions(models);
    }

    async function refreshConversations() {
      if (!state.port) return;
      const page = await state.port.listAIConversations({ pageSize: 100, includeArchived: true });
      state.conversations = page.items || [];
      renderConversations();
      if (state.conversationId && !state.conversations.some(item => item.id === state.conversationId)) {
        state.conversationId = '';
        state.conversation = null;
        state.messages = [];
        renderMessages();
        renderHeader();
      }
    }

    async function loadConversation(id) {
      if (!state.port || !id) return;
      try {
        clearNotice();
        const detail = await state.port.getAIConversation(id, { pageSize: 200 });
        state.conversationId = id;
        state.conversation = detail.conversation;
        state.messages = detail.messages || [];
        state.providerId = detail.conversation.providerId || state.providerId;
        state.model = detail.conversation.model || '';
        renderProviderOptions();
        renderModelOptions([]);
        renderMessages();
        renderHeader();
        renderConversations();
        updateComposer();
      } catch (error) {
        showNotice('读取对话失败：' + (error && error.message ? error.message : '未知错误'), { error: true });
      }
    }

    async function createConversation() {
      if (!state.port) return null;
      const provider = selectedProvider();
      if (!provider) {
        showNotice('请先添加一个 AI 配置。', { actionLabel: '添加 AI 配置', action: () => openProviderModal() });
        return null;
      }
      try {
        const conversation = await state.port.createAIConversation({
          title: '新对话',
          provider_id: provider.id,
          model: state.model || provider.model || null,
        });
        state.conversations.unshift(conversation);
        state.conversationId = conversation.id;
        state.conversation = conversation;
        state.messages = [];
        state.providerId = conversation.providerId || provider.id;
        state.model = conversation.model || state.model;
        renderConversations();
        renderMessages();
        renderHeader();
        updateComposer();
        clearNotice();
        E.chatInput.focus();
        return conversation;
      } catch (error) {
        showNotice('创建对话失败：' + (error && error.message ? error.message : '未知错误'), { error: true });
        return null;
      }
    }

    async function ensureConversation() {
      if (state.conversation) return state.conversation;
      return createConversation();
    }

    async function renameConversation() {
      if (!state.conversation || !state.port) return;
      const title = root.prompt ? root.prompt('重命名对话', state.conversation.title || '新对话') : '';
      if (title == null) return;
      const clean = String(title).trim();
      if (!clean) return;
      try {
        const updated = await state.port.updateAIConversation(state.conversation.id, {
          title: clean.slice(0, 80), revision: state.conversation.revision,
        });
        state.conversation = updated;
        const index = state.conversations.findIndex(item => item.id === updated.id);
        if (index >= 0) state.conversations[index] = updated;
        renderConversations();
        renderHeader();
      } catch (error) {
        showNotice('重命名失败：' + (error && error.message ? error.message : '未知错误'), { error: true });
      }
    }

    async function toggleArchiveConversation() {
      if (!state.conversation || !state.port) return;
      const archived = !state.conversation.archived;
      try {
        const updated = await state.port.updateAIConversation(state.conversation.id, {
          archived, revision: state.conversation.revision,
        });
        state.conversation = updated;
        const index = state.conversations.findIndex(item => item.id === updated.id);
        if (index >= 0) state.conversations[index] = updated;
        renderConversations();
        renderHeader();
        updateComposer();
        showNotice(archived ? '对话已归档，可在列表中查看和恢复。' : '对话已取消归档。');
      } catch (error) {
        showNotice((archived ? '归档' : '取消归档') + '失败：' + (error && error.message ? error.message : '未知错误'), { error: true });
      }
    }

    async function deleteConversation() {
      if (!state.conversation || !state.port) return;
      if (root.confirm && !root.confirm('删除对话「' + (state.conversation.title || '新对话') + '」？此操作不可撤销。')) return;
      try {
        await state.port.deleteAIConversation(state.conversation.id);
        state.conversationId = '';
        state.conversation = null;
        state.messages = [];
        await refreshConversations();
        renderMessages();
        renderHeader();
        updateComposer();
      } catch (error) {
        showNotice('删除对话失败：' + (error && error.message ? error.message : '未知错误'), { error: true });
      }
    }

    function markStreamingFailure(message) {
      const index = state.messages.map(item => item.role).lastIndexOf('assistant');
      if (index >= 0) {
        state.messages[index] = { ...state.messages[index], status: 'error', errorCode: 'stream_failed' };
      }
      showNotice(message, { error: true, actionLabel: '重试', action: retryLast });
      updateStatus('生成失败');
      scheduleRender();
    }

    async function consumeStream(response) {
      if (!response || !response.body || !response.body.getReader) throw new Error('浏览器不支持流式响应');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const parser = createSseParser(event => {
        if (!event) return;
        const result = applyChatEvent(state.messages, event);
        state.messages = result.messages;
        if (result.error) {
          state.finished = true;
          showNotice(result.error, { error: true, actionLabel: '重试', action: retryLast });
        }
        if (result.finished) state.finished = true;
        if (event.type === 'parse_error') {
          state.finished = true;
          showNotice('流式响应解析失败，已保留已生成内容。', { error: true, actionLabel: '重试', action: retryLast });
        }
        scheduleRender();
      });
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        parser.push(decoder.decode(value, { stream: true }));
      }
      parser.push(decoder.decode());
      parser.flush();
    }

    async function runGeneration({ text, regenerateMessageId } = {}) {
      if (state.streaming) return;
      if (!state.port) return;
      const conversation = await ensureConversation();
      if (!conversation) return;
      const provider = selectedProvider();
      if (!provider) { showNotice('请先添加一个 AI 配置。', { error: true }); return; }
      clearNotice();
      state.streaming = true;
      state.finished = false;
      state.stopRequested = false;
      state.abort = new AbortController();
      updateComposer();
      const clientId = uid('c');
      if (regenerateMessageId) {
        const index = state.messages.findIndex(message => message.id === regenerateMessageId);
        if (index >= 0) state.messages[index] = { ...state.messages[index], content: '', status: 'streaming', errorCode: '', optimistic: false };
        scheduleRender();
      } else {
        state.messages.push({ id: 'local-user-' + clientId, role: 'user', content: text, status: 'complete', clientId, optimistic: true });
        state.messages.push({ id: 'local-assistant-' + clientId, role: 'assistant', content: '', status: 'streaming', optimistic: true });
        scheduleRender();
      }
      try {
        const response = regenerateMessageId
          ? await state.port.regenerateAIMessage(conversation.id, regenerateMessageId, {
            message_id: regenerateMessageId, stream: true,
          }, { signal: state.abort.signal })
          : await state.port.sendAIMessage(conversation.id, {
            content: text, client_message_id: clientId, stream: true,
          }, { signal: state.abort.signal });
        await consumeStream(response);
        if (!state.finished) {
          if (state.stopRequested) {
            const index = state.messages.map(item => item.role).lastIndexOf('assistant');
            if (index >= 0) state.messages[index] = { ...state.messages[index], status: 'stopped' };
            updateStatus('已停止');
            scheduleRender();
          } else {
            markStreamingFailure('连接中断，已保留已生成内容。你可以停止或重试。');
          }
        }
      } catch (error) {
        if (error && error.code === 'aborted') {
          const index = state.messages.map(item => item.role).lastIndexOf('assistant');
          if (index >= 0) state.messages[index] = { ...state.messages[index], status: 'stopped' };
          updateStatus('已停止');
          scheduleRender();
        } else {
          markStreamingFailure('请求失败：' + (error && error.message ? error.message : '未知错误'));
        }
      } finally {
        state.streaming = false;
        state.abort = null;
        state.stopRequested = false;
        updateComposer();
        refreshConversations().catch(() => {});
        if (state.conversationId) {
          state.port.getAIConversation(state.conversationId, { pageSize: 200 }).then(detail => {
            if (!state.streaming && detail && detail.conversation) {
              state.conversation = detail.conversation;
              state.messages = detail.messages || state.messages;
              renderMessages();
              renderHeader();
            }
          }).catch(() => {});
        }
      }
    }

    function sendCurrent() {
      const text = String(E.chatInput.value || '').trim();
      if (!text || state.streaming) return;
      E.chatInput.value = '';
      autoGrow();
      runGeneration({ text });
    }

    function retryLast() {
      if (state.streaming) return;
      const lastUser = [...state.messages].reverse().find(message => message.role === 'user');
      const lastAssistantIndex = state.messages.map(item => item.role).lastIndexOf('assistant');
      if (lastAssistantIndex >= 0 && state.messages[lastAssistantIndex].id && !state.messages[lastAssistantIndex].id.startsWith('local-')) {
        runGeneration({ regenerateMessageId: state.messages[lastAssistantIndex].id });
      } else if (lastUser && lastUser.content) {
        runGeneration({ text: lastUser.content });
      }
    }

    async function stopGeneration() {
      if (!state.streaming || !state.port || !state.conversationId) return;
      state.stopRequested = true;
      updateComposer();
      const lastAssistant = [...state.messages].reverse().find(message => message.role === 'assistant');
      try {
        await state.port.stopAIGeneration(state.conversationId, lastAssistant && lastAssistant.id ? lastAssistant.id : undefined);
      } catch (error) {
        showNotice('停止请求失败：' + (error && error.message ? error.message : '未知错误'), { error: true });
      }
    }

    function autoGrow() {
      const input = E.chatInput;
      if (!input) return;
      input.style.height = 'auto';
      input.style.height = Math.min(190, Math.max(24, input.scrollHeight)) + 'px';
    }

    function openChat() {
      E.chatWorkspace.hidden = false;
      state.open = true;
      document.body.classList.add('chat-open');
      ensurePort().then(async ok => {
        if (!ok) return;
        try {
          await refreshProviders();
          await refreshConversations();
          if (!state.conversationId && !state.streaming && state.conversations.length) {
            const recent = state.conversations.find(item => !item.archived) || state.conversations[0];
            await loadConversation(recent.id);
            await refreshModels();
            renderHeader();
            updateComposer();
          }
          await loadPersona({ silent: true });
        } catch (error) {
          showNotice('AI 服务初始化失败：' + (error && error.message ? error.message : '未知错误'), { error: true });
        }
      }).catch(error => {
        showNotice('AI 助手无法启动：' + (error && error.message ? error.message : '未知错误'), { error: true });
      });
      setTimeout(() => E.chatInput && E.chatInput.focus(), 40);
    }

    function closeChat() {
      E.chatWorkspace.hidden = true;
      state.open = false;
      document.body.classList.remove('chat-open');
    }

    async function loadPersona(options = {}) {
      if (!state.port) return;
      try {
        const settings = await state.port.getSettings();
        state.persona = { ...DEFAULT_PERSONA, ...settings };
        if (!options.silent) fillPersonaForm();
        renderHeader();
      } catch (error) {
        if (!options.silent) showNotice('读取人格设置失败：' + (error && error.message ? error.message : '未知错误'), { error: true });
      }
    }

    function fillPersonaForm() {
      E.personaName.value = state.persona.assistant_name || DEFAULT_PERSONA.assistant_name;
      E.personaStyle.value = state.persona.assistant_style || DEFAULT_PERSONA.assistant_style;
      E.personaLength.value = state.persona.response_length || DEFAULT_PERSONA.response_length;
      E.personaPrompt.value = state.persona.assistant_custom_prompt || '';
      updatePersonaPreview();
    }

    function updatePersonaPreview() {
      const settings = {
        assistant_name: E.personaName.value.trim() || DEFAULT_PERSONA.assistant_name,
        assistant_style: E.personaStyle.value,
        response_length: E.personaLength.value,
        assistant_custom_prompt: E.personaPrompt.value,
      };
      E.personaCount.textContent = String(E.personaPrompt.value.length);
      E.personaPreview.textContent = personaPreview(settings);
    }

    async function openPersonaModal() {
      ensurePort().then(ok => {
        if (!ok) return;
        loadPersona().then(() => {
          fillPersonaForm();
          E.personaModal.hidden = false;
          E.personaName.focus();
        });
      }).catch(error => showNotice('人格设置不可用：' + error.message, { error: true }));
    }

    async function savePersona(payload) {
      if (!state.port) return;
      E.personaStatus.textContent = '正在保存…';
      E.personaStatus.className = 'chat-form-status';
      try {
        const updated = await state.port.updateSettings(payload);
        state.persona = { ...DEFAULT_PERSONA, ...updated };
        E.personaStatus.textContent = '已保存';
        E.personaStatus.className = 'chat-form-status ok';
        renderHeader();
        E.personaModal.hidden = true;
        showNotice('人格设置已保存');
      } catch (error) {
        E.personaStatus.textContent = (error && error.message ? error.message : '保存失败');
        E.personaStatus.className = 'chat-form-status error';
      }
    }

    function openProviderModal() {
      ensurePort().then(ok => {
        if (!ok) return;
        E.providerModal.hidden = false;
        resetProviderForm();
        refreshProviderList();
      }).catch(error => showNotice('AI 配置不可用：' + error.message, { error: true }));
    }

    function updateProviderHint() {
      if (!E.providerHint) return;
      const kind = E.providerKind.value;
      E.providerHint.textContent = kind === 'ollama'
        ? '本机模型：数据不离开设备，无需 API Key；需要先启动 Ollama 并安装模型，仅桌面或本机 Web 可用。'
        : '在线 API：请求会发送到所填服务商，可能产生费用；需要有效的 API Key。密钥由系统密钥存储保管。';
    }

    function resetProviderForm() {
      state.editingProviderId = '';
      E.providerKind.value = 'ollama';
      E.providerLabel.value = '';
      E.providerBaseUrl.value = 'http://127.0.0.1:11434';
      E.providerModel.value = '';
      E.providerKey.value = '';
      E.providerClearKey.checked = false;
      E.providerCancelEdit.hidden = true;
      E.providerStatus.textContent = '';
      E.providerStatus.className = 'chat-form-status';
      updateProviderHint();
    }

    function editProvider(provider) {
      state.editingProviderId = provider.id;
      E.providerKind.value = provider.kind || 'custom';
      E.providerLabel.value = provider.label || '';
      E.providerBaseUrl.value = provider.base_url || '';
      E.providerModel.value = provider.model || '';
      E.providerKey.value = '';
      E.providerClearKey.checked = false;
      E.providerCancelEdit.hidden = false;
      E.providerStatus.textContent = '正在编辑：' + (provider.label || provider.id);
      E.providerStatus.className = 'chat-form-status';
      E.providerLabel.focus();
      updateProviderHint();
    }

    async function refreshProviderList() {
      try {
        state.providers = await state.port.listAIProviders();
      } catch (error) {
        state.providers = [];
      }
      const list = E.providerList;
      list.textContent = '';
      if (!state.providers.length) {
        const empty = document.createElement('div');
        empty.className = 'provider-empty';
        empty.textContent = '还没有配置。添加本机 Ollama 或在线 API。';
        list.appendChild(empty);
        return;
      }
      for (const provider of state.providers) {
        const item = document.createElement('div');
        item.className = 'provider-item' + (provider.id === state.editingProviderId ? ' active' : '');
        const title = document.createElement('b');
        title.textContent = provider.label || provider.kind;
        const meta = document.createElement('small');
        meta.textContent = provider.kind + (provider.kind === 'ollama' ? ' · 本机' : ' · 在线') + (provider.has_key ? ' · 已保存密钥' : '') + (provider.enabled === false ? ' · 已停用' : '');
        const actions = document.createElement('div');
        actions.className = 'provider-actions';
        const edit = document.createElement('button');
        edit.type = 'button'; edit.textContent = '编辑';
        edit.addEventListener('click', () => editProvider(provider));
        const test = document.createElement('button');
        test.type = 'button'; test.textContent = '测试';
        test.addEventListener('click', () => testProvider(provider));
        const remove = document.createElement('button');
        remove.type = 'button'; remove.textContent = '删除';
        remove.addEventListener('click', () => deleteProvider(provider));
        actions.append(edit, test, remove);
        item.append(title, meta, actions);
        list.appendChild(item);
      }
    }

    async function testProvider(provider) {
      E.providerStatus.textContent = '正在测试连接…';
      E.providerStatus.className = 'chat-form-status';
      try {
        const result = await state.port.testAIProvider(provider.id);
        E.providerStatus.textContent = (result.ok ? '连接成功' : '连接失败') + '：' + (result.message || '') + ' · ' + (result.latency_ms || 0) + 'ms';
        E.providerStatus.className = 'chat-form-status ' + (result.ok ? 'ok' : 'error');
      } catch (error) {
        E.providerStatus.textContent = '测试失败：' + (error && error.message ? error.message : '未知错误');
        E.providerStatus.className = 'chat-form-status error';
      }
    }

    async function deleteProvider(provider) {
      if (root.confirm && !root.confirm('删除 AI 配置「' + (provider.label || provider.id) + '」？已保存的密钥也会删除。')) return;
      try {
        await state.port.deleteAIProvider(provider.id);
        if (state.providerId === provider.id) state.providerId = '';
        await refreshProviderList();
        await refreshProviders();
      } catch (error) {
        E.providerStatus.textContent = '删除失败：' + (error && error.message ? error.message : '未知错误');
        E.providerStatus.className = 'chat-form-status error';
      }
    }

    async function saveProvider(event) {
      event.preventDefault();
      if (!state.port) return;
      const kind = E.providerKind.value;
      const label = E.providerLabel.value.trim();
      const baseUrl = E.providerBaseUrl.value.trim();
      const model = E.providerModel.value.trim();
      if (!label || !baseUrl || !model) {
        E.providerStatus.textContent = '请填写名称、接口地址和默认模型。';
        E.providerStatus.className = 'chat-form-status error';
        return;
      }
      const payload = { kind, label, base_url: baseUrl, model, enabled: true };
      const key = E.providerKey.value.trim();
      if (key) payload.api_key = key;
      if (E.providerClearKey.checked) payload.clear_api_key = true;
      E.providerStatus.textContent = '正在保存…';
      E.providerStatus.className = 'chat-form-status';
      try {
        if (state.editingProviderId) await state.port.updateAIProvider(state.editingProviderId, payload);
        else await state.port.createAIProvider(payload);
        E.providerStatus.textContent = '配置已保存';
        E.providerStatus.className = 'chat-form-status ok';
        resetProviderForm();
        await refreshProviderList();
        await refreshProviders();
      } catch (error) {
        E.providerStatus.textContent = '保存失败：' + (error && error.message ? error.message : '未知错误');
        E.providerStatus.className = 'chat-form-status error';
      }
    }

    function openExternal(url) {
      const safe = safeHref(url);
      if (!safe || safe.startsWith('#')) return;
      const bridge = root.pywebview && root.pywebview.api;
      if (bridge && typeof bridge.open_external === 'function') {
        try {
          const pending = bridge.open_external(safe);
          if (pending && typeof pending.catch === 'function') pending.catch(() => {});
        } catch (error) {
          /* external links must never break the chat workspace */
        }
        return;
      }
      root.open(safe, '_blank', 'noopener,noreferrer');
    }

    async function copyText(text) {
      try {
        await root.navigator.clipboard.writeText(text);
        return true;
      } catch (error) {
        const helper = document.createElement('textarea');
        helper.value = text;
        helper.style.position = 'fixed';
        helper.style.opacity = '0';
        document.body.appendChild(helper);
        helper.select();
        let ok = false;
        try { ok = document.execCommand('copy'); } catch (ignored) { ok = false; }
        helper.remove();
        return ok;
      }
    }

    // ---------- events ----------
    E.assistantBtn.addEventListener('click', openChat);
    E.chatCloseBtn.addEventListener('click', closeChat);
    E.chatMenuBtn.addEventListener('click', () => setSideOpen(!E.chatWorkspace.classList.contains('side-open')));
    E.chatNewBtn.addEventListener('click', () => { setSideOpen(false); createConversation(); });
    E.chatEmptyNew.addEventListener('click', () => createConversation());
    E.chatRefreshBtn.addEventListener('click', () => {
      refreshProviders().catch(() => {});
      refreshConversations().catch(() => {});
    });
    E.chatArchiveBtn.addEventListener('click', toggleArchiveConversation);
    E.chatRenameBtn.addEventListener('click', renameConversation);
    E.chatDeleteBtn.addEventListener('click', deleteConversation);
    E.chatProviderBtn.addEventListener('click', openProviderModal);
    E.chatPersonaBtn.addEventListener('click', openPersonaModal);
    E.chatProviderSel.addEventListener('change', async () => {
      state.providerId = E.chatProviderSel.value;
      await refreshModels();
      renderHeader();
      updateComposer();
      if (state.conversation && state.port) {
        try {
          const updated = await state.port.updateAIConversation(state.conversation.id, {
            provider_id: state.providerId, model: state.model || null, revision: state.conversation.revision,
          });
          state.conversation = updated;
          renderHeader();
        } catch (error) {
          showNotice('切换配置失败：' + (error && error.message ? error.message : '未知错误'), { error: true });
        }
      }
    });
    E.chatModelSel.addEventListener('change', async () => {
      state.model = E.chatModelSel.value;
      renderHeader();
      if (state.conversation && state.port) {
        try {
          state.conversation = await state.port.updateAIConversation(state.conversation.id, {
            model: state.model || null, revision: state.conversation.revision,
          });
          renderHeader();
        } catch (error) {
          showNotice('切换模型失败：' + (error && error.message ? error.message : '未知错误'), { error: true });
        }
      }
    });
    E.chatSendBtn.addEventListener('click', sendCurrent);
    E.chatStopBtn.addEventListener('click', stopGeneration);
    E.chatInput.addEventListener('input', autoGrow);
    E.chatInput.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        sendCurrent();
      }
    });
    E.chatMessages.addEventListener('click', async event => {
      const link = event.target.closest('a[href]');
      if (link) { event.preventDefault(); openExternal(link.getAttribute('href')); return; }
      const copy = event.target.closest('.code-copy');
      if (copy) {
        let code = '';
        try { code = decodeURIComponent(copy.getAttribute('data-code') || ''); } catch (ignored) { code = ''; }
        if (await copyText(code)) { copy.textContent = '已复制'; setTimeout(() => { copy.textContent = '复制'; }, 1200); }
        return;
      }
      const action = event.target.closest('[data-action]');
      if (!action) return;
      if (action.dataset.action === 'regenerate') {
        if (action.dataset.messageId) runGeneration({ regenerateMessageId: action.dataset.messageId });
      } else if (action.dataset.action === 'copy-message') {
        const row = action.closest('.msg');
        const bubble = row && row.querySelector('.msg-bubble');
        if (bubble && await copyText(bubble.innerText || '')) { action.textContent = '已复制'; setTimeout(() => { action.textContent = '复制'; }, 1200); }
      }
    });
    E.personaName.addEventListener('input', updatePersonaPreview);
    E.personaStyle.addEventListener('change', updatePersonaPreview);
    E.personaLength.addEventListener('change', updatePersonaPreview);
    E.personaPrompt.addEventListener('input', updatePersonaPreview);
    E.personaSaveBtn.addEventListener('click', () => {
      const name = E.personaName.value.trim();
      if (!name) {
        E.personaStatus.textContent = '助手名称不能为空。';
        E.personaStatus.className = 'chat-form-status error';
        return;
      }
      savePersona({
        assistant_name: name,
        assistant_style: E.personaStyle.value,
        response_length: E.personaLength.value,
        assistant_custom_prompt: E.personaPrompt.value.trim() || null,
      });
    });
    E.personaResetBtn.addEventListener('click', () => {
      E.personaName.value = DEFAULT_PERSONA.assistant_name;
      E.personaStyle.value = DEFAULT_PERSONA.assistant_style;
      E.personaLength.value = DEFAULT_PERSONA.response_length;
      E.personaPrompt.value = '';
      updatePersonaPreview();
      savePersona({
        assistant_name: DEFAULT_PERSONA.assistant_name,
        assistant_style: DEFAULT_PERSONA.assistant_style,
        response_length: DEFAULT_PERSONA.response_length,
        assistant_custom_prompt: null,
      });
    });
    E.providerForm.addEventListener('submit', saveProvider);
    E.providerCancelEdit.addEventListener('click', resetProviderForm);
    E.providerKind.addEventListener('change', () => {
      if (!state.editingProviderId) {
        const kind = E.providerKind.value;
        E.providerBaseUrl.value = kind === 'ollama' ? 'http://127.0.0.1:11434' : '';
        E.providerLabel.value = kind === 'ollama' ? '本机 Ollama' : '';
      }
      updateProviderHint();
    });
    document.querySelectorAll('[data-close]').forEach(button => {
      button.addEventListener('click', () => {
        const modal = byId(button.getAttribute('data-close'));
        if (modal) modal.hidden = true;
      });
    });
    [E.personaModal, E.providerModal].forEach(modal => {
      modal.addEventListener('mousedown', event => { if (event.target === modal) modal.hidden = true; });
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        if (!E.personaModal.hidden) { E.personaModal.hidden = true; return; }
        if (!E.providerModal.hidden) { E.providerModal.hidden = true; return; }
      }
    });

    state.initialised = true;
    return {
      open: openChat, close: closeChat, state,
      renderMarkdown, applyChatEvent, personaPreview,
    };
  }

  if (typeof document !== 'undefined') {
    const boot = () => initChat();
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else boot();
  }

  return {
    STYLE_OPTIONS, LENGTH_LABELS, DEFAULT_PERSONA,
    escapeHtml, safeHref, renderMarkdown, highlightCode, createSseParser,
    normalizeMessage, applyChatEvent, personaPreview, initChat, uid,
  };
});
