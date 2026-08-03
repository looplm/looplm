"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  getTraceUsers,
  getUserGroups,
  getUserIdentities,
  type TraceUser,
  type UserGroup,
  type UserIdentity,
  type UserSelection,
} from "@/lib/api";
import {
  buildDisplayNameIndex,
  expandSelection,
  resolveUserName,
} from "@/lib/user-directory";

interface UserDirectoryContextValue {
  identities: UserIdentity[];
  groups: UserGroup[];
  /** Every raw user id seen in the project's traces, with its metadata username. */
  traceUsers: TraceUser[];
  /** False until the first load settles — consumers should not filter on a half-built directory. */
  ready: boolean;
  /** Identity name > metadata username > raw id. Empty string for a missing id. */
  displayName: (userId: string | null | undefined) => string;
  /** True when a stored identity supplied the name (raw ids stay monospaced). */
  isNamed: (userId: string | null | undefined) => boolean;
  /** Expand a group/identity/user selection into the raw ids the API filters on. */
  expand: (selection: UserSelection) => string[];
  reload: () => Promise<void>;
}

const UserDirectoryContext = createContext<UserDirectoryContextValue | null>(null);

export function useUserDirectory(): UserDirectoryContextValue {
  const ctx = useContext(UserDirectoryContext);
  if (!ctx) throw new Error("useUserDirectory must be used within UserDirectoryProvider");
  return ctx;
}

export function UserDirectoryProvider({ children }: { children: ReactNode }) {
  const [identities, setIdentities] = useState<UserIdentity[]>([]);
  const [groups, setGroups] = useState<UserGroup[]>([]);
  const [traceUsers, setTraceUsers] = useState<TraceUser[]>([]);
  const [ready, setReady] = useState(false);

  const load = useCallback(async () => {
    // Settled, not all-or-nothing: a project with no traces yet should still show its directory,
    // and a directory error should not blank out the user ids in the traces table.
    const [identityResult, groupResult, userResult] = await Promise.allSettled([
      getUserIdentities(),
      getUserGroups(),
      getTraceUsers(),
    ]);
    if (identityResult.status === "fulfilled") setIdentities(identityResult.value.data);
    if (groupResult.status === "fulfilled") setGroups(groupResult.value.data);
    if (userResult.status === "fulfilled") setTraceUsers(userResult.value);
    setReady(true);
  }, []);

  useEffect(() => {
    let cancelled = false;
    load().catch(() => {
      if (!cancelled) setReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  const nameIndex = useMemo(
    () => buildDisplayNameIndex(identities, traceUsers),
    [identities, traceUsers],
  );

  const value = useMemo<UserDirectoryContextValue>(
    () => ({
      identities,
      groups,
      traceUsers,
      ready,
      displayName: (userId) => resolveUserName(userId, nameIndex)?.label ?? "",
      isNamed: (userId) => resolveUserName(userId, nameIndex)?.mapped ?? false,
      expand: (selection) => expandSelection(selection, identities, groups),
      reload: load,
    }),
    [identities, groups, traceUsers, ready, nameIndex, load],
  );

  return <UserDirectoryContext.Provider value={value}>{children}</UserDirectoryContext.Provider>;
}
