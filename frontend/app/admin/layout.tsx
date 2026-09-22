import type { Metadata } from 'next'

export const metadata: Metadata = {
  robots: {
    index: false,
    follow: false,
    noarchive: true,
  },
}

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="adminShell">
      <nav className="adminNav" aria-label="管理メニュー">
        <a href="/admin/imports">取込状況</a>
        <a href="/admin/videos">読み込んだ動画</a>
        <a href="/admin/manual-import">指定取り込み</a>
      </nav>
      {children}
    </div>
  )
}
