/** Shared V2 JSON data contract for the mobile DataPort (B1.1/B1.3). */

export const CONTRACT_VERSION = "2.0";
export const SCHEMA_VERSION = 1;

export const LOCALES = ["zh-CN", "zh-TW", "en", "ja", "ko", "fr", "de", "es", "pt", "ru"] as const;
export const THEMES = ["light", "dark", "system"] as const;
export const LAYOUTS = ["list", "grid"] as const;
export const SORTS = ["updated", "created", "title"] as const;
export const PROVIDER_KINDS = ["ollama", "openai", "anthropic", "gemini", "deepseek", "qwen", "custom"] as const;

export type Locale = (typeof LOCALES)[number];
export type Theme = (typeof THEMES)[number];
export type Layout = (typeof LAYOUTS)[number];
export type Sort = (typeof SORTS)[number];
export type ProviderKind = (typeof PROVIDER_KINDS)[number];

export interface Tag {
  id: string;
  name: string;
  color: string;
  created_at: string;
  updated_at: string;
}

export interface Attachment {
  id: string;
  original_name: string;
  mime: string;
  size: number;
  sha256: string;
  kind: "image" | "document" | "audio" | "other";
  created_at: string;
}

export interface Note {
  id: string;
  title: string;
  content_html: string;
  content_text: string;
  category: string | null;
  tags: Tag[];
  attachments: Attachment[];
  is_favorite: boolean;
  is_trashed: boolean;
  favorited_at: string | null;
  trashed_at: string | null;
  created_at: string;
  updated_at: string;
  revision: number;
}

export interface NotePage {
  items: Note[];
  total: number;
  page: number;
  page_size: number;
}

export interface AppSettings {
  locale: Locale;
  theme: Theme;
  layout: Layout;
  sort: Sort;
  assistant_name: string;
  assistant_style: "concise" | "friendly" | "detailed";
  response_length: "short" | "medium" | "long";
  default_model: string | null;
}

export interface AIProviderParams {
  temperature: number;
  max_tokens: number;
  top_p: number;
  timeout_seconds: number;
}

export const DEFAULT_AI_PROVIDER_PARAMS: AIProviderParams = {
  temperature: 0.7,
  max_tokens: 1024,
  top_p: 1.0,
  timeout_seconds: 30,
};

export interface AIProviderConfig {
  id: string;
  kind: ProviderKind;
  label: string;
  base_url: string;
  model: string;
  enabled: boolean;
  is_default: boolean;
  params: AIProviderParams;
  has_key: boolean;
  created_at: string;
  updated_at: string;
}

export type MessageStatus = "pending" | "streaming" | "complete" | "stopped" | "error";
export type MessageRole = "user" | "assistant" | "system";

export interface Conversation {
  id: string;
  title: string;
  provider_id: string | null;
  model: string;
  system_prompt: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  revision: number;
  message_count: number;
}

export interface ConversationPage {
  items: Conversation[];
  total: number;
  page: number;
  page_size: number;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  status: MessageStatus;
  sequence: number;
  client_id: string | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
  revision: number;
}

export interface MessagePage {
  items: Message[];
  total: number;
  page: number;
  page_size: number;
}

export interface ConversationDetail {
  conversation: Conversation;
  messages: Message[];
  total: number;
  page: number;
  page_size: number;
}

export interface ConversationCreateInput {
  provider_id: string;
  model?: string | null;
  title?: string;
  system_prompt?: string | null;
}

export interface ConversationPatchInput {
  title?: string;
  provider_id?: string;
  model?: string;
  system_prompt?: string | null;
  archived?: boolean;
  revision?: number;
}

export interface SendMessageInput {
  content: string;
  client_message_id?: string | null;
  stream?: boolean;
}

export interface ChatReply {
  conversation: Conversation;
  user_message: Message;
  assistant_message: Message;
  finish_reason: string | null;
  usage: { prompt_tokens?: number | null; completion_tokens?: number | null; total_tokens?: number | null } | null;
}

export interface StopGenerationResult {
  stopped: boolean;
  message: Message | null;
}

export interface ListNotesOptions {
  query?: string;
  tag_id?: string;
  favorite?: boolean;
  trashed?: boolean;
  page?: number;
  page_size?: number;
  sort?: Sort;
}

export interface NoteCreateInput {
  title: string;
  content_html?: string;
  content_text?: string;
  category?: string | null;
  tags?: string[];
}

export interface NotePatchInput {
  title?: string;
  content_html?: string;
  content_text?: string;
  category?: string | null;
  tags?: string[];
  is_favorite?: boolean;
  revision?: number;
}

export interface TagCreateInput { name: string; color?: string; }
export interface TagUpdateInput { name?: string; color?: string; }
export interface AppSettingsPatch {
  locale?: Locale;
  theme?: Theme;
  layout?: Layout;
  sort?: Sort;
  assistant_name?: string;
  assistant_style?: AppSettings["assistant_style"];
  response_length?: AppSettings["response_length"];
  default_model?: string | null;
}
export interface AIProviderCreateInput {
  kind: ProviderKind;
  label: string;
  base_url: string;
  model: string;
  /** Opaque locator only; raw provider secrets never live in the frontend. */
  key_ref?: string | null;
  enabled?: boolean;
  params?: Partial<AIProviderParams>;
}

export const DEFAULT_SETTINGS: AppSettings = {
  locale: "zh-CN",
  theme: "system",
  layout: "list",
  sort: "updated",
  assistant_name: "赫淮斯托斯",
  assistant_style: "friendly",
  response_length: "medium",
  default_model: null,
};

export class DataPortError extends Error {}
export class NotFoundError extends DataPortError {}
export class ConflictError extends DataPortError {}
export class InvalidReferenceError extends DataPortError {}
export class ValidationError extends DataPortError {}

export const ISO_UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;
export const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

export function nowIso(): string { return new Date().toISOString(); }

export function newId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c?.randomUUID) return c.randomUUID().replace(/-/g, "");
  return `id_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 12)}`;
}

export function htmlToText(html: string): string {
  return html
    .replace(/<\s*(br|\/p|\/div|\/li|\/h[1-6])\s*>/gi, " ")
    .replace(/<[^>]*>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

export function requireTitle(value: unknown): string {
  if (typeof value !== "string") throw new ValidationError("标题必须是字符串");
  const title = value.trim();
  if (!title) throw new ValidationError("标题不能为空");
  if (title.length > 120) throw new ValidationError("标题不能超过 120 个字符");
  return title;
}

export function requireTagName(value: unknown): string {
  if (typeof value !== "string") throw new ValidationError("标签名必须是字符串");
  const name = value.trim();
  if (!name) throw new ValidationError("标签名不能为空");
  if (name.length > 32) throw new ValidationError("标签名不能超过 32 个字符");
  return name;
}

export function validateColor(value: unknown): string {
  if (typeof value !== "string" || !/^#[0-9a-fA-F]{6}$/.test(value)) {
    throw new ValidationError("颜色必须是 #RRGGBB");
  }
  return value.toLowerCase();
}

export function coalesceSettings(values: Partial<AppSettings>): AppSettings {
  return { ...DEFAULT_SETTINGS, ...values };
}