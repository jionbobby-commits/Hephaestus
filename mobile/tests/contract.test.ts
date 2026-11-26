import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  ConflictError,
  InvalidReferenceError,
  NotFoundError,
  ValidationError,
  ISO_UTC,
} from "../src/contracts.ts";
import { SqliteDataPort } from "../src/dataport.ts";
import { NodeSqliteClient } from "../src/node-sqlite.ts";

const fixture = JSON.parse(readFileSync(new URL("../../contracts/v2/contract_fixture.json", import.meta.url), "utf8"));

test("shared JSON fixture matches the mobile contract", () => {
  assert.equal(fixture.contract_version, "2.0");
  const note = fixture.note;
  assert.deepEqual(Object.keys(note).sort(), [
    "attachments", "category", "content_html", "content_text", "created_at", "favorited_at",
    "id", "is_favorite", "is_trashed", "revision", "tags", "title", "trashed_at", "updated_at",
  ].sort());
  assert.match(note.created_at, ISO_UTC);
  assert.match(note.updated_at, ISO_UTC);
  assert.equal(note.tags[0].id, fixture.tag.id);
  assert.equal(note.is_favorite, true);
  assert.equal(note.revision, 3);
  assert.equal(fixture.provider.has_key, false);
  assert.equal(fixture.provider.enabled, true);
  assert.equal(fixture.provider.is_default, false);
  assert.equal(fixture.provider.params.temperature, 0.7);
  assert.equal("key_ref" in fixture.provider, false);
});

test("mobile DataPort implements note, tag, favorite and trash semantics", async () => {
  const client = new NodeSqliteClient();
  const port = await SqliteDataPort.open(client);
  try {
    const tag = await port.createTag({ name: "工作", color: "#7c83e6" });
    assert.equal(tag.name, "工作");
    await assert.rejects(() => port.createTag({ name: "工作" }), ConflictError);

    const note = await port.createNote({
      title: "移动端契约", content_html: "<p>正文</p>", tags: [tag.id],
    });
    assert.equal(note.title, "移动端契约");
    assert.equal(note.content_text, "正文");
    assert.equal(note.revision, 1);
    assert.equal(note.tags[0].id, tag.id);

    const page = await port.listNotes({ query: "正文" });
    assert.equal(page.total, 1);
    assert.equal(page.items[0].id, note.id);

    const updated = await port.updateNote(note.id, { title: "已修改", revision: 1 });
    assert.equal(updated.revision, 2);
    await assert.rejects(
      () => port.updateNote(note.id, { title: "冲突", revision: 1 }),
      ConflictError,
    );

    const favorite = await port.setFavorite(note.id, true);
    assert.equal(favorite.is_favorite, true);
    assert.equal((await port.listNotes({ favorite: true })).total, 1);

    await port.trashNote(note.id);
    assert.equal((await port.listNotes()).total, 0);
    assert.equal((await port.listNotes({ trashed: true })).total, 1);

    const restored = await port.restoreNote(note.id);
    assert.equal(restored.is_trashed, false);
    await port.deleteNote(note.id, true);
    await assert.rejects(() => port.getNote(note.id), NotFoundError);
  } finally {
    client.close();
  }
});

test("mobile DataPort validates references and title/transaction boundaries", async () => {
  const client = new NodeSqliteClient();
  const port = await SqliteDataPort.open(client);
  try {
    await assert.rejects(() => port.createNote({ title: "   " }), ValidationError);
    await assert.rejects(
      () => port.createNote({ title: "坏引用", tags: ["missing"] }),
      InvalidReferenceError,
    );
    assert.equal((await port.listNotes()).total, 0);
  } finally {
    client.close();
  }
});

