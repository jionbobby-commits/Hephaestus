/** Unified mobile DataPort: SQLite + the V2 JSON contract (B1.3). */
import {
  type AIProviderConfig,
  type AIProviderCreateInput,
  type AIProviderParams,
  type AppSettings,
  type AppSettingsPatch,
  type Attachment,
  type ListNotesOptions,
  type Note,
  type NoteCreateInput,
  type NotePage,
  type NotePatchInput,
  type Tag,
  type TagCreateInput,
  type TagUpdateInput,
  ConflictError,
  DataPortError,
  InvalidReferenceError,
  NotFoundError,
  ValidationError,
  DEFAULT_AI_PROVIDER_PARAMS,
  coalesceSettings,
  htmlToText,
  newId,
  nowIso,
  requireTagName,
  requireTitle,
  validateColor,
} from "./contracts.ts";
import { SCHEMA_SQL } from "./schema.ts";
import type { SqliteClient } from "./sqlite.ts";

interface NoteRow {
  id: string; title: string; content_html: string; content_text: string;
  category: string | null; is_favorite: number; favorited_at: string | null;
  is_trashed: number; trashed_at: string | null; created_at: string;
  updated_at: string; revision: number;
}
interface TagRow { id: string; name: string; color: string; created_at: string; updated_at: string; }
interface AttachmentRow {
  id: string; original_name: string; mime: string; size: number;
  sha256: string; kind: Attachment["kind"]; created_at: string;
}
interface ProviderRow {
  id: string; kind: AIProviderConfig["kind"]; label: string; base_url: string;
  model: string; key_ref: string | null; created_at: string; updated_at: string;
  extra_json: string | null;
}

function tagOf(row: TagRow): Tag {
  return { id: row.id, name: row.name, color: row.color, created_at: row.created_at, updated_at: row.updated_at };
}

function attachmentOf(row: AttachmentRow): Attachment {
  return {
    id: row.id, original_name: row.original_name, mime: row.mime, size: Number(row.size),
    sha256: row.sha256, kind: row.kind, created_at: row.created_at,
  };
}

function noteOf(row: NoteRow, tags: Tag[], attachments: Attachment[]): Note {
  return {
    id: row.id, title: row.title, content_html: row.content_html,
    content_text: row.content_text, category: row.category, tags, attachments,
    is_favorite: Boolean(row.is_favorite), is_trashed: Boolean(row.is_trashed),
    favorited_at: row.favorited_at, trashed_at: row.trashed_at,
    created_at: row.created_at, updated_at: row.updated_at, revision: Number(row.revision),
  };
}

function providerParamsOf(value: unknown): AIProviderParams {
  const raw = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const numberOr = (key: keyof AIProviderParams, fallback: number): number => {
    const candidate = raw[key];
    return typeof candidate === "number" && Number.isFinite(candidate) ? candidate : fallback;
  };
  return {
    temperature: numberOr("temperature", DEFAULT_AI_PROVIDER_PARAMS.temperature),
    max_tokens: numberOr("max_tokens", DEFAULT_AI_PROVIDER_PARAMS.max_tokens),
    top_p: numberOr("top_p", DEFAULT_AI_PROVIDER_PARAMS.top_p),
    timeout_seconds: numberOr("timeout_seconds", DEFAULT_AI_PROVIDER_PARAMS.timeout_seconds),
  };
}

function validateProviderParams(input?: Partial<AIProviderParams>): AIProviderParams {
  const params = { ...DEFAULT_AI_PROVIDER_PARAMS, ...(input ?? {}) };
  if (typeof params.temperature !== "number" || !Number.isFinite(params.temperature) || params.temperature < 0 || params.temperature > 2) {
    throw new ValidationError("temperature 必须在 0 到 2 之间");
  }
  if (!Number.isInteger(params.max_tokens) || params.max_tokens < 1 || params.max_tokens > 8192) {
    throw new ValidationError("max_tokens 必须是 1 到 8192 的整数");
  }
  if (typeof params.top_p !== "number" || !Number.isFinite(params.top_p) || params.top_p < 0 || params.top_p > 1) {
    throw new ValidationError("top_p 必须在 0 到 1 之间");
  }
  if (typeof params.timeout_seconds !== "number" || !Number.isFinite(params.timeout_seconds) || params.timeout_seconds < 1 || params.timeout_seconds > 120) {
    throw new ValidationError("timeout_seconds 必须在 1 到 120 之间");
  }
  return params;
}

