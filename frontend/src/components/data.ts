'use client';
import { useQuery } from '@tanstack/react-query';
import { api, queryPath } from '@/lib/api';
import type { Page } from '@/lib/types';
export function useList<T>(path: string, params: Record<string, string | number | undefined> = {}) {
  const url = queryPath(path, params);
  return useQuery({ queryKey: ['list', url], queryFn: ({ signal }) => api<Page<T>>(url, { signal }) });
}
export function useRecord<T>(path: string) { return useQuery({ queryKey: ['record', path], queryFn: ({ signal }) => api<T>(path, { signal }) }); }
