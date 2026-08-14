import { useQuery } from "@tanstack/react-query";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => fetch("/api/me").then((r) => r.json()),
  });
}

export function MePage() {
  const { data } = useMe();
  return <div>{data?.email}</div>;
}
