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
  const [inviting, setInviting] = useState(false);

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

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!projectId || !email.trim()) return;
    setInviting(true);
    setError(null);
    setLastInvite(null);
    try {
      const result = await inviteProjectMember(projectId, {
        email: email.trim(),
        role: inviteRole,
        allowed_sections: inviteSections,
      });
      if (result.status === "pending") {
        setLastInvite(result);
      }
      setEmail("");
      setInviteRole("member");
      setInviteSections([...ALL_SECTIONS]);
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
                  onChange={() =>
                    setInviteSections((prev) =>
                      prev.includes(section) ? prev.filter((s) => s !== section) : [...prev, section],
                    )
                  }
                  className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
                />
                <span className="capitalize text-gray-700 dark:text-slate-300">{section}</span>
              </label>
            ))}
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
              {members.map((member) => (
                <tr
                  key={member.id}
                  className="border-b border-gray-100 dark:border-slate-800/50 last:border-0"
                >
                  <td className="px-6 py-3 text-gray-900 dark:text-white">{member.email}</td>
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
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
