/** Node 22+ built-in SQLite adapter, used only by the contract test runner. */
import { DatabaseSync } from "node:sqlite";
import type { SqliteClient, SqlParams } from "./sqlite.ts";

export class NodeSqliteClient implements SqliteClient {
  private db: DatabaseSync;

  constructor(path = ":memory:") {
    this.db = new DatabaseSync(path);
    this.db.exec("PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;");
  }

  async exec(sql: string): Promise<void> { this.db.exec(sql); }

  async all<T>(sql: string, params: SqlParams = []): Promise<T[]> {
    return this.db.prepare(sql).all(...params) as T[];
  }

  async get<T>(sql: string, params: SqlParams = []): Promise<T | undefined> {
    return this.db.prepare(sql).get(...params) as T | undefined;
  }

  async run(sql: string, params: SqlParams = []): Promise<{ changes: number }> {
    const result = this.db.prepare(sql).run(...params);
    return { changes: Number(result.changes ?? 0) };
  }

  close(): void { this.db.close(); }
}
