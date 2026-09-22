'use client'

import { useEffect, useMemo, useState } from 'react'

import RandomGenerator from './RandomGenerator'

const API = process.env.NEXT_PUBLIC_API_URL || '/api'
const MIN_QUESTIONS = 5
const MAX_QUESTIONS = 30
const ANSWER_TRANSITION_MS = 450

type Performer = {
  name: string
  type: string
  hair_color: string
  hair_style: string
  glasses: boolean
}

type Product = {
  id: number
  title: string
  description: string
  release_date: string
  fanza_url: string
  performers: Performer[]
  attributes: Record<string, unknown>
}

type Candidate = {
  product: Product
  weight: number
}

type Question = {
  id: string
  text: string
  reliability?: number
  matches: (product: Product) => boolean | null
}

type Answer = 'yes' | 'likely-yes' | 'unknown' | 'likely-no' | 'no'

const ANSWERS: Array<{ answer: Answer; label: string }> = [
  { answer: 'yes', label: 'はい' },
  { answer: 'likely-yes', label: 'たぶんそう' },
  { answer: 'unknown', label: 'わからない' },
  { answer: 'likely-no', label: 'たぶん違う' },
  { answer: 'no', label: 'いいえ' },
]

function productText(product: Product) {
  return [
    product.title,
    product.description,
    JSON.stringify(product.attributes),
  ]
    .join(' ')
    .toLowerCase()
}

function includesAny(product: Product, words: string[]) {
  const text = productText(product)
  return words.some((word) => text.includes(word.toLowerCase()))
}

function performerMatches(
  product: Product,
  field: keyof Performer,
  values: Array<string | boolean>,
) {
  return (product.performers || []).some((performer) =>
    values.includes(performer[field]),
  )
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function stringValues(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .filter((item): item is string => typeof item === 'string')
      .map((item) => item.trim())
      .filter(Boolean)
  }
  if (typeof value === 'string' && value.trim()) return [value.trim()]
  return []
}

function unique(values: string[]) {
  return Array.from(new Set(values))
}

function normalized(value: string) {
  return value.trim().toLocaleLowerCase('ja-JP')
}

const MINOR_CODED_TERMS =
  /(ロリ|幼女|児童|未成年|小学生|中学生|高校生|女子高生|男子高生|(^|\W)jk(\W|$)|(^|\W)jc(\W|$)|(^|\W)js(\W|$))/i

function isAllowedQuestionValue(value: string) {
  return !MINOR_CODED_TERMS.test(value)
}

function productAttributes(product: Product) {
  return asRecord(product.attributes)
}

function visualAttributes(product: Product) {
  return asRecord(productAttributes(product).visual_analysis)
}

function sourceMetadata(product: Product) {
  return asRecord(productAttributes(product).source_metadata)
}

function analysisValues(
  product: Product,
  attributeKey: string,
  visualKey: string,
) {
  return unique([
    ...stringValues(productAttributes(product)[attributeKey]),
    ...stringValues(visualAttributes(product)[visualKey]),
  ])
}

type DynamicQuestionField = {
  key: string
  reliability: number
  limit: number
  values: (product: Product) => string[]
  question: (value: string) => string
}