function providerOf(row: ProviderRow): AIProviderConfig {
  let extra: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(row.extra_json || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) extra = parsed as Record<string, unknown>;
  } catch { /* legacy rows default below */ }
  return {
    id: row.id, kind: row.kind, label: row.label, base_url: row.base_url, model: row.model,
    enabled: extra.enabled !== false,
    is_default: extra.is_default === true,
    params: providerParamsOf(extra.params),
    has_key: Boolean(row.key_ref), created_at: row.created_at, updated_at: row.updated_at,
  };
}

function placeholders(count: number): string { return new Array(count).fill("?").join(", "); }

export class SqliteDataPort {
  private client: SqliteClient;

  constructor(client: SqliteClient) { this.client = client; }

  static async open(client: SqliteClient): Promise<SqliteDataPort> {
    const port = new SqliteDataPort(client);
    await port.initialize();
    return port;
  }

  async initialize(): Promise<void> { await this.client.exec(SCHEMA_SQL); }

  private async transaction<T>(fn: () => Promise<T>): Promise<T> {
    await this.client.exec("BEGIN IMMEDIATE");
    try {
      const result = await fn();
      await this.client.exec("COMMIT");
      return result;
    } catch (error) {
      try { await this.client.exec("ROLLBACK"); } catch { /* already rolled back */ }
      throw error;
    }
  }

  private async tagsByIds(tagIds: string[]): Promise<Tag[]> {
    const ids = [...new Set(tagIds)];
    if (!ids.length) return [];
    const rows = await this.client.all<TagRow>(
      `SELECT * FROM v2_tags WHERE id IN (${placeholders(ids.length)})`, ids,
    );
    const byId = new Map(rows.map((row) => [row.id, tagOf(row)]));
    const missing = ids.filter((id) => !byId.has(id));
    if (missing.length) throw new InvalidReferenceError(`标签不存在: ${missing.join(", ")}`);
    return ids.map((id) => byId.get(id) as Tag);
  }

  private async tagsForNote(noteId: string): Promise<Tag[]> {
    const rows = await this.client.all<TagRow>(
      "SELECT t.* FROM v2_tags t JOIN v2_note_tags nt ON nt.tag_id = t.id WHERE nt.note_id = ? ORDER BY t.created_at, t.id",
      [noteId],
    );
    return rows.map(tagOf);
  }

  private async attachmentsForNote(noteId: string): Promise<Attachment[]> {
    const rows = await this.client.all<AttachmentRow>(
      "SELECT a.* FROM v2_attachments a JOIN v2_note_attachments na ON na.attachment_id = a.id WHERE na.note_id = ? ORDER BY a.created_at, a.id",
      [noteId],
    );
    return rows.map(attachmentOf);
  }

  private async noteRow(noteId: string): Promise<NoteRow> {
    const row = await this.client.get<NoteRow>("SELECT * FROM v2_notes WHERE id = ?", [noteId]);
    if (!row) throw new NotFoundError(`笔记不存在: ${noteId}`);
    return row;
  }

