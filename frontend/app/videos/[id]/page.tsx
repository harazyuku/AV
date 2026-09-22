'use client'

import { useEffect, useState } from 'react'

const API = process.env.NEXT_PUBLIC_API_URL || '/api'

type VideoDetail = {
  id: number
  source: {
    title: string
    description: string
    metadata: {
      maker?: string
      label?: string
      director?: string
      genres?: string[]
      product_code?: string
      release_date?: string
    }
  }
  visual_analysis: {
    summary: string
    keywords: string[]
  }
  media: {
    thumbnail_url: string | null
    provider: string
  }
}

export default function VideoDetailPage({
  params,
}: {
  params: { id: string }
}) {
  const [item, setItem] = useState<VideoDetail | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch(`${API}/products/by-external/${encodeURIComponent(params.id)}/json`, { cache: 'no-store' })
      .then(async (response) => {
        if (!response.ok) throw new Error('動画情報を取得できませんでした')
        return response.json()
      })
      .then((data) => {
        setItem(data)
        const viewKey = `viewed-video-${params.id}`
        if (!sessionStorage.getItem(viewKey)) {
          sessionStorage.setItem(viewKey, 'true')
          void fetch(`${API}/products/by-external/${encodeURIComponent(params.id)}/view`, { method: 'POST' })
        }
      })
      .catch((reason) =>
        setError(
          reason instanceof Error ? reason.message : '取得に失敗しました',
        ),
      )
  }, [params.id])

  if (error) {
    return <main className="videoDetailPage">{error}</main>
  }

  if (!item) {
    return <main className="videoDetailPage">読み込み中…</main>
  }

  const metadata = item.source.metadata || {}
  const tags = metadata.genres || item.visual_analysis.keywords || []

  return (
    <main className="videoDetailPage">
      <article className="videoDetail">
        <div className="videoDetailImage">
          {item.media.thumbnail_url ? (
            <img
              src={item.media.thumbnail_url}
              alt={`${item.source.title}の作品画像`}
              referrerPolicy="no-referrer"
            />
          ) : (
            <span>NO IMAGE</span>
          )}
        </div>
        <div className="videoDetailBody">
          <small>{metadata.product_code || `VIDEO ${item.id}`}</small>
          <h1>{item.source.title}</h1>
          <p>{item.source.description || item.visual_analysis.summary}</p>
          <dl>
            {metadata.maker && (
              <>
                <dt>メーカー</dt>
                <dd>{metadata.maker}</dd>
              </>
            )}
            {metadata.label && (
              <>
                <dt>レーベル</dt>
                <dd>{metadata.label}</dd>
              </>
            )}
            {metadata.release_date && (
              <>
                <dt>発売日</dt>
                <dd>{metadata.release_date}</dd>
              </>
            )}
          </dl>
          <div className="tags">
            {tags.slice(0, 8).map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </div>
        </div>
      </article>
    </main>
  )
}