const DYNAMIC_FIELDS: DynamicQuestionField[] = [
  {
    key: 'genre',
    reliability: 0.98,
    limit: 80,
    values: (product) => stringValues(sourceMetadata(product).genres),
    question: (value) => `ジャンルに「${value}」が含まれますか？`,
  },
  {
    key: 'clothing',
    reliability: 0.82,
    limit: 50,
    values: (product) => analysisValues(product, '衣装', 'clothing'),
    question: (value) => `「${value}」を着ていますか？`,
  },
  {
    key: 'location',
    reliability: 0.82,
    limit: 40,
    values: (product) => analysisValues(product, '場所', 'locations'),
    question: (value) => `「${value}」が主な舞台ですか？`,
  },
  {
    key: 'mood',
    reliability: 0.72,
    limit: 30,
    values: (product) => analysisValues(product, '雰囲気', 'mood'),
    question: (value) => `「${value}」雰囲気の作品ですか？`,
  },
  {
    key: 'keyword',
    reliability: 0.74,
    limit: 100,
    values: (product) => analysisValues(product, 'キーワード', 'keywords'),
    question: (value) => `「${value}」が特徴の作品ですか？`,
  },
  {
    key: 'maker',
    reliability: 0.98,
    limit: 30,
    values: (product) => stringValues(sourceMetadata(product).maker),
    question: (value) => `メーカーは「${value}」ですか？`,
  },
  {
    key: 'label',
    reliability: 0.98,
    limit: 30,
    values: (product) => stringValues(sourceMetadata(product).label),
    question: (value) => `レーベルは「${value}」ですか？`,
  },
  {
    key: 'performer-type',
    reliability: 0.78,
    limit: 30,
    values: (product) =>
      unique(
        (product.performers || []).map((item) => item.type).filter(Boolean),
      ),
    question: (value) => `登場人物は「${value}」タイプですか？`,
  },
  {
    key: 'hair-color',
    reliability: 0.76,
    limit: 20,
    values: (product) =>
      unique(
        (product.performers || [])
          .map((item) => item.hair_color)
          .filter(Boolean),
      ),
    question: (value) => `髪色は「${value}」ですか？`,
  },
  {
    key: 'hair-style',
    reliability: 0.76,
    limit: 30,
    values: (product) =>
      unique(
        (product.performers || [])
          .map((item) => item.hair_style)
          .filter(Boolean),
      ),
    question: (value) => `髪型は「${value}」ですか？`,
  },
]

function buildDynamicQuestions(products: Product[]) {
  const questions: Question[] = []

  for (const field of DYNAMIC_FIELDS) {
    const occurrences = new Map<string, { label: string; count: number }>()
    let knownProducts = 0

    for (const product of products) {
      const values = unique(field.values(product))
      if (!values.length) continue
      knownProducts += 1

      for (const value of values) {
        const key = normalized(value)
        const current = occurrences.get(key)
        occurrences.set(key, {
          label: current?.label || value,
          count: (current?.count || 0) + 1,
        })
      }
    }

    if (knownProducts < 4) continue

    const selected = Array.from(occurrences.entries())
      .filter(
        ([, entry]) =>
          entry.count >= 1 &&
          entry.count < knownProducts &&
          isAllowedQuestionValue(entry.label),
      )
      .sort(
        (a, b) =>
          Math.abs(0.5 - a[1].count / knownProducts) -
          Math.abs(0.5 - b[1].count / knownProducts),
      )
      .slice(0, field.limit)

    for (const [valueKey, entry] of selected) {
      questions.push({
        id: `auto:${field.key}:${valueKey}`,
        text: field.question(entry.label),
        reliability: field.reliability,
        matches: (product) => {
          const values = field.values(product)
          if (!values.length) return null
          return values.some((value) => normalized(value) === valueKey)
        },
      })
    }
  }

  return questions
}

type AdultConcept = {
  id: string
  text: string
  words: string[]
  reliability?: number
}

