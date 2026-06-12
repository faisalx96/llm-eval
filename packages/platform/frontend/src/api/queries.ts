import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '@/api/client'
import type { CreateProjectRequest, Me, Project, ProjectsResponse } from '@/api/types'

/**
 * Query hooks for the /v1 endpoints the shell consumes.
 *
 * QueryClient defaults (staleTime 30s, retry 1, refetchOnWindowFocus false)
 * are configured where the client is constructed in src/main.tsx.
 */

export const queryKeys = {
  me: ['me'] as const,
  projects: ['projects'] as const,
}

export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => apiFetch<Me>('/v1/me'),
  })
}

export function useProjects() {
  return useQuery({
    queryKey: queryKeys.projects,
    queryFn: () => apiFetch<ProjectsResponse>('/v1/projects'),
    select: (data) => data.projects,
  })
}

export function useCreateProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateProjectRequest) =>
      apiFetch<Project>('/v1/projects', { method: 'POST', body }),
    onSuccess: () => {
      // /v1/me embeds the project list too — refresh both.
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects })
      void queryClient.invalidateQueries({ queryKey: queryKeys.me })
    },
  })
}
