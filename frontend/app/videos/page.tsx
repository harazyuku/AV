'use client'

import {useEffect,useState} from 'react'

const API=process.env.NEXT_PUBLIC_API_URL||'http://localhost:8000'
type ImportedProduct={
 schema_version:number
 id:number
 external_id:string
 title:string
 source_title:string
 source_metadata:Record<string,any>
 summary:string
 description:string
 source_url:string
 performers:Array<{name:string;type:string;hair_color:string;hair_style:string;glasses:boolean}>
 attributes:Record<string,any>
 created_at:string|null
}

const workCode=(item:ImportedProduct)=>String(item.attributes?.source_id||item.external_id).replace(/^missav-/,'').toUpperCase()
const displayTitle=(item:ImportedProduct)=>item.source_title||item.title
const importedAt=(value:string|null)=>value?new Intl.DateTimeFormat('ja-JP',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value)):'日時不明'

export default function VideosPage(){
 const [items,setItems]=useState<ImportedProduct[]>([])
 const [selected,setSelected]=useState<ImportedProduct|null>(null)
 const [loading,setLoading]=useState(true)
 const [error,setError]=useState('')
 useEffect(()=>{fetch(API+'/products/imported',{cache:'no-store'}).then(async response=>{if(!response.ok)throw new Error('一覧を取得できませんでした');return response.json()}).then(data=>setItems(data.items||[])).catch(err=>setError(err instanceof Error?err.message:'一覧を取得できませんでした')).finally(()=>setLoading(false))},[])
 return <main className="libraryPage">
  <nav className="pageNav"><a href="/">← 検索へ戻る</a><span>AV AI SEARCH</span></nav>
  <header className="libraryHeader"><div className="eyebrow">IMPORTED LIBRARY</div><h1>読み込んだ動画</h1><p>AI解析が完了し、検索用JSONとして保存された作品です。カードを押すとJSONを確認できます。</p></header>
  {loading&&<div className="libraryMessage">読み込み中…</div>}
  {error&&<div className="monitorError">{error}</div>}
  {!loading&&!error&&<section className="libraryGrid">
   {items.map(item=><button className="videoLibraryCard" key={item.id} onClick={()=>setSelected(item)}>
    <div className="videoLibraryCover"><small>VIDEO {String(item.id).padStart(2,'0')} · JSON v{item.schema_version}</small><strong>{workCode(item)}</strong><span>JSONを見る →</span></div>
    <div className="videoLibraryBody"><small>{importedAt(item.created_at)}</small><h2>{displayTitle(item)}</h2><p>{item.description||'説明はありません'}</p><div className="tags">{(item.attributes?.キーワード||[]).slice(0,4).map((tag:string)=><span key={tag}>{tag}</span>)}</div></div>
   </button>)}
   {!items.length&&<div className="monitorEmpty"><span>◇</span><h2>読み込んだ動画はまだありません</h2><p>取込とAI解析が完了すると、ここに追加されます。</p></div>}
  </section>}
  {selected&&<div className="jsonOverlay" role="presentation" onClick={()=>setSelected(null)}><section className="jsonPanel" role="dialog" aria-modal="true" aria-label={`${displayTitle(selected)}のJSON`} onClick={event=>event.stopPropagation()}><header><div><small>{workCode(selected)}</small><h2>{displayTitle(selected)}</h2></div><button onClick={()=>setSelected(null)} aria-label="閉じる">×</button></header><pre>{JSON.stringify(selected,null,2)}</pre></section></div>}
 </main>
}