const ADULT_CONCEPTS: AdultConcept[] = [
  {
    id: 'adult-mature',
    text: '熟女・年上系の作品ですか？',
    words: ['熟女', '年上', 'お姉さん系'],
  },
  {
    id: 'adult-married',
    text: '人妻や夫婦の設定ですか？',
    words: ['人妻', '夫婦', '若妻', '既婚'],
  },
  {
    id: 'body-busty',
    text: '巨乳・豊満な体型が特徴ですか？',
    words: ['巨乳', '爆乳', '豊満'],
  },
  {
    id: 'body-slim',
    text: 'スレンダーな体型が特徴ですか？',
    words: ['スレンダー', '細身'],
  },
  {
    id: 'body-curvy',
    text: 'ぽっちゃり・肉感的な体型ですか？',
    words: ['ぽっちゃり', '肉感', 'マシュマロ'],
  },
  {
    id: 'body-hips',
    text: 'お尻や下半身が特徴の作品ですか？',
    words: ['巨尻', '美尻', 'デカ尻'],
  },
  {
    id: 'genre-lesbian',
    text: '女性同士の関係が中心ですか？',
    words: ['レズ', 'レズビアン', '百合'],
    reliability: 0.94,
  },
  {
    id: 'genre-futanari',
    text: '成人向けのふたなり要素がありますか？',
    words: ['ふたなり', '両性具有'],
    reliability: 0.96,
  },
  {
    id: 'genre-scat',
    text: 'スカトロ系の要素がありますか？',
    words: ['スカトロ', '排泄', '糞尿'],
    reliability: 0.96,
  },
  {
    id: 'genre-sm',
    text: 'SMや緊縛の要素がありますか？',
    words: ['SM', 'BDSM', '緊縛', '拘束'],
    reliability: 0.94,
  },
  {
    id: 'genre-anal',
    text: 'アナル系の要素がありますか？',
    words: ['アナル', '肛門'],
    reliability: 0.94,
  },
  {
    id: 'fetish-feet',
    text: '脚・足のフェチ要素が強いですか？',
    words: ['脚フェチ', '足フェチ', '美脚', '足裏'],
  },
  {
    id: 'fetish-stockings',
    text: 'ストッキングやタイツが特徴ですか？',
    words: ['ストッキング', 'タイツ', 'パンスト'],
  },
  {
    id: 'fetish-nipple',
    text: '乳首への愛撫が特徴の作品ですか？',
    words: ['乳首', 'チクビ'],
  },
  {
    id: 'fetish-cosplay',
    text: '成人のコスプレ設定がありますか？',
    words: ['コスプレ', 'コスチューム'],
  },
  {
    id: 'clothing-lingerie',
    text: 'ランジェリーや下着が印象的ですか？',
    words: ['ランジェリー', '下着', 'ブラジャー'],
  },
  {
    id: 'relation-ntr',
    text: '寝取られ・寝取りの設定ですか？',
    words: ['NTR', '寝取られ', '寝取り'],
    reliability: 0.94,
  },
  {
    id: 'relation-couple',
    text: 'カップルや恋人関係が中心ですか？',
    words: ['カップル', '恋人', '彼氏', '彼女'],
  },
  {
    id: 'situation-massage',
    text: 'マッサージやエステが舞台ですか？',
    words: ['マッサージ', 'エステ', 'セラピスト'],
  },
  {
    id: 'situation-medical',
    text: '病院や医療系の設定ですか？',
    words: ['病院', '医者', '看護師', 'ナース', '診察'],
  },
  {
    id: 'situation-transport',
    text: '電車やバスなどの乗り物が舞台ですか？',
    words: ['電車', 'バス', '夜行バス', '車内'],
  },
  {
    id: 'situation-bath',
    text: '浴室・お風呂が舞台ですか？',
    words: ['浴室', '風呂', '温泉', '洗面所'],
  },
  {
    id: 'format-vr',
    text: 'VRや主観映像の作品ですか？',
    words: ['VR', 'POV', '主観'],
    reliability: 0.96,
  },
  {
    id: 'format-amateur',
    text: '素人風・ドキュメンタリー風ですか？',
    words: ['素人', 'ドキュメンタリー', 'リアル'],
  },
  {
    id: 'format-compilation',
    text: '総集編や複数作品のまとめですか？',
    words: ['総集編', 'ベスト', 'コンピレーション'],
  },
  {
    id: 'tone-hard',
    text: 'ハードで激しい雰囲気の作品ですか？',
    words: ['ハード', '激しい', '過激'],
  },
  {
    id: 'tone-soft',
    text: '穏やかでソフトな雰囲気ですか？',
    words: ['ソフト', '穏やか', 'いやし'],
  },
]

function peopleCount(product: Product) {
  const attributes = productAttributes(product)
  const visual = visualAttributes(product)
  const value = attributes['人数'] ?? visual.people
  const count = Number(value)
  return Number.isFinite(count) && count > 0 ? count : null
}

