"use client";

import { useEffect, useState } from "react";
import {
  getProjectMembers,
  inviteProjectMember,
  updateProjectMember,
  removeProjectMember,
  type ProjectMember,
  type InviteResponse,
} from "@/lib/api";

const ALL_SECTIONS = ["observe", "evaluate", "improve"] as const;

const SECTION_PAGES: Record<string, string[]> = {
  observe: ["dashboard", "traces", "analytics", "feedback", "costs", "data-sources"],
  evaluate: ["evaluations", "evaluators", "datasets"],
  improve: ["advisor", "routes", "prompts"],
};

const ALL_PAGES = Object.values(SECTION_PAGES).flat();

function pagesForSections(sections: string[]): string[] {
  return sections.flatMap((s) => SECTION_PAGES[s] || []);
}

export default function MembersSettings({ projectId }: { projectId: string | null }) {
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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

  // Expanded rows for page-level editing
  const [expandedMembers, setExpandedMembers] = useState<Set<string>>(new Set());

  async function loadMembers() {
    if (!projectId) return;
    setLoading(true);
    try {
      const { data } = await getProjectMembers(projectId);
      setMembers(data);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load members");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadMembers();
  }, [projectId]);

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
    setError(null);
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
      await loadMembers();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to invite member");
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

  async function handleToggleSection(member: ProjectMember, section: string) {
    if (!projectId) return;
    const current = member.allowed_sections;
    const updated = current.includes(section)
      ? current.filter((s) => s !== section)
      : [...current, section];
    try {
      await updateProjectMember(projectId, member.id, { allowed_sections: updated });
      await loadMembers();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to update member");
    }
  }

  async function handleTogglePage(member: ProjectMember, page: string) {
    if (!projectId) return;
    const currentPages = member.allowed_pages;
    let updatedPages: string[] | null;

    if (currentPages === null) {
      const all = pagesForSections(member.allowed_sections);
      updatedPages = all.filter((p) => p !== page);
    } else {
      const next = currentPages.includes(page)
        ? currentPages.filter((p) => p !== page)
        : [...currentPages, page];
      const all = pagesForSections(member.allowed_sections);
      updatedPages = all.every((p) => next.includes(p)) ? null : next;
    }

    try {
      await updateProjectMember(projectId, member.id, { allowed_pages: updatedPages });
      await loadMembers();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to update member");
    }
  }

  async function handleToggleMemberWrite(member: ProjectMember, page: string) {
    if (!projectId) return;
    const currentWrite = member.write_pages;
    const currentAllowed =
      member.allowed_pages ?? pagesForSections(member.allowed_sections);

    let nextWrite: string[];
    if (currentWrite === null) {
      // Legacy full-write: materialize the list and toggle
      nextWrite = currentAllowed.filter((p) => p !== page);
    } else if (currentWrite.includes(page)) {
      nextWrite = currentWrite.filter((p) => p !== page);
    } else {
      nextWrite = [...currentWrite, page];
    }

    // If granting write on a page that isn't in allowed_pages, add it to allowed_pages too.
    const patch: {
      write_pages: string[];
      allowed_pages?: string[] | null;
    } = { write_pages: nextWrite };
    if (
      member.allowed_pages !== null &&
      nextWrite.includes(page) &&
      !member.allowed_pages.includes(page)
    ) {
      patch.allowed_pages = [...member.allowed_pages, page];
    }

    try {
      await updateProjectMember(projectId, member.id, patch);
      await loadMembers();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to update member");
    }
  }

  function isMemberPageChecked(member: ProjectMember, page: string): boolean {
    if (member.allowed_pages === null) return true;
    return member.allowed_pages.includes(page);
  }

  function isMemberWriteChecked(member: ProjectMember, page: string): boolean {
    // Admins bypass write checks entirely.
    if (member.role === "admin") return true;
    if (member.write_pages === null) {
      // Legacy: write implicitly granted on all allowed pages
      return isMemberPageChecked(member, page);
    }
    return member.write_pages.includes(page);
  }

  async function handleRoleChange(member: ProjectMember, role: string) {
    if (!projectId) return;
    try {
      await updateProjectMember(projectId, member.id, { role });
      await loadMembers();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to update role");
    }
  }

  async function handleRemove(member: ProjectMember) {
    if (!projectId) return;
    const label = member.status === "pending" ? "Cancel invitation for" : "Remove";
    if (!confirm(`${label} ${member.email}?`)) return;
    try {
      await removeProjectMember(projectId, member.id);
      await loadMembers();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to remove member");
    }
  }

  function toggleExpanded(memberId: string) {
    setExpandedMembers((prev) => {
      const next = new Set(prev);
      if (next.has(memberId)) next.delete(memberId);
      else next.add(memberId);
      return next;
    });
  }

  if (!projectId) {
    return <p className="text-gray-500 dark:text-slate-400">Select a project first.</p>;
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {/* Invite form */}
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

      {/* Members list */}
      <div className="rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-slate-800">
          <h3 className="text-lg font-semibold">Members</h3>
        </div>
        {loading ? (
          <div className="px-6 py-8 text-center text-gray-500 dark:text-slate-400 text-sm">Loading...</div>
        ) : members.length === 0 ? (
          <div className="px-6 py-8 text-center text-gray-500 dark:text-slate-400 text-sm">
            No members yet. Invite someone above.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
                <th className="px-6 py-3 font-medium">Email</th>
                <th className="px-6 py-3 font-medium">Status</th>
                <th className="px-6 py-3 font-medium">Role</th>
                {ALL_SECTIONS.map((s) => (
                  <th key={s} className="px-4 py-3 font-medium capitalize text-center">{s}</th>
                ))}
                <th className="px-6 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {members.map((member) => {
                const isExpanded = expandedMembers.has(member.id);
                const hasPageRestrictions = member.allowed_pages !== null;
                const hasWriteRestrictions =
                  member.role !== "admin" && member.write_pages !== null;
                return (
                  <tr
                    key={member.id}
                    className="border-b border-gray-100 dark:border-slate-800/50 last:border-0 align-top"
                  >
                    <td className="px-6 py-3 text-gray-900 dark:text-white">
                      <div>{member.email}</div>
                      <button
                        onClick={() => toggleExpanded(member.id)}
                        className="text-[11px] text-indigo-600 dark:text-indigo-400 hover:underline mt-0.5"
                      >
                        {isExpanded
                          ? "Hide pages"
                          : hasPageRestrictions || hasWriteRestrictions
                            ? "Edit pages (restricted)"
                            : "Edit pages"}
                      </button>
                    </td>
                    <td className="px-6 py-3">
                      {member.status === "pending" ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400">
                          Pending
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">
                          Active
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-3">
                      <select
                        value={member.role}
                        onChange={(e) => handleRoleChange(member, e.target.value)}
                        className="px-2 py-1 rounded border border-gray-300 dark:border-slate-700 bg-gray-50 dark:bg-slate-800 text-gray-900 dark:text-white text-xs"
                      >
                        <option value="member">Member</option>
                        <option value="admin">Admin</option>
                      </select>
                    </td>
                    {ALL_SECTIONS.map((section) => (
                      <td key={section} className="px-4 py-3 text-center">
                        <input
                          type="checkbox"
                          checked={member.allowed_sections.includes(section)}
                          onChange={() => handleToggleSection(member, section)}
                          className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
                        />
                        {isExpanded && member.allowed_sections.includes(section) && (
                          <div className="mt-1.5 space-y-1 text-left">
                            {(SECTION_PAGES[section] || []).map((page) => {
                              const readable = isMemberPageChecked(member, page);
                              return (
                                <div key={page} className="flex items-center gap-2 text-[11px]">
                                  <label className="flex items-center gap-1 min-w-[90px]">
                                    <input
                                      type="checkbox"
                                      checked={readable}
                                      onChange={() => handleTogglePage(member, page)}
                                      className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500 h-3 w-3"
                                    />
                                    <span className="capitalize text-gray-500 dark:text-slate-400">{page}</span>
                                  </label>
                                  <label className="flex items-center gap-1 text-gray-400 dark:text-slate-500">
                                    <input
                                      type="checkbox"
                                      checked={isMemberWriteChecked(member, page)}
                                      disabled={member.role === "admin" || (!readable && !isMemberWriteChecked(member, page))}
                                      onChange={() => handleToggleMemberWrite(member, page)}
                                      className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500 h-3 w-3 disabled:opacity-40"
                                    />
                                    <span>W</span>
                                  </label>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </td>
                    ))}
                    <td className="px-6 py-3 text-right">
                      <button
                        onClick={() => handleRemove(member)}
                        className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 text-xs font-medium"
                      >
                        {member.status === "pending" ? "Cancel" : "Remove"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
