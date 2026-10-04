// Pairing credentials belong only in volatile connection state, never route history.
// ConnectionProvider receives the raw initial URL and warm Linking events.
export function redirectSystemPath({
  path,
}: {
  path: string;
  initial: boolean;
}) {
  return path.toLowerCase().startsWith("stridecoach:") ? "/settings" : path;
}
