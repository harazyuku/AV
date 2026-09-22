'use client'
import { useEffect, useState } from 'react'

import PublicVideoCard from './components/PublicVideoCard'
import QuizFinder from './components/QuizFinder'

const API = process.env.NEXT_PUBLIC_API_URL || '/api'
type VideoProduct = {
  id: number
  external_id: string
  source: {
    title: string
    description: string
    source_id: string | null
  }
  visual_analysis: {
    keywords: string[]
  }
  media: {
    thumbnail_url: string | null
    thumbnail_small_url: string | null
    provider: string
  }
}
type SearchSuggestion = {
  type: string
  value: string
  count: number
}

export default function Home() {
  const [query, setQuery] = useState('')
  const [selectedTags, setSelectedTags] = useState<SearchSuggestion[]>([])
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([])
  const [items, setItems] = useState<VideoProduct[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [popular, setPopular] = useState<VideoProduct[]>([])
  const [recommended, setRecommended] = useState<VideoProduct[]>([])
  useEffect(() => {
    fetch(API + '/products/popular?limit=12', { cache: 'no-store' })
      .then((response) => (response.ok ? response.json() : { items: [] }))
      .then((data) => setPopular(data.items || []))
      .catch(() => setPopular([]))
    fetch(API + '/products/recommended?limit=12', { cache: 'no-store' })
      .then((response) => (response.ok ? response.json() : { items: [] }))
      .then((data) => setRecommended(data.items || []))
      .catch(() => setRecommended([]))
  }, [])
  useEffect(() => {
    const value = query.trim()
    if (!value) {
      setSuggestions([])
      return
    }
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      fetch(
        `${API}/search/suggestions?q=${encodeURIComponent(value)}&limit=12`,
        {
          cache: 'no-store',
          signal: controller.signal,
        },
      )
        .then((response) => (response.ok ? response.json() : { items: [] }))
        .then((data) => setSuggestions(data.items || []))
        .catch((reason) => {
          if (reason instanceof Error && reason.name !== 'AbortError') {
            setSuggestions([])
          }
        })
    }, 120)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [query])

  function selectSuggestion(suggestion: SearchSuggestion) {
    setSelectedTags((current) =>
      current.some((tag) => tag.value === suggestion.value)
        ? current
        : [...current, suggestion],
    )
    setQuery('')
    setSuggestions([])
  }

  function removeTag(value: string) {
    setSelectedTags((current) => current.filter((tag) => tag.value !== value))
  }

  async function search() {
    setLoading(true)
    setMessage('')
    try {
      const r = await fetch(API + '/search', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          query: query.trim(),
          selected_tags: selectedTags.map((tag) => ({
            type: tag.type,
            value: tag.value,
          })),
        }),
      })
      const d = await r.json()
      setItems(d.results || [])
    } catch {
      setMessage(
        'APIに接続できません。バックエンドが起動しているか確認してね。',
      )
    } finally {
      setLoading(false)
    }
  }
  return (
    <main>
      <header className="homeHero">
        <div className="heroCopy">
          <h1>
            <em>このAV</em>なんだっけ？
          </h1>
          <div className="search">
            <div className="searchComposer">
              {selectedTags.map((tag) => (
                <span className="searchToken" key={tag.value}>
                  {tag.type !== 'FANZAジャンル' && <small>{tag.type}</small>}
                  {tag.value}
                  <button
                    type="button"
                    aria-label={`${tag.value}を削除`}
                    onClick={() => removeTag(tag.value)}
                  >
                    ×
                  </button>
                </span>
              ))}
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void search()
                  if (e.key === 'Escape') setSuggestions([])
                }}
                placeholder={
                  selectedTags.length > 0
                    ? '条件を追加…'
                    : 'ジャンル・タグ・女優名・品番など'
                }
                aria-label="作品の検索条件"
                autoComplete="off"
              />
            </div>
            <button className="searchSubmit" onClick={search}>
              {loading ? '検索中…' : '検索する'}
            </button>
            {suggestions.length > 0 && (
              <div className="searchSuggestions" role="listbox">
                {suggestions.map((suggestion) => (
                  <button
                    type="button"
                    role="option"
                    aria-selected="false"
                    className={
                      suggestion.type === 'FANZAジャンル'
                        ? 'genreSuggestion'
                        : undefined
                    }
                    key={`${suggestion.type}-${suggestion.value}`}
                    onClick={() => selectSuggestion(suggestion)}
                  >
                    {suggestion.type !== 'FANZAジャンル' && (
                      <small>{suggestion.type}</small>
                    )}
                    <span>{suggestion.value}</span>
                    <b>{suggestion.count}</b>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </header>
      <QuizFinder />
      {message && <div className="notice searchNotice">{message}</div>}
      {items.length > 0 && (
        <section className="recommendations searchResults">
          <div className="recommendationHeading">
            <div>
              <small>SEARCH RESULT</small>
              <h2>検索した作品</h2>
            </div>
            <span className="resultCount">{items.length}件</span>
          </div>
          <div className="recommendationGrid twoRowVideoGrid">
            {items.slice(0, 12).map((item) => (
              <PublicVideoCard
                externalId={item.external_id}
                key={item.id}
                title={item.source.title}
                thumbnailUrl={
                  item.media?.thumbnail_small_url || item.media?.thumbnail_url
                }
              />
            ))}
          </div>
        </section>
      )}
      {popular.length > 0 && (
        <section className="recommendations popularVideos">
          <div className="recommendationHeading">
            <div>
              <small>POPULAR</small>
              <h2>よく検索される動画</h2>
            </div>
          </div>
          <div className="recommendationGrid twoRowVideoGrid">
            {popular.map((item) => (
              <PublicVideoCard
                externalId={item.external_id}
                key={item.id}
                title={item.source.title}
                thumbnailUrl={
                  item.media?.thumbnail_small_url || item.media?.thumbnail_url
                }
              />
            ))}
          </div>
        </section>
      )}
      {recommended.length > 0 && (
        <section className="recommendations">
          <div className="recommendationHeading">
            <div>
              <h2>おすすめ動画</h2>
            </div>
          </div>
          <div className="recommendationGrid twoRowVideoGrid">
            {recommended.map((item) => (
              <PublicVideoCard
                externalId={item.external_id}
                key={item.id}
                title={item.source.title}
                thumbnailUrl={
                  item.media?.thumbnail_small_url || item.media?.thumbnail_url
                }
              />
            ))}
          </div>
        </section>
      )}
    </main>
  )
}