  async listNotes(options: ListNotesOptions = {}): Promise<NotePage> {
    const page = Math.max(1, Math.trunc(options.page ?? 1));
    const pageSize = Math.min(100, Math.max(1, Math.trunc(options.page_size ?? 20)));
    const where: string[] = [];
    const params: (string | number | null | Uint8Array)[] = [];
    const query = (options.query ?? "").trim();
    if (query) {
      where.push("(n.title LIKE ? COLLATE NOCASE OR n.content_text LIKE ? COLLATE NOCASE)");
      params.push(`%${query}%`, `%${query}%`);
    }
    if (options.tag_id) {
      where.push("EXISTS (SELECT 1 FROM v2_note_tags nt WHERE nt.note_id = n.id AND nt.tag_id = ?)");
      params.push(options.tag_id);
    }
    if (options.favorite !== undefined) {
      where.push("n.is_favorite = ?"); params.push(options.favorite ? 1 : 0);
    }
    const trashed = options.trashed ?? false;
    where.push("n.is_trashed = ?"); params.push(trashed ? 1 : 0);
    const clause = where.length ? `WHERE ${where.join(" AND ")}` : "";
    const totalRow = await this.client.get<{ total: number }>(`SELECT COUNT(*) AS total FROM v2_notes n ${clause}`, params);
    const order = options.sort === "created"
      ? "n.created_at DESC, n.id DESC"
      : options.sort === "title" ? "LOWER(n.title) ASC, n.id ASC" : "n.updated_at DESC, n.id DESC";
    const rows = await this.client.all<NoteRow>(
      `SELECT n.* FROM v2_notes n ${clause} ORDER BY ${order} LIMIT ? OFFSET ?`,
      [...params, pageSize, (page - 1) * pageSize],
    );
    const ids = rows.map((row) => row.id);
    const tagsByNote = new Map<string, Tag[]>();
    const attachmentsByNote = new Map<string, Attachment[]>();
    if (ids.length) {
      const tagRows = await this.client.all<TagRow & { note_id: string }>(
        `SELECT t.*, nt.note_id FROM v2_tags t JOIN v2_note_tags nt ON nt.tag_id = t.id WHERE nt.note_id IN (${placeholders(ids.length)}) ORDER BY t.created_at, t.id`,
        ids,
      );
      for (const row of tagRows) {
        const list = tagsByNote.get(row.note_id) ?? []; list.push(tagOf(row)); tagsByNote.set(row.note_id, list);
      }
      const attachmentRows = await this.client.all<AttachmentRow & { note_id: string }>(
        `SELECT a.*, na.note_id FROM v2_attachments a JOIN v2_note_attachments na ON na.attachment_id = a.id WHERE na.note_id IN (${placeholders(ids.length)}) ORDER BY a.created_at, a.id`,
        ids,
      );
      for (const row of attachmentRows) {
        const list = attachmentsByNote.get(row.note_id) ?? []; list.push(attachmentOf(row)); attachmentsByNote.set(row.note_id, list);
      }
    }
    return {
      items: rows.map((row) => noteOf(row, tagsByNote.get(row.id) ?? [], attachmentsByNote.get(row.id) ?? [])),
      total: Number(totalRow?.total ?? 0), page, page_size: pageSize,
    };
  }

  async getNote(noteId: string): Promise<Note> {
    const row = await this.noteRow(noteId);
    return noteOf(row, await this.tagsForNote(noteId), await this.attachmentsForNote(noteId));
  }

  async createNote(input: NoteCreateInput): Promise<Note> {
    const title = requireTitle(input.title);
    return this.transaction(async () => {
      const tags = await this.tagsByIds(input.tags ?? []);
      const now = nowIso();
      const id = newId();
      const html = input.content_html ?? "";
      const text = input.content_text || htmlToText(html);
      const category = input.category ? input.category.trim() || null : null;
      await this.client.run(
        "INSERT INTO v2_notes (id,title,content_html,content_text,category,is_favorite,favorited_at,is_trashed,trashed_at,created_at,updated_at,revision,extra_json) VALUES (?,?,?,?,?,0,NULL,0,NULL,?,?,1,'{}')",
        [id, title, html, text, category, now, now],
      );
      for (const tag of tags) {
        await this.client.run("INSERT INTO v2_note_tags (note_id,tag_id) VALUES (?,?)", [id, tag.id]);
      }
      return this.getNote(id);
    });
  }

