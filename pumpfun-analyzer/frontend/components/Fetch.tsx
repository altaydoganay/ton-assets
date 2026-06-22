"use client";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Loading, Empty, ErrorState } from "./States";

export function Fetch<T>({
  path,
  children,
  isEmpty,
  refreshInterval,
  emptyLabel,
}: {
  path: string;
  children: (data: T) => React.ReactNode;
  isEmpty?: (data: T) => boolean;
  refreshInterval?: number;
  emptyLabel?: string;
}) {
  const { data, error, isLoading } = useSWR<T>(path, fetcher, { refreshInterval });
  if (isLoading) return <Loading />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (data === undefined) return <Empty label={emptyLabel} />;
  if (isEmpty && isEmpty(data)) return <Empty label={emptyLabel} />;
  return <>{children(data)}</>;
}
