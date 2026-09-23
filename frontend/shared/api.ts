/** Browser-side API entry point shared by PC and SP screens. */
export const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api'

export function apiAssetUrl(path?: string | null): string | null {
  if (!path) return null
  if (/^https?:\/\//i.test(path)) return path

  const apiBase = API_BASE.replace(/\/$/, '')
  const assetPath = path.startsWith('/api/') ? path.slice(4) : path
  return `${apiBase}/${assetPath.replace(/^\//, '')}`
}

export function productPath(externalId: string): string {
  return `/videos/${encodeURIComponent(externalId.replace(/^missav-/, ''))}`
}
