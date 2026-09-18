'use client'
import {useEffect,useState} from 'react'

const API=process.env.NEXT_PUBLIC_API_URL||'http://localhost:8000'
type ImportItem={id:number;url:string;status:string;title:string|null;product_id:number|null;attempts:number;error:string|null}
type AutoStatus={enabled:boolean;daily_limit:number;used_today:number;recent:ImportItem[]}
const stages=[
 {key:'pending',label:'待機中',detail:'順番を待っています'},
 {key:'downloading',label:'動画取得中',detail:'解析用データを読み込み中'},
 {key:'splitting',label:'シーン抽出中',detail:'動画から代表シーンを選択中'},
 {key:'json_building',label:'JSON生成中',detail:'AIが検索用データを整理中'},
 {key:'completed',label:'完成',detail:'検索データへの登録が完了'},
]
const stageIndex=(status:string)=>status==='processing'?1:Math.max(0,stages.findIndex(x=>x.key===status))
const workCode=(item:ImportItem)=>item.url.split('/').filter(Boolean).pop()?.toUpperCase()||`動画 ${item.id}`

export default function ImportsPage(){
 const [data,setData]=useState<AutoStatus|null>(null);const [connectionError,setConnectionError]=useState(false);const [changing,setChanging]=useState(false);const [running,setRunning]=useState(false);const [runMessage,setRunMessage]=useState('')
 useEffect(()=>{let active=true;const load=async()=>{try{const r=await fetch(API+'/auto-import/status',{cache:'no-store'});if(!r.ok)throw new Error();if(active){setData(await r.json());setConnectionError(false)}}catch{if(active)setConnectionError(true)}};load();const timer=setInterval(load,2000);return()=>{active=false;clearInterval(timer)}},[])
 const jobs=data?.recent||[];const remaining=data?Math.max(0,data.daily_limit-data.used_today):0
 async function toggleWorker(){if(!data||changing)return;setChanging(true);try{const r=await fetch(API+'/auto-import/control',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({enabled:!data.enabled})});if(!r.ok)throw new Error();const result=await r.json();setData({...data,enabled:result.enabled});setConnectionError(false)}catch{setConnectionError(true)}finally{setChanging(false)}}
 async function runNow(){if(running)return;setRunning(true);setRunMessage('');try{const r=await fetch(API+'/auto-import/run-now',{method:'POST'});const result=await r.json();if(!r.ok)throw new Error(result.detail||'読み込みを要求できませんでした');setRunMessage(result.message||'読み込みを要求しました')}catch(e){setRunMessage(e instanceof Error?e.message:'読み込みを要求できませんでした')}finally{setRunning(false)}}
 return <main className="importsPage">
  <nav className="pageNav"><a href="/">← 検索へ戻る</a><span>AV AI SEARCH</span></nav>
  <header className="importsHeader"><div><div className="eyebrow">IMPORT MONITOR</div><h1>動画の取込状況</h1><p>取得からシーン抽出、AIによるJSON生成までをリアルタイムで確認できます。</p></div><div className="workerControl"><div className={`workerBadge ${data&&!data.enabled?'paused':''}`}><span/>{data?.enabled?'自動取込 稼働中':'自動取込 一時停止中'}</div><button disabled={!data||changing} onClick={toggleWorker}>{changing?'切替中…':data?.enabled?'一時停止する':'再開する'}</button><button className="runNowButton" disabled={running} onClick={runNow}>{running?'要求中…':'読み込みを実施する'}</button>{runMessage&&<small className="runMessage">{runMessage}</small>}</div></header>
  <section className="summaryRow">
   <div><small>本日の処理</small><strong>{data?.used_today??'—'} <i>/ {data?.daily_limit??'—'} 本</i></strong></div>
   <div><small>本日の残り</small><strong>{data?remaining:'—'} <i>本</i></strong></div>
   <div><small>表示中</small><strong>{jobs.length} <i>件</i></strong></div>
   <div><small>更新</small><strong className="autoRefresh"><span/>2秒ごと</strong></div>
  </section>
  {connectionError&&<div className="monitorError">バックエンドに接続できません。再接続を待っています。</div>}
  <section className="monitorGrid" aria-label="動画取込状況" aria-live="polite">
   {jobs.map(item=>{const failed=item.status==='failed';const index=stageIndex(item.status);const current=failed?{label:'取得失敗',detail:item.error||'処理を完了できませんでした'}:stages[index]||stages[0];return <article className={`monitorCard ${failed?'isFailed':''} ${item.status==='completed'?'isDone':''}`} key={item.id}>
    <div className="monitorCardTop"><div><small>VIDEO {String(item.id).padStart(2,'0')}</small><h2>{workCode(item)}</h2><p>{item.title||'タイトル取得待ち'}</p></div><i>{failed?'!':item.status==='completed'?'✓':index+1}</i></div>
    <div className="fullStageTrack">{stages.map((stage,i)=><div key={stage.key} className={i<=index&&!failed?'active':''}><span/><small>{stage.label}</small></div>)}</div>
    <div className="currentState"><span className="statePulse"/><div><b>{current.label}</b><p title={current.detail}>{current.detail}</p></div></div>
    <footer><span>試行 {item.attempts} 回</span>{item.product_id&&<a href={`/?product=${item.product_id}`}>作品を見る →</a>}</footer>
   </article>})}
   {!jobs.length&&<div className="monitorEmpty"><span>＋</span><h2>取込待ちはありません</h2><p>動画を追加すると、ここに進捗カードが表示されます。</p></div>}
  </section>
 </main>
}
