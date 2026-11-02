import type { QueryClient } from '@tanstack/react-query';

export async function clearSession(client: QueryClient) {
  // Finish cancelling requests before removing cached student data so late
  // responses cannot restore the signed-out user's workspace.
  await client.cancelQueries();
  client.removeQueries({ predicate: query => query.queryKey[0] !== 'session' });
  client.getMutationCache().clear();
  client.setQueryData(['session'], null);
}
