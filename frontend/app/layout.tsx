import './style.css'

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <header className="siteHeader">
          <div className="siteHeaderInner">
            <a className="siteBrand" href="/">
              <span>このAV</span>なんだっけ？
            </a>
            <nav className="siteNav" aria-label="メインナビゲーション"></nav>
          </div>
        </header>

        <div className="siteContent">{children}</div>

        <footer className="siteFooter">
          <div className="siteFooterInner">
            <div className="footerIdentity">
              <span>AV AI SEARCH</span>
              <small>作品を、自然な言葉で探す。</small>
            </div>
            <a className="adminEntry" href="/admin">
              管理者ログイン
              <span aria-hidden="true">→</span>
            </a>
          </div>
        </footer>
      </body>
    </html>
  )
}
