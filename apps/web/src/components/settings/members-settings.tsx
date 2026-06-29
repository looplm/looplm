"use client";

import { useEffect, useState } from "react";
import {
  getProjectMembers,
  updateProjectMember,
  removeProjectMember,
  transferProjectOwnership,
  type ProjectMember,
} from "@/lib/api";
import { usePermissions } from "@/components/permissions-context";
import { pagesForSections } from "./permission-constants";
import InviteMemberForm from "./invite-member-form";
import MembersTable from "./members-table";

export default function MembersSettings({ projectId }: { projectId: string | null }) {
  const { role: currentRole, refresh: refreshPermissions } = usePermissions();
  const isOwner = currentRole === "owner";
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  async function handleRoleChange(member: ProjectMember, role: string) {
    if (!projectId) return;
    try {
      await updateProjectMember(projectId, member.id, { role });
      await loadMembers();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to update role");
    }
  }

  async function handleTransfer(member: ProjectMember) {
    if (!projectId) return;
    if (
      !confirm(
        `Transfer ownership to ${member.email}?\n\nThey will become the project owner and you will become an admin. Only the new owner can transfer it back.`,
      )
    )
      return;
    try {
      await transferProjectOwnership(projectId, member.user_id!);
      await loadMembers();
      // Current user is no longer the owner — refresh cached permissions.
      refreshPermissions();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to transfer ownership");
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

      <InviteMemberForm projectId={projectId} onInvited={loadMembers} onError={setError} />

      <MembersTable
        members={members}
        loading={loading}
        isOwner={isOwner}
        onToggleSection={handleToggleSection}
        onTogglePage={handleTogglePage}
        onToggleMemberWrite={handleToggleMemberWrite}
        onRoleChange={handleRoleChange}
        onTransfer={handleTransfer}
        onRemove={handleRemove}
      />
    </div>
  );
}
