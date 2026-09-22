'use client'

import { useEffect, useMemo, useState } from 'react'

const API = process.env.NEXT_PUBLIC_API_URL || '/api'

type ImportedProduct = {
  id: number
  external_id: string
  title?: string
  description?: string
  attributes?: Record<string, unknown>
  source?: {
    title?: string
    description?: string
    metadata?: Record<string, unknown>
  }
  visual_analysis?: {
    people?: number
    locations?: string[]
    keywords?: string[]
  }
}

type Choice = {
  label: string
  words?: string[]
  people?: number | 'many'
  neutral?: boolean
}

type Step = {
  eyebrow: string
  question: string
  choices: Choice[]
}

const STEPS: Step[] = [
  {
    eyebrow: 'TYPE',
    question: '女優の系統',
    choices: [
      {
        label: 'ロリ系',
        words: ['童顔', '小柄', 'ミニ系', 'ロリ系'],
      },
      {
        label: '学生',
        words: ['女子大生', '学生風', '学園もの', '制服', '学生服'],
      },
      { label: 'お姉さん', words: ['お姉さん', '美女', '長身'] },
      { label: '熟女', words: ['熟女', '人妻', '主婦'] },
      { label: 'ババア', words: ['シニア', '老女', 'お婆ちゃん'] },
    ],
  },
  {
    eyebrow: 'LOCATION',
    question: 'シチュエーション',
    choices: [
      {
        label: '公共施設',
        words: ['公共施設', '病院', '学校', '電車', 'バス', '職場'],
      },
      { label: '家', words: ['家', '自宅', '部屋', '家庭', 'リビング'] },
      { label: '屋外', words: ['屋外', '野外', '露出', '公園', '路上'] },
      { label: 'ホテル', words: ['ホテル', '旅館', '温泉'] },
      { label: 'その他', neutral: true },
    ],
  },
  {
    eyebrow: 'PEOPLE',
    question: '登場人数',
    choices: [
      { label: '一人', people: 1 },
      { label: '二人', people: 2 },
      { label: '三人', people: 3 },
      { label: '四人', people: 4 },
      { label: '多数', people: 'many' },
    ],
  },
  {
    eyebrow: 'STYLE',
    question: 'プレイの傾向',
    choices: [
      { label: '総受け', words: ['総受け', '輪姦', '複数プレイ', '乱交'] },
      { label: 'オナニー', words: ['オナニー', '自慰', 'オナサポ'] },
      {
        label: 'ノーマル',
        words: ['ノーマル', '単体作品', '恋愛', 'カップル'],
      },
      {
        label: '強制・凌辱系',
        words: ['レイプ', '強姦', '強制', '凌辱', '鬼畜'],
      },
      {
        label: '寝取られ',
        words: ['寝取られ', '寝取り', 'NTR', '不倫'],
      },
    ],
  },
  {
    eyebrow: 'CAST',
    question: '出演者の系統',
    choices: [
      { label: '素人', words: ['素人', 'ナンパ', '投稿'] },
      {
        label: 'プロ',
        words: ['単体作品', '専属', '女優', 'アイドル', '芸能人'],
      },
    ],
  },
]