  async updateNote(noteId: string, patch: NotePatchInput): Promise<Note> {
    return this.transaction(async () => {
      const row = await this.noteRow(noteId);
      if (patch.revision !== undefined && patch.revision !== Number(row.revision)) {
        throw new ConflictError(`笔记已被修改: 当前 revision=${row.revision}`);
      }
      const fields = new Set(Object.keys(patch));
      const sets: string[] = [];
      const params: (string | number | null)[] = [];
      if (fields.has("title")) {
        const title = requireTitle(patch.title);
        sets.push("title = ?"); params.push(title);
      }
      if (fields.has("content_html")) {
        const html = patch.content_html ?? "";
        sets.push("content_html = ?"); params.push(html);
        if (!fields.has("content_text")) {
          sets.push("content_text = ?"); params.push(htmlToText(html));
        }
      }
      if (fields.has("content_text")) {
        sets.push("content_text = ?"); params.push(patch.content_text ?? "");
      }
      if (fields.has("category")) {
        const category = patch.category ? patch.category.trim() || null : null;
        sets.push("category = ?"); params.push(category);
      }
      if (fields.has("is_favorite")) {
        sets.push("is_favorite = ?", "favorited_at = ?");
        params.push(patch.is_favorite ? 1 : 0, patch.is_favorite ? nowIso() : null);
      }
      sets.push("revision = ?", "updated_at = ?");
      params.push(Number(row.revision) + 1, nowIso(), noteId);
      await this.client.run(`UPDATE v2_notes SET ${sets.join(", ")} WHERE id = ?`, params);
      if (fields.has("tags")) {
        const tags = await this.tagsByIds(patch.tags ?? []);
        await this.client.run("DELETE FROM v2_note_tags WHERE note_id = ?", [noteId]);
        for (const tag of tags) {
          await this.client.run("INSERT INTO v2_note_tags (note_id,tag_id) VALUES (?,?)", [noteId, tag.id]);
        }
      }
      return this.getNote(noteId);
    });
  }

  async setFavorite(noteId: string, favorite: boolean): Promise<Note> {
    return this.transaction(async () => {
      const row = await this.noteRow(noteId);
      await this.client.run(
        "UPDATE v2_notes SET is_favorite = ?, favorited_at = ?, revision = ?, updated_at = ? WHERE id = ?",
        [favorite ? 1 : 0, favorite ? nowIso() : null, Number(row.revision) + 1, nowIso(), noteId],
      );
      return this.getNote(noteId);
    });
  }

  private async trashRow(row: NoteRow): Promise<void> {
    if (Number(row.is_trashed)) return;
    await this.client.run(
      "UPDATE v2_notes SET is_trashed = 1, trashed_at = ?, revision = ?, updated_at = ? WHERE id = ?",
      [nowIso(), Number(row.revision) + 1, nowIso(), row.id],
    );
  }

  async trashNote(noteId: string): Promise<Note> {
    return this.transaction(async () => {
      await this.trashRow(await this.noteRow(noteId));
      return this.getNote(noteId);
    });
  }

  async restoreNote(noteId: string): Promise<Note> {
    return this.transaction(async () => {
      const row = await this.noteRow(noteId);
      if (Number(row.is_trashed)) {
        await this.client.run(
          "UPDATE v2_notes SET is_trashed = 0, trashed_at = NULL, revision = ?, updated_at = ? WHERE id = ?",
          [Number(row.revision) + 1, nowIso(), noteId],
        );
      }
      return this.getNote(noteId);
    });
  }

  async deleteNote(noteId: string, permanent = false): Promise<void> {
    if (!permanent) { await this.trashNote(noteId); return; }
    await this.transaction(async () => {
      await this.noteRow(noteId);
      await this.client.run("DELETE FROM v2_notes WHERE id = ?", [noteId]);
    });
  }

  async listTags(): Promise<Tag[]> {
    const rows = await this.client.all<TagRow>("SELECT * FROM v2_tags ORDER BY created_at, id");
    return rows.map(tagOf);
  }

  async createTag(input: TagCreateInput): Promise<Tag> {
    const name = requireTagName(input.name);
    return this.transaction(async () => {
      const existing = await this.client.get<TagRow>("SELECT * FROM v2_tags WHERE name = ?", [name]);
      if (existing) throw new ConflictError(`标签已存在: ${name}`);
      const now = nowIso();
      const tag = { id: newId(), name, color: validateColor(input.color ?? "#8b8f94"), created_at: now, updated_at: now };
      await this.client.run(
        "INSERT INTO v2_tags (id,name,color,created_at,updated_at) VALUES (?,?,?,?,?)",
        [tag.id, tag.name, tag.color, tag.created_at, tag.updated_at],
      );
      return tag;
    });
  }