test("mobile DataPort settings and AI config never expose key_ref", async () => {
  const client = new NodeSqliteClient();
  const port = await SqliteDataPort.open(client);
  try {
    const defaults = await port.getSettings();
    assert.equal(defaults.locale, "zh-CN");
    assert.equal(defaults.theme, "system");
    const changed = await port.updateSettings({ theme: "dark", locale: "en" });
    assert.equal(changed.theme, "dark");
    assert.equal(changed.locale, "en");

    const provider = await port.createAiProvider({
      kind: "custom", label: "在线 API", base_url: "https://api.example.com/v1",
      model: "model-x", key_ref: "secret-ref", params: { max_tokens: 256 },
    });
    assert.equal(provider.has_key, true);
    assert.equal(provider.enabled, true);
    assert.equal(provider.is_default, false);
    assert.equal(provider.params.max_tokens, 256);
    assert.equal("key_ref" in provider, false);
    const rows = await port.listAiProviders();
    assert.equal(rows.length, 1);
    assert.equal("key_ref" in rows[0], false);
    await assert.rejects(
      () => port.createAiProvider({
        kind: "ollama", label: "本地", base_url: "http://127.0.0.1:11434", model: "qwen3",
      }),
      ValidationError,
    );
  } finally {
    client.close();
  }
});

test("mobile DataPort pagination and attachment listing are contract-stable", async () => {
  const client = new NodeSqliteClient();
  const port = await SqliteDataPort.open(client);
  try {
    for (const title of ["A", "B", "C"]) await port.createNote({ title });
    const page = await port.listNotes({ page: 2, page_size: 2 });
    assert.equal(page.total, 3);
    assert.equal(page.page, 2);
    assert.equal(page.page_size, 2);
    assert.equal(page.items.length, 1);

    const note = await port.createNote({ title: "附件宿主" });
    await client.run(
      "INSERT INTO v2_attachments (id,original_name,mime,size,sha256,kind,stored_name,created_at) VALUES (?,?,?,?,?,?,?,?)",
      ["att1", "a.png", "image/png", 3, "0".repeat(64), "image", "stored_a.png", new Date().toISOString()],
    );
    await client.run("INSERT INTO v2_note_attachments (note_id,attachment_id) VALUES (?,?)", [note.id, "att1"]);
    const attachments = await port.listAttachments(note.id);
    assert.equal(attachments.length, 1);
    assert.equal(attachments[0].original_name, "a.png");
  } finally {
    client.close();
  }
});

test("mobile DataPort conversation and message contract", async () => {
  const client = new NodeSqliteClient();
  const port = await SqliteDataPort.open(client);
  try {
    const conversation = await port.createConversation({ provider_id: "provider-mobile-1", title: "  " });
    assert.equal(conversation.title, "新对话");
    assert.equal(conversation.revision, 1);
    assert.equal(conversation.message_count, 0);

    const user = await port.appendMessage(conversation.id, {
      role: "user", content: "你好", clientId: "client-1",
    });
    const duplicate = await port.appendMessage(conversation.id, {
      role: "user", content: "重复提交", clientId: "client-1",
    });
    assert.equal(duplicate.id, user.id);
    const assistant = await port.appendMessage(conversation.id, {
      role: "assistant", content: "你好，我是赫淮斯托斯", status: "complete",
    });
    assert.equal(assistant.sequence, 2);

    const messages = await port.listMessages(conversation.id);
    assert.equal(messages.total, 2);
    assert.deepEqual(messages.items.map((item) => item.role), ["user", "assistant"]);

    const renamed = await port.updateConversation(conversation.id, {
      title: "移动端会话", revision: conversation.revision,
    });
    assert.equal(renamed.title, "移动端会话");
    assert.equal(renamed.revision, 2);
    await assert.rejects(
      () => port.updateConversation(conversation.id, { title: "冲突", revision: 1 }),
      ConflictError,
    );

    const archived = await port.updateConversation(conversation.id, {
      archived: true, revision: renamed.revision,
    });
    assert.notEqual(archived.archived_at, null);
    assert.equal((await port.listConversations()).total, 0);
    assert.equal((await port.listConversations(true)).total, 1);

    const failed = await port.updateMessage(assistant.id, {
      status: "error", error_code: "provider_unavailable",
    });
    assert.equal(failed.status, "error");
    assert.equal(failed.error_code, "provider_unavailable");
    assert.equal(failed.revision, 2);

    await port.deleteConversation(conversation.id);
    await assert.rejects(() => port.getConversation(conversation.id), NotFoundError);
    assert.equal((await port.listMessages(conversation.id).catch((error) => error)) instanceof NotFoundError, true);
  } finally {
    client.close();
  }
});