const BASE_QUESTIONS: Question[] = [
  {
    id: 'solo',
    text: '登場する人物は1人が中心ですか？',
    reliability: 0.86,
    matches: (product) => {
      const count = peopleCount(product)
      return count === null ? null : count === 1
    },
  },
  {
    id: 'pair',
    text: '登場する人物は2人が中心ですか？',
    reliability: 0.86,
    matches: (product) => {
      const count = peopleCount(product)
      return count === null ? null : count === 2
    },
  },
  {
    id: 'group',
    text: '3人以上の複数人が登場しますか？',
    reliability: 0.86,
    matches: (product) => {
      const count = peopleCount(product)
      return count === null ? null : count >= 3
    },
  },
  {
    id: 'hair-black',
    text: '髪色は黒系ですか？',
    matches: (product) =>
      performerMatches(product, 'hair_color', ['黒', '黒髪']) ||
      includesAny(product, ['黒髪', '黒系']),
  },
  {
    id: 'hair-brown',
    text: '髪色は茶色系ですか？',
    matches: (product) =>
      performerMatches(product, 'hair_color', ['茶', '茶髪']) ||
      includesAny(product, ['茶髪', '茶色']),
  },
  {
    id: 'hair-blonde',
    text: '髪色は金髪系ですか？',
    matches: (product) =>
      performerMatches(product, 'hair_color', ['金', '金髪']) ||
      includesAny(product, ['金髪']),
  },
  {
    id: 'hair-long',
    text: '髪型はロングですか？',
    matches: (product) =>
      performerMatches(product, 'hair_style', ['ロング']) ||
      includesAny(product, ['ロング']),
  },
  {
    id: 'hair-short',
    text: '髪型はショートですか？',
    matches: (product) =>
      performerMatches(product, 'hair_style', ['ショート']) ||
      includesAny(product, ['ショート']),
  },
  {
    id: 'hair-bob',
    text: '髪型はボブですか？',
    matches: (product) =>
      performerMatches(product, 'hair_style', ['ボブ']) ||
      includesAny(product, ['ボブ']),
  },
  {
    id: 'glasses',
    text: 'メガネをかけていますか？',
    matches: (product) =>
      performerMatches(product, 'glasses', [true]) ||
      includesAny(product, ['メガネ', '眼鏡']),
  },
  ...[
    ['clothing-uniform', '成人の制服風コスプレですか？', ['制服', '体操服']],
    ['clothing-suit', 'スーツを着ていますか？', ['スーツ']],
    [
      'clothing-casual',
      '私服やワンピースが中心ですか？',
      ['私服', 'ワンピース'],
    ],
    ['location-hotel', 'ホテルや宿泊施設が舞台ですか？', ['ホテル', '旅館']],
    ['location-school', '学校風のセットや教室が舞台ですか？', ['学校', '教室']],
    [
      'location-office',
      'オフィスや職場が舞台ですか？',
      ['オフィス', '職場', '会社'],
    ],
    ['location-home', '自宅や室内が中心ですか？', ['自宅', '和室', '寝室']],
    ['location-outdoor', '屋外のシーンが中心ですか？', ['屋外', '野外']],
    ['type-pure', '清楚系の雰囲気ですか？', ['清楚系', '清楚']],
    ['type-gal', 'ギャル系ですか？', ['ギャル系', 'ギャル']],
    ['type-mature', 'お姉さん系や熟女系ですか？', ['お姉さん系', '熟女']],
    ['mood-bright', '明るく活発な雰囲気ですか？', ['明るい', '活発']],
    [
      'mood-romantic',
      'ロマンチックで落ち着いた雰囲気ですか？',
      ['ロマンチック', '落ち着いた'],
    ],
  ].map(([id, text, words]) => ({
    id: id as string,
    text: text as string,
    matches: (product: Product) => includesAny(product, words as string[]),
  })),
  ...ADULT_CONCEPTS.map((concept) => ({
    id: concept.id,
    text: concept.text,
    reliability: concept.reliability ?? 0.88,
    matches: (product: Product) => includesAny(product, concept.words),
  })),
]

function answerFactor(answer: Answer, matches: boolean | null) {
  if (answer === 'unknown') return 1
  if (matches === null) return 0.5
  if (answer === 'yes') return matches ? 0.95 : 0.05
  if (answer === 'likely-yes') return matches ? 0.75 : 0.25
  if (answer === 'likely-no') return matches ? 0.25 : 0.75
  return matches ? 0.05 : 0.95
}

