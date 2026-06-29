"use client";

import { useState } from "react";
import { type ProjectMember } from "@/lib/api";
import { ALL_SECTIONS, SECTION_PAGES } from "./permission-constants";

export default function MembersTable({
  members,
  loading,
  isOwner,
  onToggleSection,
  onTogglePage,
  onToggleMemberWrite,
  onRoleChange,
  onTransfer,
  onRemove,
}: {
  members: ProjectMember[];
  loading: boolean;
  isOwner: boolean;
  onToggleSection: (member: ProjectMember, section: string) => void;
  onTogglePage: (member: ProjectMember, page: string) => void;
  onToggleMemberWrite: (member: ProjectMember, page: string) => void;
  onRoleChange: (member: ProjectMember, role: string) => void;
  onTransfer: (member: ProjectMember) => void;
  onRemove: (member: ProjectMember) => void;
}) {
  // Expanded rows for page-level editing
  const [expandedMembers, setExpandedMembers] = useState<Set<string>>(new Set());

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

  function toggleExpanded(memberId: string) {
    setExpandedMembers((prev) => {
      const next = new Set(prev);
      if (next.has(memberId)) next.delete(memberId);
      else next.add(memberId);
      return next;
    });
  }

  return (
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
              const isOwnerRow = member.role === "owner";
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
                    {!isOwnerRow && (
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
                    )}
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
                    {isOwnerRow ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400">
                        Owner
                      </span>
                    ) : (
                      <select
                        value={member.role}
                        onChange={(e) => onRoleChange(member, e.target.value)}
                        className="px-2 py-1 rounded border border-gray-300 dark:border-slate-700 bg-gray-50 dark:bg-slate-800 text-gray-900 dark:text-white text-xs"
                      >
                        <option value="member">Member</option>
                        <option value="admin">Admin</option>
                      </select>
                    )}
                  </td>
                  {ALL_SECTIONS.map((section) => (
                    <td key={section} className="px-4 py-3 text-center">
                      <input
                        type="checkbox"
                        checked={member.allowed_sections.includes(section)}
                        disabled={isOwnerRow}
                        onChange={() => onToggleSection(member, section)}
                        className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500 disabled:opacity-50"
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
                                    onChange={() => onTogglePage(member, page)}
                                    className="rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500 h-3 w-3"
                                  />
                                  <span className="capitalize text-gray-500 dark:text-slate-400">{page}</span>
                                </label>
                                <label className="flex items-center gap-1 text-gray-400 dark:text-slate-500">
                                  <input
                                    type="checkbox"
                                    checked={isMemberWriteChecked(member, page)}
                                    disabled={member.role === "admin" || (!readable && !isMemberWriteChecked(member, page))}
                                    onChange={() => onToggleMemberWrite(member, page)}
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
                  <td className="px-6 py-3 text-right whitespace-nowrap">
                    {isOwnerRow ? (
                      <span className="text-xs text-gray-400 dark:text-slate-500">—</span>
                    ) : (
                      <div className="inline-flex items-center gap-3">
                        {isOwner && member.status === "active" && member.user_id && (
                          <button
                            onClick={() => onTransfer(member)}
                            className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 text-xs font-medium"
                          >
                            Make owner
                          </button>
                        )}
                        <button
                          onClick={() => onRemove(member)}
                          className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 text-xs font-medium"
                        >
                          {member.status === "pending" ? "Cancel" : "Remove"}
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
