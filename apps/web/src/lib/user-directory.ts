/**
 * Pure helpers for the user directory: turning raw `user_id` strings into display names,
 * and turning a filter-bar selection of groups/identities into the raw ids the API expects.
 *
 * No React here on purpose — `components/user-directory-context.tsx` owns the fetching, and
 * these functions stay independently testable.
 */

import type {
  ResolvedUserName,
  TraceUser,
  UserGroup,
  UserIdentity,
  UserSelection,
} from "./api-types";

export const EMPTY_USER_SELECTION: UserSelection = { userIds: [], identityIds: [], groupIds: [] };

/**
 * Build the raw-id → display-name index.
 *
 * Precedence: a stored identity name wins, else the `username` the app put in trace metadata,
 * else the raw id itself. Only the identity case counts as `mapped`, since that is the one the
 * user curated; the metadata username is still just data from the traces.
 */
export function buildDisplayNameIndex(
  identities: UserIdentity[],
  traceUsers: TraceUser[],
): Map<string, ResolvedUserName> {
  const index = new Map<string, ResolvedUserName>();
  for (const user of traceUsers) {
    if (user.username) {
      index.set(user.user_id, { label: user.username, mapped: false });
    }
  }
  for (const identity of identities) {
    for (const userId of identity.user_ids ?? []) {
      index.set(userId, { label: identity.name, mapped: true, identityId: String(identity.id) });
    }
  }
  return index;
}

/** Resolve one raw id against an index built by {@link buildDisplayNameIndex}. */
export function resolveUserName(
  userId: string | null | undefined,
  index: Map<string, ResolvedUserName>,
): ResolvedUserName | null {
  if (!userId) return null;
  return index.get(userId) ?? { label: userId, mapped: false };
}

/**
 * Expand a filter selection into the raw user ids the Observe endpoints filter on.
 *
 * Group and identity ids that no longer exist contribute nothing, so a shared link whose group
 * was deleted degrades to the rest of the selection instead of filtering on a dangling id.
 */
export function expandSelection(
  selection: UserSelection,
  identities: UserIdentity[],
  groups: UserGroup[],
): string[] {
  const byIdentityId = new Map(identities.map((i) => [String(i.id), i]));
  const out = new Set<string>(selection.userIds);

  const addIdentity = (identityId: string) => {
    for (const userId of byIdentityId.get(identityId)?.user_ids ?? []) out.add(userId);
  };

  for (const identityId of selection.identityIds) addIdentity(identityId);

  const byGroupId = new Map(groups.map((g) => [String(g.id), g]));
  for (const groupId of selection.groupIds) {
    const group = byGroupId.get(groupId);
    if (!group) continue;
    for (const userId of group.user_ids ?? []) out.add(userId);
    for (const identityId of group.identity_ids ?? []) addIdentity(String(identityId));
  }

  return [...out];
}

/** Drop selected group/identity ids that no longer resolve. Returns the same object when clean. */
export function pruneSelection(
  selection: UserSelection,
  identities: UserIdentity[],
  groups: UserGroup[],
): UserSelection {
  const identityIds = new Set(identities.map((i) => String(i.id)));
  const groupIds = new Set(groups.map((g) => String(g.id)));
  const keptIdentities = selection.identityIds.filter((id) => identityIds.has(id));
  const keptGroups = selection.groupIds.filter((id) => groupIds.has(id));
  if (
    keptIdentities.length === selection.identityIds.length &&
    keptGroups.length === selection.groupIds.length
  ) {
    return selection;
  }
  return { ...selection, identityIds: keptIdentities, groupIds: keptGroups };
}

/** Raw ids that already belong to an identity, so pickers can flag them as claimed. */
export function claimedUserIds(identities: UserIdentity[]): Set<string> {
  const claimed = new Set<string>();
  for (const identity of identities) {
    for (const userId of identity.user_ids ?? []) claimed.add(userId);
  }
  return claimed;
}