function productText(product: ImportedProduct) {
  return [
    product.title,
    product.description,
    product.source?.title,
    product.source?.description,
    JSON.stringify(product.source?.metadata || {}),
    JSON.stringify(product.attributes || {}),
    JSON.stringify(product.visual_analysis || {}),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

function productPeople(product: ImportedProduct) {
  const visualPeople = Number(product.visual_analysis?.people)
  if (Number.isFinite(visualPeople) && visualPeople > 0) return visualPeople

  const attributePeople = Number(product.attributes?.['人数'])
  return Number.isFinite(attributePeople) && attributePeople > 0
    ? attributePeople
    : 0
}

function matchesChoice(product: ImportedProduct, choice: Choice) {
  if (choice.neutral) return true

  if (choice.people !== undefined) {
    const people = productPeople(product)
    if (!people) return false
    return choice.people === 'many' ? people >= 5 : people === choice.people
  }

  const text = productText(product)
  return (choice.words || []).some((word) => text.includes(word.toLowerCase()))
}

export default function RandomGenerator() {
  const [open, setOpen] = useState(false)
  const [stepIndex, setStepIndex] = useState(0)
  const [answers, setAnswers] = useState<Choice[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const step = STEPS[stepIndex]
  const progress = useMemo(
    () =>
      `${String(stepIndex + 1).padStart(2, '0')} / ${String(STEPS.length).padStart(2, '0')}`,
    [stepIndex],
  )

  useEffect(() => {
    if (!open) return

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !loading) setOpen(false)
    }
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', closeOnEscape)

    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', closeOnEscape)
    }
  }, [open, loading])

  function start() {
    setStepIndex(0)
    setAnswers([])
    setLoading(false)
    setError('')
    setOpen(true)
  }

  async function drawProduct(selectedAnswers: Choice[]) {
    setLoading(true)
    setError('')

    try {
      const response = await fetch(API + '/products/imported', {
        cache: 'no-store',
      })
      if (!response.ok) throw new Error('作品を取得できませんでした')

      const data = await response.json()
      const products = (data.items || []) as ImportedProduct[]
      if (!products.length) throw new Error('抽選できる作品がまだありません')

      const scored = products.map((product) => ({
        product,
        score: selectedAnswers.reduce(
          (total, choice) => total + (matchesChoice(product, choice) ? 1 : 0),
          0,
        ),
      }))
      const highestScore = Math.max(...scored.map(({ score }) => score))
      const finalists = scored.filter(({ score }) => score === highestScore)
      const selected = finalists[Math.floor(Math.random() * finalists.length)]

      window.location.assign(`/videos/${encodeURIComponent(selected.product.external_id.replace(/^missav-/, ''))}`)
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : '作品を選べませんでした',
      )
      setLoading(false)
    }
  }

  function selectChoice(choice: Choice) {
    if (loading) return
    const selectedAnswers = [...answers, choice]
    setAnswers(selectedAnswers)

    if (stepIndex === STEPS.length - 1) {
      void drawProduct(selectedAnswers)
      return
    }

    setStepIndex((current) => current + 1)
  }

  function goBack() {
    if (loading || stepIndex === 0) return
    setAnswers((current) => current.slice(0, -1))
    setStepIndex((current) => current - 1)
    setError('')
  }

  return (
    <>
      <button className="discoveryAction randomAction" onClick={start}>
        <span aria-hidden="true">↝</span>
        <span>
          <small>RANDOM GENERATOR</small>
          <b>オカズランダムジェネレーター</b>
        </span>
        <i aria-hidden="true">→</i>
      </button>

      {open && (
        <div
          className="randomOverlay"
          role="presentation"
          onClick={() => !loading && setOpen(false)}
        >
          <section
            className="randomModal"
            role="dialog"
            aria-modal="true"
            aria-label="オカズランダムジェネレーター"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="randomModalHeader">
              <div>
                <small>OKAZU RANDOM GENERATOR</small>
                <b>今日の1本を選ぶ</b>
              </div>
              <button
                type="button"
                aria-label="閉じる"
                disabled={loading}
                onClick={() => setOpen(false)}
              >
                ×
              </button>
            </header>

            <div className="randomProgress" aria-label={`質問 ${progress}`}>
              {STEPS.map((item, index) => (
                <span
                  className={index <= stepIndex ? 'active' : ''}
                  key={item.eyebrow}
                />
              ))}
            </div>

            {loading ? (
              <div className="randomLoading">
                <span className="quizLoadingSpin" aria-hidden="true" />
                <b>条件に近い作品を抽選中…</b>
                <small>最高一致の候補からランダムに選んでいます</small>
              </div>
            ) : (
              <div className="randomModalBody">
                <div className="randomQuestionMeta">
                  <small>{step.eyebrow}</small>
                  <span>{progress}</span>
                </div>
                <h2>{step.question}</h2>

                <div className="randomChoices">
                  {step.choices.map((choice) => (
                    <button
                      type="button"
                      key={choice.label}
                      onClick={() => selectChoice(choice)}
                    >
                      <b>{choice.label}</b>
                    </button>
                  ))}
                </div>

                {error && <p className="randomError">{error}</p>}

                <footer className="randomModalFooter">
                  <button
                    type="button"
                    onClick={goBack}
                    disabled={stepIndex === 0}
                  >
                    ← 前の質問
                  </button>
                  <span>
                    {answers.length
                      ? answers.map((answer) => answer.label).join(' / ')
                      : '5つの質問に答えてね'}
                  </span>
                </footer>
              </div>
            )}
          </section>
        </div>
      )}
    </>
  )
}
