'use client'

import { useState } from 'react'

const API = process.env.NEXT_PUBLIC_API_URL || '/api'

export default function ManualImportPage() {
  const [importUrl, setImportUrl] = useState('')
  const [importing, setImporting] = useState(false)
  const [message, setMessage] = useState('')

  async function seed() {
    await fetch(API + '/admin/products/seed', {
      method: 'POST',
      credentials: 'include',
    })
    setMessage('サンプル作品を登録したよ。検索してみて。')
  }

  async function importVideo() {
    if (!importUrl) return

    setImporting(true)
    setMessage('取得を開始しているよ…')

    try {
      const response = await fetch(API + '/admin/imports/missav', {
        method: 'POST',
        credentials: 'include',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ url: importUrl, analyze: true }),
      })
      const job = await response.json()

      if (!response.ok) {
        throw new Error(job.detail || '開始できませんでした')
      }

      setMessage(`取得中：ジョブ ${job.id}`)

      const timer = setInterval(async () => {
        const status = await fetch(API + '/admin/imports/' + job.id, {
          credentials: 'include',
        }).then((result) => result.json())

        if (status.status === 'splitting') {
          setMessage('動画から代表シーンを抽出中…')
        } else if (status.status === 'json_building') {
          setMessage('AIが検索用JSONを生成中…')
        } else if (status.status === 'completed') {
          clearInterval(timer)
          setImporting(false)
          setMessage(
            `解析・DB登録完了：${status.title}（作品ID ${status.product_id}）`,
          )
        } else if (status.status === 'failed') {
          clearInterval(timer)
          setImporting(false)
          setMessage(`処理失敗：${status.error}`)
        }
      }, 2000)
    } catch (error) {
      setImporting(false)
      setMessage(error instanceof Error ? error.message : '取得に失敗しました')
    }
  }

  return (
    <main className="manualImportPage">
      <header className="manualImportHeader">
        <div className="eyebrow">MANUAL IMPORT</div>
        <h1>指定取り込み</h1>
        <p>公開作品URLを指定して、取得・AI解析・DB登録を実行します。</p>
      </header>

      <section className="manualImportContent">
        <div className="importer">
          <div>
            <b>取得・AI解析・DB登録</b>
            <small>公開作品URLを1件ずつ指定</small>
          </div>
          <input
            value={importUrl}
            onChange={(event) => setImportUrl(event.target.value)}
            placeholder="https://missav..."
          />
          <button disabled={importing} onClick={importVideo}>
            {importing ? '処理中…' : '取り込む'}
          </button>
        </div>

        {message && <div className="notice">{message}</div>}

        <div className="empty">
          <div>✦</div>
          <h2>まずは作品データを登録しよう</h2>
          <p>開発用のサンプル作品を登録して、検索の動きを確認できます。</p>
          <button onClick={seed}>サンプルを登録</button>
        </div>
      </section>
    </main>
  )
}