  async updateTag(tagId: string, patch: TagUpdateInput): Promise<Tag> {
    return this.transaction(async () => {
      const row = await this.client.get<TagRow>("SELECT * FROM v2_tags WHERE id = ?", [tagId]);
      if (!row) throw new NotFoundError(`标签不存在: ${tagId}`);
      const fields = new Set(Object.keys(patch));
      if (fields.has("name")) {
        const name = requireTagName(patch.name);
        const duplicate = await this.client.get<TagRow>("SELECT * FROM v2_tags WHERE name = ? AND id <> ?", [name, tagId]);
        if (duplicate) throw new ConflictError(`标签已存在: ${name}`);
        row.name = name;
      }
      if (fields.has("color")) row.color = validateColor(patch.color);
      row.updated_at = nowIso();
      await this.client.run("UPDATE v2_tags SET name = ?, color = ?, updated_at = ? WHERE id = ?", [row.name, row.color, row.updated_at, tagId]);
      return tagOf(row);
    });
  }

  async deleteTag(tagId: string): Promise<void> {
    await this.transaction(async () => {
      const row = await this.client.get<TagRow>("SELECT * FROM v2_tags WHERE id = ?", [tagId]);
      if (!row) throw new NotFoundError(`标签不存在: ${tagId}`);
      await this.client.run("DELETE FROM v2_note_tags WHERE tag_id = ?", [tagId]);
      await this.client.run("DELETE FROM v2_tags WHERE id = ?", [tagId]);
    });
  }

  async getSettings(): Promise<AppSettings> {
    const rows = await this.client.all<{ key: string; value_json: string }>("SELECT key, value_json FROM v2_settings");
    const values: Record<string, unknown> = {};
    for (const row of rows) {
      try { values[row.key] = JSON.parse(row.value_json); } catch { /* ignore corrupt row */ }
    }
    return coalesceSettings(values as Partial<AppSettings>);
  }

  async updateSettings(patch: AppSettingsPatch): Promise<AppSettings> {
    await this.transaction(async () => {
      for (const [key, value] of Object.entries(patch)) {
        if (value === undefined) continue;
        await this.client.run(
          "INSERT INTO v2_settings (key,value_json,updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
          [key, JSON.stringify(value), nowIso()],
        );
      }
    });
    return this.getSettings();
  }

  async listAiProviders(): Promise<AIProviderConfig[]> {
    const rows = await this.client.all<ProviderRow>("SELECT * FROM v2_ai_providers ORDER BY created_at, id");
    return rows.map(providerOf);
  }

  async createAiProvider(input: AIProviderCreateInput): Promise<AIProviderConfig> {
    if (input.kind === "ollama") throw new ValidationError("移动端不支持 Ollama，请使用在线 API");
    if (!input.label.trim()) throw new ValidationError("配置名称不能为空");
    if (!/^https?:\/\//.test(input.base_url)) throw new ValidationError("base_url 必须是 http(s) URL");
    if (!input.model.trim()) throw new ValidationError("模型不能为空");
    const now = nowIso();
    const row: ProviderRow = {
      id: newId(), kind: input.kind, label: input.label.trim(), base_url: input.base_url.trim(),
      model: input.model.trim(), key_ref: input.key_ref ?? null, created_at: now, updated_at: now,
      extra_json: JSON.stringify({
        enabled: input.enabled !== false,
        is_default: false,
        params: validateProviderParams(input.params),
      }),
    };
    await this.client.run(
      "INSERT INTO v2_ai_providers (id,kind,label,base_url,model,key_ref,created_at,updated_at,extra_json) VALUES (?,?,?,?,?,?,?,?,?)",
      [row.id, row.kind, row.label, row.base_url, row.model, row.key_ref, row.created_at, row.updated_at, row.extra_json],
    );
    return providerOf(row);
  }

  async deleteAiProvider(providerId: string): Promise<void> {
    const row = await this.client.get<ProviderRow>("SELECT * FROM v2_ai_providers WHERE id = ?", [providerId]);
    if (!row) throw new NotFoundError(`AI 配置不存在: ${providerId}`);
    await this.client.run("DELETE FROM v2_ai_providers WHERE id = ?", [providerId]);
  }

  async listAttachments(noteId: string): Promise<Attachment[]> {
    await this.noteRow(noteId);
    return this.attachmentsForNote(noteId);
  }
}
