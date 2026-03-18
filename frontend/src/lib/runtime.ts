const configuredBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();

function normalizeBase(base: string): string {
  return base.endsWith("/") ? base.slice(0, -1) : base;
}

export function getApiBaseUrl(): string {
  if (configuredBase) {
    return normalizeBase(configuredBase);
  }
  return window.location.origin;
}

export function getApiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${getApiBaseUrl()}${normalizedPath}`;
}

export function getWebSocketUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const httpBase = getApiBaseUrl();
  const wsBase = httpBase.startsWith("https://")
    ? httpBase.replace("https://", "wss://")
    : httpBase.replace("http://", "ws://");
  return `${wsBase}${normalizedPath}`;
}
