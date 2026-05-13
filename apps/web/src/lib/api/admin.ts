import { request } from "./client";

export interface PendingRevision {
  revision: string;
  message: string | null;
}

export interface MigrationsStatus {
  current_rev: string | null;
  head_rev: string | null;
  pending: PendingRevision[];
}

export interface MigrationUpgradeResult {
  success: boolean;
  before_rev: string | null;
  after_rev: string | null;
  output: string;
}

export function getMigrations(): Promise<MigrationsStatus> {
  return request<MigrationsStatus>("/api/admin/migrations");
}

export function runMigrations(): Promise<MigrationUpgradeResult> {
  return request<MigrationUpgradeResult>("/api/admin/migrations/upgrade", {
    method: "POST",
  });
}
