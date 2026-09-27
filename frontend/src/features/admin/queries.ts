import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ApiError } from "@shared/types";
import {
  createUser,
  fetchUsers,
  resetUserPassword,
  updateUser,
} from "@shared/api/adminUsers";
import type { NewUserInput, UserPatch } from "@shared/api/adminUsers";
import { ApiRequestError } from "@shared/api/client";
import { responseShapeError } from "@shared/api/errors";

/** Not a prefix any other feature uses, and never reached by SSE invalidation. */
export const ADMIN_USERS_QUERY_KEY = ["admin", "users"] as const;

export function useUsersQuery() {
  return useQuery({
    queryKey: ADMIN_USERS_QUERY_KEY,
    queryFn: ({ signal }) => fetchUsers(signal),
  });
}

export function errorOf(error: unknown): ApiError {
  return error instanceof ApiRequestError ? error.apiError : responseShapeError();
}

export function useCreateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: NewUserInput) => createUser(input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ADMIN_USERS_QUERY_KEY }),
  });
}

export function useUpdateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: { readonly userId: string; readonly patch: UserPatch }) =>
      updateUser(variables.userId, variables.patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ADMIN_USERS_QUERY_KEY }),
  });
}

export function useResetPassword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: { readonly userId: string; readonly password: string }) =>
      resetUserPassword(variables.userId, variables.password),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ADMIN_USERS_QUERY_KEY }),
  });
}