function nextQuestion(
  candidates: Candidate[],
  askedIds: string[],
  questions: Question[],
) {
  const totalWeight = candidates.reduce(
    (sum, candidate) => sum + candidate.weight,
    0,
  )

  if (!totalWeight) return null

  return (
    questions
      .filter((question) => !askedIds.includes(question.id))
      .map((question) => {
        let knownWeight = 0
        let yesWeight = 0

        for (const candidate of candidates) {
          const matches = question.matches(candidate.product)
          if (matches === null) continue
          knownWeight += candidate.weight
          if (matches) yesWeight += candidate.weight
        }

        const coverage = knownWeight / totalWeight
        const ratio = knownWeight ? yesWeight / knownWeight : 0
        const balance = Math.abs(0.5 - ratio)
        const reliabilityPenalty = 1 - (question.reliability ?? 0.8)
        const score = balance + (1 - coverage) * 0.85 + reliabilityPenalty * 0.2

        return { question, ratio, coverage, score }
      })
      .filter(
        ({ ratio, coverage }) =>
          coverage >= 0.12 && ratio > 0.03 && ratio < 0.97,
      )
      .sort((a, b) => a.score - b.score)[0]?.question || null
  )
}

export default function QuizFinder() {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [answering, setAnswering] = useState(false)
  const [error, setError] = useState('')
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [questions, setQuestions] = useState<Question[]>(BASE_QUESTIONS)
  const [askedIds, setAskedIds] = useState<string[]>([])
  const [result, setResult] = useState<Product | null>(null)

  const question = useMemo(
    () => nextQuestion(candidates, askedIds, questions),
    [candidates, askedIds, questions],
  )
  const viableCandidateCount = useMemo(() => {
    const topWeight = candidates[0]?.weight || 0
    if (!topWeight) return candidates.length
    return candidates.filter((candidate) => candidate.weight >= topWeight * 0.1)
      .length
  }, [candidates])

  useEffect(() => {
    if (!open) return

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', closeOnEscape)

    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])

  async function start() {
    setOpen(true)
    setLoading(true)
    setAnswering(false)
    setError('')
    setCandidates([])
    setQuestions(BASE_QUESTIONS)
    setAskedIds([])
    setResult(null)

    try {
      const response = await fetch(API + '/search', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ query: '' }),
      })
      const data = await response.json()

      if (!response.ok) throw new Error('作品候補を取得できませんでした')

      const products = (data.results || []) as Product[]
      if (!products.length) {
        throw new Error('質問で探せる作品がまだありません')
      }

      setCandidates(
        products.map((product) => ({ product, weight: 1 / products.length })),
      )
      setQuestions([...BASE_QUESTIONS, ...buildDynamicQuestions(products)])
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : '作品候補を取得できませんでした',
      )
    } finally {
      setLoading(false)
    }
  }

  async function answerQuestion(answer: Answer) {
    if (!question || answering) return

    setAnswering(true)
    await new Promise((resolve) =>
      window.setTimeout(resolve, ANSWER_TRANSITION_MS),
    )

    const updated = candidates
      .map((candidate) => ({
        ...candidate,
        weight:
          candidate.weight *
          answerFactor(answer, question.matches(candidate.product)),
      }))
      .sort((a, b) => b.weight - a.weight)

    const totalWeight = updated.reduce(
      (sum, candidate) => sum + candidate.weight,
      0,
    )
    const normalized = updated.map((candidate) => ({
      ...candidate,
      weight: totalWeight ? candidate.weight / totalWeight : 0,
    }))
    const nextAskedIds = [...askedIds, question.id]
    const topConfidence = normalized[0]?.weight || 0
    const secondConfidence = normalized[1]?.weight || 0
    const confidenceLead = secondConfidence
      ? topConfidence / secondConfidence
      : Number.POSITIVE_INFINITY
    const effectiveCandidates = normalized.filter(
      (candidate) => candidate.weight >= topConfidence * 0.1,
    ).length
    const noQuestionLeft = !nextQuestion(normalized, nextAskedIds, questions)

    setCandidates(normalized)
    setAskedIds(nextAskedIds)

    if (
      nextAskedIds.length >= MAX_QUESTIONS ||
      (nextAskedIds.length >= MIN_QUESTIONS &&
        topConfidence >= 0.8 &&
        confidenceLead >= 3) ||
      (nextAskedIds.length >= MIN_QUESTIONS &&
        effectiveCandidates <= 2 &&
        confidenceLead >= 2) ||
      noQuestionLeft
    ) {
      setResult(normalized[0]?.product || null)
    }
    setAnswering(false)
  }

  function rejectResult() {
    if (!result) return

    const remaining = candidates.filter(
      (candidate) => candidate.product.id !== result.id,
    )
    const totalWeight = remaining.reduce(
      (sum, candidate) => sum + candidate.weight,
      0,
    )

    setCandidates(
      remaining.map((candidate) => ({
        ...candidate,
        weight: totalWeight ? candidate.weight / totalWeight : 0,
      })),
    )
    setResult(null)
  }

  return (
    <>
      <section className="quizLaunch">
        <button className="quizLaunchButton" onClick={start}>
          <span className="quizLaunchAvatar" aria-hidden="true">
            <img src="/quiz-guide.png" alt="" />
          </span>
          <b>エロ博士に聞く</b>
        </button>
        <div className="discoveryActions">
          <RandomGenerator />
          <a
            className="discoveryAction fanzaAction"
            href="https://video.dmm.co.jp/av/"
            target="_blank"
            rel="noopener noreferrer sponsored"
          >
            <span aria-hidden="true">↗</span>
            <span>
              <small>PR / FANZA</small>
              <b>FANZAに行く</b>
            </span>
            <i aria-hidden="true">↗</i>
          </a>
        </div>
      </section>

      {open && (
        <div
          className="quizOverlay"
          role="presentation"
          onClick={() => setOpen(false)}
        >
          <section
            className="quizModal"
            role="dialog"
            aria-modal="true"
            aria-label="質問で作品を探す"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="quizModalHeader">
              <div>
                <small>QUESTION FINDER</small>
                <b>質問で作品を探す</b>
              </div>
              <button onClick={() => setOpen(false)} aria-label="閉じる">
                ×
              </button>
            </header>

            <div className="quizModalBody">
              <div className="quizGuide" aria-hidden="true">
                <img src="/quiz-guide.png" alt="" />
                <span>AV NAVIGATOR</span>
              </div>

              <div className="quizConversation">
                {loading && (
                  <div className="quizLoading">
                    <i />
                    <span>作品候補を準備中…</span>
                  </div>
                )}
                {error && <div className="monitorError">{error}</div>}

                {!loading && !error && result && (
                  <div className="quizResult">
                    <div className="quizSpeech quizResultSpeech">
                      <span>私が思い浮かべたのは…</span>
                      <h2>{result.title}</h2>
                      <p>{result.description}</p>
                    </div>
                    <div className="quizResultActions">
                      <a href={API + '/go/' + result.id} target="_blank">
                        この作品を見る →
                      </a>
                      <button onClick={rejectResult}>違う、質問を続ける</button>
                      <button onClick={start}>最初から</button>
                    </div>
                  </div>
                )}

                {!loading && !error && !result && question && (
                  <div className="quizQuestion">
                    <div className="quizProgress">
                      <span>
                        QUESTION {String(askedIds.length + 1).padStart(2, '0')}
                        {' / '}
                        {MAX_QUESTIONS}
                      </span>
                      <small>候補 {viableCandidateCount} 作品</small>
                    </div>
                    <div className="quizSpeech">
                      <small>あなたの探している作品は…</small>
                      <h2>{question.text}</h2>
                    </div>
                    {answering ? (
                      <div className="quizAnswerLoading" aria-live="polite">
                        <i />
                        <span>次の質問を選んでいます…</span>
                      </div>
                    ) : (
                      <div className="quizAnswers">
                        {ANSWERS.map(({ answer, label }) => (
                          <button
                            key={answer}
                            onClick={() => void answerQuestion(answer)}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </section>
        </div>
      )}
    </>
  )
}
