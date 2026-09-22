'use client'

import Link from 'next/link'

type PublicVideoCardProps = {
  id: number
  title: string
  thumbnailUrl?: string | null
}

export default function PublicVideoCard({
  id,
  title,
  thumbnailUrl,
}: PublicVideoCardProps) {
  return (
    <Link className="publicVideoCard" href={`/videos/${id}`}>
      <div className="publicVideoThumbnail">
        {thumbnailUrl ? (
          <img
            src={thumbnailUrl}
            alt={`${title}のサムネイル`}
            loading="lazy"
            decoding="async"
            width="147"
            height="200"
            referrerPolicy="no-referrer"
            onError={(event) => {
              event.currentTarget.hidden = true
            }}
          />
        ) : (
          <span>NO IMAGE</span>
        )}
      </div>
      <h3 title={title}>{title}</h3>
    </Link>
  )
}
