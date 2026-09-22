'use client'

import Link from 'next/link'
import { productPath } from '../../shared/api'

type PublicVideoCardProps = {
  externalId: string
  title: string
  thumbnailUrl?: string | null
}

export default function PublicVideoCard({
  externalId,
  title,
  thumbnailUrl,
}: PublicVideoCardProps) {
  return (
    <Link className="publicVideoCard" href={productPath(externalId)}>
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
