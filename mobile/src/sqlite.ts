/** SQLite driver abstraction: node:sqlite for tests, Capacitor SQLite on devices. */

export type SqlValue = string | number | null | Uint8Array;
export type SqlParams = SqlValue[];

export interface SqliteClient {
  exec(sql: string): Promise<void>;
  all<T = Record<string, unknown>>(sql: string, params?: SqlParams): Promise<T[]>;
  get<T = Record<string, unknown>>(sql: string, params?: SqlParams): Promise<T | undefined>;
  run(sql: string, params?: SqlParams): Promise<{ changes: number }>;
}
