import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "~/api/client";
import type { AttachmentUpdate, DetectedType } from "~/api/types";
import { queryKeys } from "~/lib/query";

interface UseAttachmentsOptions {
  detectedType?: DetectedType;
  limit?: number;
  offset?: number;
}

export function useAttachmentsByResource(
  resourceId: string | undefined,
  options?: UseAttachmentsOptions,
) {
  const query = useQuery({
    queryKey: [...queryKeys.attachments.byResource(resourceId ?? ""), options],
    queryFn: () => api.attachments.listByResource(resourceId!, options),
    enabled: !!resourceId,
  });

  return {
    attachments: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error ?? null,
    isFetching: query.isFetching,
    refetch: query.refetch,
  };
}

export function useAttachmentsByGame(gameId: string | undefined, options?: UseAttachmentsOptions) {
  const query = useQuery({
    queryKey: [...queryKeys.attachments.byGame(gameId ?? ""), options],
    queryFn: () => api.attachments.listByGame(gameId!, options),
    enabled: !!gameId,
  });

  return {
    attachments: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error ?? null,
    isFetching: query.isFetching,
    refetch: query.refetch,
  };
}

export function useAttachment(id: string | undefined) {
  const query = useQuery({
    queryKey: queryKeys.attachments.detail(id ?? ""),
    queryFn: () => api.attachments.get(id!),
    enabled: !!id,
  });

  return {
    attachment: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error ?? null,
    isFetching: query.isFetching,
    refetch: query.refetch,
  };
}

export function useUpdateAttachment() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: AttachmentUpdate }) =>
      api.attachments.update(id, data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.attachments.all });
      queryClient.setQueryData(queryKeys.attachments.detail(data.id), data);
    },
  });
}

export function useReprocessAttachment() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => api.attachments.reprocess(id),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.attachments.all });
      queryClient.setQueryData(
        queryKeys.attachments.detail(result.attachment.id),
        result.attachment,
      );
    },
  });
}
