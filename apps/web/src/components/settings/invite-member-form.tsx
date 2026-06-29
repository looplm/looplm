"use client";

import { useState } from "react";
import { inviteProjectMember, type InviteResponse } from "@/lib/api";
import {
  ALL_SECTIONS,
  ALL_PAGES,
  SECTION_PAGES,
  pagesForSections,
} from "./permission-constants";

export default function InviteMemberForm({
  projectId,
  onInvited,
  onError,
}: {
  projectId: string;
  onInvited: () => void | Promise<void>;
  onError: (message: string | null) => void;
}) {
  const [lastInvite, setLastInvite] = useState<InviteResponse | null>(null);
  const [copied, setCopied] = useState(false);

  // Invite form
  const [email, setEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [inviteSections, setInviteSections] = useState<string[]>([...ALL_SECTIONS]);
  const [invitePages, setInvitePages] = useState<string[] | null>(null);
  const [inviteWritePages, setInviteWritePages] = useState<string[]>([]);
  const [showPageDetail, setShowPageDetail] = useState(false);
  const [inviting, setInviting] = useState(false);

  function resetInviteForm() {
    setEmail("");
    setInviteRole("member");
    setInviteSections([...ALL_SECTIONS]);
    setInvitePages(null);
    setInviteWritePages([]);
    setShowPageDetail(false);
  }

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!projectId || !email.trim()) return;
    setInviting(true);
    onError(null);
    setLastInvite(null);
    try {
      // Clamp write_pages to allowed pages before sending
      const effectiveAllowedPages =
        invitePages !== null ? invitePages : pagesForSections(inviteSections);
      const writes = inviteWritePages.filter((p) => effectiveAllowedPages.includes(p));
      const result = await inviteProjectMember(projectId, {
        email: email.trim(),
        role: inviteRole,
        allowed_sections: inviteSections,
        allowed_pages: invitePages,
        write_pages: writes,
      });
      if (result.status === "pending") {
        setLastInvite(result);
      }
      resetInviteForm();
      await onInvited();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : "Failed to invite member");
    } finally {
      setInviting(false);
    }
  }

  function handleCopyLink() {
    if (!lastInvite?.invite_link) return;
    navigator.clipboard.writeText(lastInvite.invite_link);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function handleInviteSectionToggle(section: string) {
    setInviteSections((prev) => {
      const next = prev.includes(section)
        ? prev.filter((s) => s !== section)
        : [...prev, section];
      const sectionPages = SECTION_PAGES[section] || [];
      if (!next.includes(section)) {
        if (invitePages !== null) {
          const cleaned = invitePages.filter((p) => !sectionPages.includes(p));
          setInvitePages(cleaned.length > 0 ? cleaned : null);
        }
        setInviteWritePages((w) => w.filter((p) => !sectionPages.includes(p)));
      }
      return next;
    });
  }

  function handleInvitePageToggle(page: string) {
    const section = ALL_PAGES.includes(page) ? Object.keys(SECTION_PAGES).find((s) => SECTION_PAGES[s].includes(page)) : undefined;
    if (!section) return;
    let nextPages: string[] | null;
    if (invitePages === null) {
      // Currently all pages — unchecking one collapses to an explicit list minus that page
      const all = pagesForSections(inviteSections);
      nextPages = all.filter((p) => p !== page);
    } else {
      const toggled = invitePages.includes(page)
        ? invitePages.filter((p) => p !== page)
        : [...invitePages, page];
      const all = pagesForSections(inviteSections);
      nextPages = all.every((p) => toggled.includes(p)) ? null : toggled;
    }
    setInvitePages(nextPages);
    // If page is no longer allowed, remove from write_pages
    const effective = nextPages === null ? pagesForSections(inviteSections) : nextPages;
    setInviteWritePages((w) => w.filter((p) => effective.includes(p)));
  }

  function handleInviteWriteToggle(page: string) {
    setInviteWritePages((prev) => {
      if (prev.includes(page)) return prev.filter((p) => p !== page);
      // Enabling write implies page must be readable
      if (invitePages !== null && !invitePages.includes(page)) {
        setInvitePages([...invitePages, page]);
      }
      return [...prev, page];
    });
  }

  function isInvitePageChecked(page: string): boolean {
    if (invitePages === null) return true;
    return invitePages.includes(page);
  }

  function isInviteWriteChecked(page: string): boolean {
    return inviteWritePages.includes(page);
  }

  return (
    <div className="rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6">
      <h3 className="text-lg font-semibold mb-4">Invite Member</h3>
      <form onSubmit={handleInvite} className="space-y-4">
        <div className="flex gap-3 flex-wrap">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email address"
            required
            className="flex-1 min-w-[200px] px-3 py-2 rounded-lg border border-gray-300 dark:border-slate-700 bg-gray-50 dark:bg-slate-800 text-sm text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
          />
          <select
            value={inviteRole}
            onChange={(e) => setInviteRole(e.target.value)}
            className="px-3 py-2 rounded-lg border border-gray-300 dark:border-slate-700 bg-gray-50 dark:bg-slate-800 text-sm text-gray-900 dark:text-white"
          >
            <option value="member">Member</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-600 dark:text-slate-400">Sections:</span>
          {ALL_SECTIONS.map((section) => (
            <label key={section} className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={inviteSections.includes(section)}
                onChange={() => handleInviteSectionToggle(section)}
                className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
              />
              <span className="capitalize text-gray-700 dark:text-slate-300">{section}</span>
            </label>
          ))}
        </div>
        <div>
          <button
            type="button"
            onClick={() => {
              setShowPageDetail(!showPageDetail);
              if (showPageDetail) {
                setInvitePages(null);
                setInviteWritePages([]);
              }
            }}
            className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
          >
            {showPageDetail ? "Hide page-level access" : "Customize page-level access"}
          </button>
          {showPageDetail && (
            <div className="mt-2 space-y-3 pl-1">
              <p className="text-xs text-gray-500 dark:text-slate-400">
                {inviteRole === "admin"
                  ? "Admins have write access everywhere — write toggles are cosmetic."
                  : "New members default to read-only. Check Write to grant mutation access per page."}
              </p>
              {ALL_SECTIONS.filter((s) => inviteSections.includes(s)).map((section) => (
                <div key={section}>
                  <span className="text-xs font-medium text-gray-500 dark:text-slate-400 capitalize">{section}</span>
                  <div className="mt-1 ml-2 space-y-0.5">
                    {(SECTION_PAGES[section] || []).map((page) => {
                      const readable = isInvitePageChecked(page);
                      return (
                        <div key={page} className="flex items-center gap-4 text-xs">
                          <label className="flex items-center gap-1 min-w-[120px]">
                            <input
                              type="checkbox"
                              checked={readable}
                              onChange={() => handleInvitePageToggle(page)}
                              className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500 h-3.5 w-3.5"
                            />
                            <span className="capitalize text-gray-600 dark:text-slate-300">{page}</span>
                          </label>
                          <label className="flex items-center gap-1 text-gray-500 dark:text-slate-400">
                            <input
                              type="checkbox"
                              checked={isInviteWriteChecked(page)}
                              disabled={!readable && !isInviteWriteChecked(page)}
                              onChange={() => handleInviteWriteToggle(page)}
                              className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500 h-3.5 w-3.5 disabled:opacity-40"
                            />
                            <span>Write</span>
                          </label>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <button
          type="submit"
          disabled={inviting || !email.trim()}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-500 disabled:opacity-50 transition-colors"
        >
          {inviting ? "Inviting..." : "Invite"}
        </button>
      </form>

      {/* Invite link banner */}
      {lastInvite && lastInvite.status === "pending" && lastInvite.invite_link && (
        <div className="mt-4 rounded-lg bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-200 dark:border-indigo-800 px-4 py-3">
          <p className="text-sm text-indigo-700 dark:text-indigo-300 mb-2">
            {lastInvite.email_sent
              ? `Invitation email sent to ${lastInvite.email}. You can also share this link:`
              : `${lastInvite.email} is not registered yet. Share this invite link:`}
          </p>
          <div className="flex items-center gap-2">
            <input
              type="text"
              readOnly
              value={lastInvite.invite_link}
              className="flex-1 px-3 py-1.5 rounded border border-indigo-200 dark:border-indigo-700 bg-white dark:bg-slate-800 text-xs text-gray-700 dark:text-slate-300 font-mono"
            />
            <button
              onClick={handleCopyLink}
              className="px-3 py-1.5 bg-indigo-600 text-white rounded text-xs font-medium hover:bg-indigo-500 transition-colors whitespace-nowrap"
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
