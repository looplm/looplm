"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  createUserGroup,
  createUserIdentity,
  deleteUserGroup,
  deleteUserIdentity,
  updateUserGroup,
  updateUserIdentity,
  type CreateUserGroupBody,
  type UpdateUserGroupBody,
  type UpdateUserIdentityBody,
} from "@/lib/api";
import { usePermissions } from "@/components/permissions-context";
import { useUserDirectory } from "@/components/user-directory-context";
import UserIdentitiesTable from "./user-identities-table";
import UserIdSuggestions from "./user-id-suggestions";
import UserGroupsTable from "./user-groups-table";

/**
 * Settings → Users: give raw end-user ids readable names and collect them into groups the
 * Observe filter bar can include or exclude.
 *
 * Data comes from the shared user-directory context rather than a local fetch, so a rename here
 * updates the traces table and the filter bar without a page reload.
 */
export default function UsersSettings() {
  const { identities, groups, traceUsers, ready, reload } = useUserDirectory();
  const { canWrite } = usePermissions();
  const editable = canWrite("traces");
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>, successMessage: string) {
    try {
      await action();
      await reload();
      setError(null);
      toast.success(successMessage);
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : "Something went wrong";
      setError(message);
      toast.error(message);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">Users</h3>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
          Name the user IDs your app sends with each trace, merge the IDs that belong to the same
          person, and group them so the Observe views can include or exclude whole groups.
        </p>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {!editable && (
        <div className="rounded-lg bg-gray-50 dark:bg-slate-800/60 border border-gray-200 dark:border-slate-700 px-4 py-3 text-sm text-gray-600 dark:text-slate-300">
          You have read-only access to this project&apos;s traces, so the directory cannot be edited
          here.
        </div>
      )}

      <UserIdentitiesTable
        identities={identities}
        traceUsers={traceUsers}
        loading={!ready}
        editable={editable}
        onRename={(id: string, body: UpdateUserIdentityBody) =>
          run(() => updateUserIdentity(id, body), "Identity updated")
        }
        onDelete={(id: string, name: string) => {
          if (!confirm(`Delete "${name}"? Its user IDs go back to being unnamed.`)) return;
          run(() => deleteUserIdentity(id), "Identity deleted");
        }}
      />

      <UserIdSuggestions
        identities={identities}
        traceUsers={traceUsers}
        loading={!ready}
        editable={editable}
        onCreate={(name: string, userIds: string[]) =>
          run(() => createUserIdentity({ name, user_ids: userIds }), `Named "${name}"`)
        }
        onMerge={(identityId: string, userIds: string[]) =>
          run(() => updateUserIdentity(identityId, { user_ids: userIds }), "User ID merged")
        }
      />

      <UserGroupsTable
        groups={groups}
        identities={identities}
        traceUsers={traceUsers}
        loading={!ready}
        editable={editable}
        onCreate={(body: CreateUserGroupBody) =>
          run(() => createUserGroup(body), `Created "${body.name}"`)
        }
        onUpdate={(id: string, body: UpdateUserGroupBody) =>
          run(() => updateUserGroup(id, body), "Group updated")
        }
        onDelete={(id: string, name: string) => {
          if (!confirm(`Delete the group "${name}"? The identities in it are kept.`)) return;
          run(() => deleteUserGroup(id), "Group deleted");
        }}
      />
    </div>
  );
}
