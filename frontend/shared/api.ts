/** Browser-side API entry point shared by PC and SP screens. */
export const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api'

export function productPath(externalId: string): string {
  return `/videos/${encodeURIComponent(externalId.replace(/^missav-/, ''))}`
}
