/* Hephaestus frontend DataPort (V2 B2).
 *
 * This file is the only place that talks to the backend. UI code must call
 * DataPort methods, never fetch() directly. It supports:
 *   - legacy /api/state read/write for unmigrated databases;
 *   - /api/v2 status detection + read/write after migration;
 *   - fallback to legacy for migration_pending / migration_failed;
 *   - typed errors (including revision conflicts) for the UI layer.
 *
 * UMD-ish wrapper: browser attaches window.HephaestusDataPort, Node tests can
 * require() this file without a bundler.
 */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.HephaestusDataPort = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  'use strict';

  const MODES = ['legacy', 'migration_pending', 'v2_ready', 'migration_failed'];

  class DataPortError extends Error {
    constructor(message, options = {}) {
      super(message);
      this.name = 'DataPortError';
      this.code = options.code || 'data_port_error';
      this.status = options.status || 0;
      this.details = options.details || null;
      this.cause = options.cause || null;
    }
  }

  class ConflictError extends DataPortError {
    constructor(message, options = {}) {
      super(message, { ...options, code: 'conflict' });
      this.name = 'ConflictError';
    }
  }

  const asArray = value => Array.isArray(value) ? value : [];
  const asObject = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const safeTitle = note => String((note && note.title) || '').trim() || '无标题笔记';
  const timestamp = value => {
    const parsed = typeof value === 'number' ? value : Date.parse(value || '');
    return Number.isFinite(parsed) ? parsed : Date.now();
  };

  function normalizeLegacy(state) {
    if (!state || !Array.isArray(state.notes) || !Array.isArray(state.tags)) return null;
    return {
      notes: state.notes.map(note => ({
        ...note,
        tags: asArray(note.tags),
        fav: Boolean(note.fav),
        trashed: Boolean(note.trashed),
        created: timestamp(note.created),
        updated: timestamp(note.updated),
      })),
      tags: state.tags.map(tag => ({
        ...tag,
        name: String(tag.name || ''),
        color: tag.color || '#8b8f94',
      })),
      ui: {
        theme: 'light', layout: 'list', sort: 'updated',
        ...asObject(state.ui),
      },
    };
  }

  function toLegacySnapshot(data) {
    return {
      notes: asArray(data && data.notes).map(note => ({
        id: note.id,
        title: String(note.title || ''),
        html: String(note.html || ''),
        tags: asArray(note.tags),
        fav: Boolean(note.fav),
        trashed: Boolean(note.trashed),
        created: Number(note.created) || Date.now(),
        updated: Number(note.updated) || Date.now(),
      })),
      tags: asArray(data && data.tags).map(tag => ({
        id: tag.id,
        name: String(tag.name || ''),
        color: tag.color || '#8b8f94',
      })),
      ui: {
        theme: (data && data.ui && data.ui.theme) || 'light',
        layout: (data && data.ui && data.ui.layout) || 'list',
        sort: (data && data.ui && data.ui.sort) || 'updated',
      },
    };
  }

  function fromV2Note(note) {
    return {
      id: note.id,
      title: note.title || '',
      html: note.content_html || '',
      tags: asArray(note.tags).map(tag => tag.id).filter(Boolean),
      fav: Boolean(note.is_favorite),
      trashed: Boolean(note.is_trashed),
      created: timestamp(note.created_at),
      updated: timestamp(note.updated_at),
      category: note.category || '',
      revision: Number(note.revision) || 1,
      attachments: asArray(note.attachments),
      tagObjects: asArray(note.tags),
    };
  }

  function fromV2Tag(tag) {
    return { id: tag.id, name: tag.name, color: tag.color || '#8b8f94' };
  }

  function settingsToUi(settings) {
    const source = asObject(settings);
    return {
      theme: source.theme || 'light',
      layout: source.layout || 'list',
      sort: source.sort || 'updated',
      locale: source.locale || 'zh-CN',
    };
  }

  function createHttp(fetchImpl, baseUrl) {
    const base = String(baseUrl || '').replace(/\/+$/, '');
    return async function request(path, options = {}) {
      if (typeof fetchImpl !== 'function') {
        throw new DataPortError('当前环境缺少 fetch，无法连接本地服务', { code: 'no_fetch' });
      }
      const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
      const timeoutMs = options.timeoutMs == null ? 12000 : options.timeoutMs;
      const timer = controller && timeoutMs > 0 ? setTimeout(() => controller.abort(), timeoutMs) : null;
      let response;
      try {
        response = await fetchImpl(base + path, {
          method: options.method || 'GET',
          headers: options.body == null ? undefined : { 'Content-Type': 'application/json' },
          body: options.body == null ? undefined : JSON.stringify(options.body),
          signal: controller ? controller.signal : undefined,
          keepalive: Boolean(options.keepalive),
          credentials: 'same-origin',
        });
      } catch (error) {
        throw new DataPortError('无法连接本地服务，请确认 Hephaestus 正在运行', {
          code: error && error.name === 'AbortError' ? 'timeout' : 'network',
          cause: error,
        });
      } finally {
        if (timer) clearTimeout(timer);
      }

      let payload = null;
      const text = await response.text();
      if (text) {
        try { payload = JSON.parse(text); } catch { payload = text; }
      }
      if (!response.ok) {
        const detail = payload && typeof payload === 'object'
          ? (payload.detail || payload.message || JSON.stringify(payload))
          : (payload || ('HTTP ' + response.status));
        const message = typeof detail === 'string' ? detail : ('HTTP ' + response.status);
        if (response.status === 409) {
          throw new ConflictError(message, { status: 409, details: payload });
        }
        throw new DataPortError(message, { status: response.status, details: payload });
      }
      return payload;
    };
  }

  function createLegacyAdapter(request) {
    return {
      async load() {
        const result = await request('/api/state');
        if (!result || !result.initialized || !result.state) return null;
        return normalizeLegacy(result.state);
      },
      async save(data) {
        await request('/api/state', { method: 'PUT', body: toLegacySnapshot(data) });
      },
    };
  }

  function createV2Adapter(request, log) {
    let tagCache = null;

    async function listTags(force = false) {
      if (!force && tagCache) return tagCache;
      const rows = asArray(await request('/api/v2/tags'));
      tagCache = rows.map(fromV2Tag);
      return tagCache;
    }

    async function rememberTag(tag) {
      if (!tagCache) await listTags();
      if (!tagCache.some(existing => existing.id === tag.id)) tagCache.push(tag);
      return tag;
    }

    async function createOrFindTag(input) {
      try {
        const created = fromV2Tag(await request('/api/v2/tags', {
          method: 'POST',
          body: { name: input.name, color: input.color || '#8b8f94' },
        }));
        return rememberTag(created);
      } catch (error) {
        if (error && error.status === 409) {
          await listTags(true);
          const existing = (tagCache || []).find(tag => tag.name === input.name);
          if (existing) return existing;
        }
        throw error;
      }
    }

    async function ensureTagIds(note, localTags) {
      const tags = asArray(note && note.tags);
      if (!tags.length) return [];
      const remote = await listTags();
      const remoteById = new Map(remote.map(tag => [tag.id, tag]));
      const remoteByName = new Map(remote.map(tag => [tag.name, tag]));
      const localById = new Map(asArray(localTags).map(tag => [tag.id, tag]));
      const result = [];
      for (const ref of tags) {
        let tag = remoteById.get(ref);
        if (!tag) {
          const local = localById.get(ref);
          const name = local ? local.name : String(ref || '');
          tag = remoteByName.get(name);
          if (!tag && name.trim()) {
            try {
              tag = await createOrFindTag({ name, color: local ? local.color : '#8b8f94' });
            } catch (error) {
              throw new DataPortError('标签同步失败：' + (error && error.message ? error.message : '未知错误'), {
                code: 'tag_sync_failed', cause: error,
              });
            }
            remoteByName.set(tag.name, tag);
          }
        }
        if (tag) result.push(tag.id);
      }
      return Array.from(new Set(result)).slice(0, 100);
    }

    async function listPage(trashed, page) {
      return request('/api/v2/notes?trashed=' + (trashed ? 'true' : 'false') + '&page=' + page + '&page_size=100');
    }

    async function listAll(trashed) {
      const notes = [];
      for (let page = 1; page <= 100; page += 1) {
        const result = await listPage(trashed, page);
        const items = asArray(result && result.items).map(fromV2Note);
        notes.push(...items);
        const total = Number(result && result.total) || 0;
        if (!items.length || notes.length >= total) break;
      }
      return notes;
    }

    return {
      async load() {
        const [tags, settings, live, trashed] = await Promise.all([
          listTags(),
          request('/api/v2/settings'),
          listAll(false),
          listAll(true),
        ]);
        return {
          notes: live.concat(trashed),
          tags,
          ui: settingsToUi(settings),
        };
      },
      async createNote(note, localTags) {
        const tagIds = await ensureTagIds(note, localTags);
        const created = await request('/api/v2/notes', {
          method: 'POST',
          body: {
            title: safeTitle(note),
            content_html: String((note && note.html) || ''),
            category: (note && note.category) || null,
            tags: tagIds,
          },
        });
        return fromV2Note(created);
      },
      async updateNote(note, localTags) {
        const tagIds = await ensureTagIds(note, localTags);
        const updated = await request('/api/v2/notes/' + encodeURIComponent(note.id), {
          method: 'PATCH',
          body: {
            title: safeTitle(note),
            content_html: String(note.html || ''),
            category: note.category || null,
            tags: tagIds,
            revision: Number(note.revision) || 1,
          },
        });
        return fromV2Note(updated);
      },
      async getNote(id) {
        return fromV2Note(await request('/api/v2/notes/' + encodeURIComponent(id)));
      },
      async setFavorite(note) {
        return fromV2Note(await request('/api/v2/notes/' + encodeURIComponent(note.id) + '/favorite', {
          method: 'PATCH', body: { favorite: Boolean(note.fav) },
        }));
      },
      async trash(note) {
        await request('/api/v2/notes/' + encodeURIComponent(note.id), { method: 'DELETE' });
      },
      async restore(note) {
        return fromV2Note(await request('/api/v2/notes/' + encodeURIComponent(note.id) + '/restore', { method: 'POST' }));
      },
      async remove(note) {
        await request('/api/v2/notes/' + encodeURIComponent(note.id) + '?permanent=true', { method: 'DELETE' });
      },
      async createTag(input) {
        return createOrFindTag(input);
      },
      async fetchTags() {
        return listTags(true);
      },
      async updateTag(tag) {
        return fromV2Tag(await request('/api/v2/tags/' + encodeURIComponent(tag.id), {
          method: 'PATCH', body: { name: tag.name, color: tag.color },
        }));
      },
      async deleteTag(id) {
        await request('/api/v2/tags/' + encodeURIComponent(id), { method: 'DELETE' });
      },
      async saveSettings(ui) {
        const current = await request('/api/v2/settings');
        const body = { theme: ui.theme, layout: ui.layout, sort: ui.sort };
        if (current && current.locale) body.locale = current.locale;
        return settingsToUi(await request('/api/v2/settings', { method: 'PATCH', body }));
      },
      invalidateTags() { tagCache = null; },
    };
  }

  async function detectStatus(request, log) {
    try {
      const status = await request('/api/v2/status');
      if (!status || !MODES.includes(status.data_mode)) {
        throw new DataPortError('状态接口返回了未知的数据模式', { code: 'bad_status' });
      }
      log('检测到数据模式：' + status.data_mode, {
        fallback: Boolean(status.fallback), reason: status.reason,
      });
      return { mode: status.data_mode, status, degraded: false, error: null };
    } catch (error) {
      const isOldServer = error && (error.status === 404 || error.status === 405);
      if (!isOldServer) {
        // 只有旧服务端（没有该路由）才允许回退 /api/state。网络错误或 5xx 时
        // 无法确认数据模式，必须停止写入，否则迁移后的库会被旧快照再次写入。
        log('数据状态检测失败，已停止一切写入', { error: String(error && error.message || error) });
        throw new DataPortError('无法确认数据模式，已停止写入以避免双重写入', {
          code: 'status_unavailable',
          status: error && error.status ? error.status : 0,
          cause: error,
        });
      }
      const status = {
        data_mode: 'legacy',
        contract_version: '1.0',
        fallback: true,
        reason: '服务端没有 /api/v2/status，按旧版处理',
        legacy: null,
        v2: null,
      };
      log('旧服务端没有数据状态接口，使用 /api/state', { error: String(error && error.message || error) });
      return { mode: 'legacy', status, degraded: true, error };
    }
  }

  function createDataPort(options = {}) {
    const fetchImpl = options.fetchImpl || (typeof fetch === 'function' ? fetch.bind(root) : null);
    const logger = options.logger || ((message, detail) => {
      if (root && root.console && root.console.info) root.console.info('[Hephaestus DataPort] ' + message, detail || '');
    });
    const request = createHttp(fetchImpl, options.baseUrl || '');
    const legacy = createLegacyAdapter(request);
    const v2 = createV2Adapter(request, logger);
    const state = {
      mode: 'legacy',
      adapter: 'legacy',
      status: null,
      diagnostics: [],
      lastError: null,
      opened: false,
    };

    function note(message, detail) {
      state.diagnostics.push({ at: new Date().toISOString(), message, detail: detail || null });
      if (state.diagnostics.length > 50) state.diagnostics.shift();
      logger(message, detail);
    }

    function assertV2() {
      if (state.adapter !== 'v2') {
        throw new DataPortError('当前数据尚未迁移，禁止调用 V2 数据接口', { code: 'v2_not_ready' });
      }
    }

    async function open() {
      const detection = await detectStatus(request, note);
      state.status = detection.status;
      state.mode = detection.mode;
      state.opened = true;
      state.lastError = detection.error || null;

      if (detection.mode === 'v2_ready') {
        try {
          const snapshot = await v2.load();
          state.adapter = 'v2';
          note('V2 数据读取完成', { notes: snapshot.notes.length, tags: snapshot.tags.length });
          return { mode: state.mode, status: state.status, snapshot, adapter: 'v2', error: null };
        } catch (error) {
          state.adapter = 'v2';
          state.lastError = error;
          note('V2 数据读取失败，保留本地缓存且不写入旧快照', { error: String(error && error.message || error) });
          return { mode: state.mode, status: state.status, snapshot: null, adapter: 'v2', error };
        }
      }

      state.adapter = 'legacy';
      try {
        const snapshot = await legacy.load();
        note('旧版 /api/state 读取完成', { notes: snapshot ? snapshot.notes.length : 0 });
        return { mode: state.mode, status: state.status, snapshot, adapter: 'legacy', error: detection.error || null };
      } catch (error) {
        state.lastError = error;
        note('旧版 /api/state 读取失败，使用本地缓存', { error: String(error && error.message || error) });
        return { mode: state.mode, status: state.status, snapshot: null, adapter: 'legacy', error };
      }
    }

    async function saveLegacy(data) {
      if (state.adapter !== 'legacy') {
        throw new DataPortError('V2 模式禁止写入旧 /api/state，避免双重写入', { code: 'legacy_write_blocked' });
      }
      await legacy.save(data);
    }

    return {
      open,
      saveLegacy,
      get mode() { return state.mode; },
      get adapter() { return state.adapter; },
      get status() { return state.status; },
      get diagnostics() { return state.diagnostics.slice(); },
      get lastError() { return state.lastError; },
      createNote(noteData, tags) { assertV2(); return v2.createNote(noteData, tags); },
      updateNote(noteData, tags) { assertV2(); return v2.updateNote(noteData, tags); },
      getNote(id) { assertV2(); return v2.getNote(id); },
      setFavorite(noteData) { assertV2(); return v2.setFavorite(noteData); },
      trash(noteData) { assertV2(); return v2.trash(noteData); },
      restore(noteData) { assertV2(); return v2.restore(noteData); },
      remove(noteData) { assertV2(); return v2.remove(noteData); },
      createTag(tag) { assertV2(); return v2.createTag(tag); },
      updateTag(tag) { assertV2(); return v2.updateTag(tag); },
      deleteTag(id) { assertV2(); return v2.deleteTag(id); },
      saveSettings(ui) { assertV2(); return v2.saveSettings(ui); },
      fetchTags() { assertV2(); return v2.fetchTags(); },
      refreshTags() { assertV2(); v2.invalidateTags(); return v2.load(); },
    };
  }

  return {
    createDataPort,
    DataPortError,
    ConflictError,
    MODES,
    normalizeLegacy,
    toLegacySnapshot,
    fromV2Note,
    settingsToUi,
  };
});
