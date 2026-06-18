"use client";

import { useEffect, useState } from "react";
import { getMe, logout } from "@/lib/api";
import LoopLMIcon from "@/components/looplm-icon";

/**
 * Shown to a signed-in user who belongs to no project yet. Regular sign-ups
 * cannot create projects — an admin has to add them. This screen surfaces the
 * user's email with a one-tap copy so they can hand it to their admin.
 */
export default function NoProjectGate() {
  const [email, setEmail] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    getMe()
      .then((me) => setEmail(me.email))
      .catch(() => {});
  }, []);

  async function copyEmail() {
    if (!email) return;
    try {
      await navigator.clipboard.writeText(email);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard unavailable — ignore
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md text-center">
        <div className="flex items-center justify-center gap-2 mb-6">
          <LoopLMIcon className="w-7 h-7 text-indigo-400" />
          <span className="text-xl font-bold tracking-tight">
            <span className="text-indigo-400">Loop</span>LM
          </span>
        </div>

        <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl p-8 shadow-sm">
          <h1 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
            You&apos;re not in a project yet
          </h1>
          <p className="text-sm text-gray-500 dark:text-slate-400 mb-6">
            Ask your admin to add you to a project. Copy your email below and
            send it to them so they can invite you.
          </p>

          <div className="flex items-stretch gap-2 mb-2">
            <div className="flex-1 px-3 py-2 rounded-lg bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm text-gray-700 dark:text-slate-200 truncate text-left flex items-center">
              {email || "…"}
            </div>
            <button
              onClick={copyEmail}
              disabled={!email}
              className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-500 disabled:opacity-50 transition-colors whitespace-nowrap"
            >
              {copied ? "Copied!" : "Copy email"}
            </button>
          </div>
          <p className="text-xs text-gray-400 dark:text-slate-500 mb-6 text-left">
            Once an admin adds you, refresh this page to get started.
          </p>

          <div className="flex items-center justify-center gap-4 text-sm">
            <button
              onClick={() => window.location.reload()}
              className="text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              Refresh
            </button>
            <span className="text-gray-300 dark:text-slate-700">|</span>
            <button
              onClick={logout}
              className="text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white"
            >
              Sign out
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
