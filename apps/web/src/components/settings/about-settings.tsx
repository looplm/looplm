"use client";

import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import {
  getVersion,
  getLatestVersion,
  type VersionInfo,
  type LatestVersionInfo,
} from "@/lib/api";

const WEB_VERSION = process.env.NEXT_PUBLIC_APP_VERSION ?? "unknown";

// Parses "0.5.0" or "v0.5.0" into [0, 5, 0]. Returns null if the string can't
// be parsed as a strict semver triple.
function parseVersion(v: string | null | undefined): number[] | null {
  if (!v) return null;
  const m = v.trim().replace(/^v/, "").match(/^(\d+)\.(\d+)\.(\d+)/);
  if (!m) return null;
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

// Returns -1 if a < b, 0 if equal, 1 if a > b. Null if either is unparseable.
function compareVersions(a: string | null | undefined, b: string | null | undefined): number | null {
  const pa = parseVersion(a);
  const pb = parseVersion(b);
  if (!pa || !pb) return null;
  for (let i = 0; i < 3; i++) {
    if (pa[i] !== pb[i]) return pa[i] < pb[i] ? -1 : 1;
  }
  return 0;
}

function formatDate(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

export default function AboutSettings() {
  const [info, setInfo] = useState<VersionInfo | null>(null);
  const [latest, setLatest] = useState<LatestVersionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getVersion()
      .then(setInfo)
      .catch(() => setError("Could not load API version"));
    getLatestVersion()
      .then(setLatest)
      .catch(() => {
        // Silent — the update card just doesn't render.
      });
  }, []);

  const cmp = latest?.latest?.tag ? compareVersions(info?.api, latest.latest.tag) : null;
  const updateAvailable = cmp !== null && cmp < 0;

  return (
    <div className="space-y-6">
      <div className="p-6 rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800">
        <h2 className="text-lg font-semibold mb-4">About</h2>

        <dl className="grid grid-cols-1 sm:grid-cols-[160px_1fr] gap-x-6 gap-y-3 text-sm">
          <dt className="text-gray-500 dark:text-slate-400">Web</dt>
          <dd className="font-mono">v{WEB_VERSION}</dd>

          <dt className="text-gray-500 dark:text-slate-400">API</dt>
          <dd className="font-mono">
            {info ? `v${info.api}` : error ? <span className="text-red-500">{error}</span> : "…"}
          </dd>

          <dt className="text-gray-500 dark:text-slate-400">Connectors</dt>
          <dd className="font-mono">{info?.connectors ? `v${info.connectors}` : "—"}</dd>

          <dt className="text-gray-500 dark:text-slate-400">Commit</dt>
          <dd className="font-mono">{info?.commit ? info.commit.slice(0, 12) : "—"}</dd>
        </dl>

        <p className="mt-6 text-xs text-gray-500 dark:text-slate-400">
          LoopLM is open source —{" "}
          <a
            href="https://github.com/looplm/looplm"
            target="_blank"
            rel="noreferrer"
            className="text-indigo-600 dark:text-indigo-400 hover:underline"
          >
            github.com/looplm/looplm
          </a>
        </p>
      </div>

      {latest && info && <UpdateCard latest={latest} updateAvailable={updateAvailable} />}
    </div>
  );
}

interface UpdateCardProps {
  latest: LatestVersionInfo;
  updateAvailable: boolean;
}

function UpdateCard({ latest, updateAvailable }: UpdateCardProps) {
  if (!latest.enabled) {
    return (
      <div className="p-4 rounded-xl bg-gray-50 dark:bg-slate-900/50 border border-gray-100 dark:border-slate-800 text-sm text-gray-500 dark:text-slate-400">
        Update checks are disabled (UPDATE_CHECK_ENABLED=false).
      </div>
    );
  }

  if (latest.error || !latest.latest) {
    return (
      <div className="p-4 rounded-xl bg-gray-50 dark:bg-slate-900/50 border border-gray-100 dark:border-slate-800 text-sm text-gray-500 dark:text-slate-400">
        Could not check for updates right now.
      </div>
    );
  }

  const release = latest.latest;

  if (!updateAvailable) {
    return (
      <div className="p-4 rounded-xl bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-900/50 text-sm">
        <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300">
          <span aria-hidden>✓</span>
          <span>You&apos;re running the latest version.</span>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 rounded-xl bg-indigo-50 dark:bg-indigo-950/30 border border-indigo-200 dark:border-indigo-900/50">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-base font-semibold text-indigo-900 dark:text-indigo-200">
          Update available: {release.tag}
        </h3>
        {release.published_at && (
          <span className="text-xs text-indigo-700/70 dark:text-indigo-300/70">
            Released {formatDate(release.published_at)}
          </span>
        )}
      </div>

      <p className="mt-2 text-sm text-indigo-900/80 dark:text-indigo-200/80">
        You&apos;re running <span className="font-mono">v{latest.running}</span>. Pull the latest
        image and restart:
      </p>

      <pre className="mt-3 px-3 py-2 rounded-lg bg-indigo-100/70 dark:bg-indigo-900/40 text-xs font-mono text-indigo-900 dark:text-indigo-100 overflow-x-auto">
        docker compose pull && docker compose up -d
      </pre>

      <p className="mt-2 text-xs text-indigo-800/70 dark:text-indigo-300/70">
        Then run <span className="font-mono">poetry run alembic upgrade head</span> in the api
        container if migrations are pending.
      </p>

      {release.body && (
        <details className="mt-4 group">
          <summary className="text-sm cursor-pointer text-indigo-700 dark:text-indigo-300 hover:underline list-none">
            <span className="group-open:hidden">Show release notes</span>
            <span className="hidden group-open:inline">Hide release notes</span>
          </summary>
          <div className="mt-3 prose prose-sm dark:prose-invert max-w-none prose-headings:text-indigo-900 dark:prose-headings:text-indigo-200">
            <Markdown>{release.body}</Markdown>
          </div>
        </details>
      )}

      {release.html_url && (
        <a
          href={release.html_url}
          target="_blank"
          rel="noreferrer"
          className="mt-4 inline-block text-sm text-indigo-700 dark:text-indigo-300 hover:underline"
        >
          View release on GitHub →
        </a>
      )}
    </div>
  );
}
