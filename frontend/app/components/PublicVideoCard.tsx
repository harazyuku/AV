'use client'

import Link from 'next/link'
import { apiAssetUrl, productPath } from '../../shared/api'

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
  const imageUrl = apiAssetUrl(thumbnailUrl)

  return (
    <Link className="publicVideoCard" href={productPath(externalId)}>
      <div className="publicVideoThumbnail">
        {imageUrl ? (
          <img
            src={imageUrl}
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
