# AV AI Search

作品メタデータをJSONで保存し、自然文の検索条件化・属性フィルタ・FANZA送客を行うMVPです。

## 起動

```bash
cp .env.example .env
docker compose up --build
```

Frontend: http://localhost:3000 / Backend: http://localhost:8000/docs

`POST /products/seed` でサンプル作品を登録できます。AI処理はすべてGemini APIを利用します。検索条件化だけはAPI障害時に簡易パーサーへフォールバックします。

AI設定は3系統に分けています。`QUERY_AI_API_KEY` はユーザーの希望を検索条件JSONへ変換し、Embeddingを作る検索AI用です。`IMPORT_AI_API_KEY` は取得した動画フレームを作品JSONへ変換する取込AI用です。`DESCRIPTION_AI_API_KEY` は正式タイトルと先に生成したJSONから短い説明文 `summary` を作る説明AI用です。必要なら同じGemini APIキーを複数用途へ設定しても構いません。

取込JSONには `schema_version` を保存します。この値は検索用JSONのトップレベル項目数（`schema_version` 自身を除く）で、現在は11です。項目を追加・削除するとコード上のフィールド定義から自動的に更新されます。`source_title` には取得元ページの正式タイトル、`source_metadata` にはHTMLから取得した概要・配信日・品番・ジャンル・メーカー・監督・レーベル、`title` にはAIが作った検索向けタイトル、`summary` には正式タイトルと先行JSONから説明AIが作った短い説明を保存します。動画解析AIと説明AIは `source_metadata` を一次情報として優先します。

## MissAVからローカル取得

規約・権利上取得可能な公開作品URLを1件ずつバックグラウンド取得します。取得後、動画から6枚の画像をローカル抽出し、画像だけをGemini APIへ送信して検索用JSONを作成し、DBへ自動登録します。動画本体はAPIへ送りません。ログイン回避、DRM解除、プレイリスト一括取得は行いません。

既定の `KEEP_SOURCE_VIDEO=false` では解析の成否にかかわらず作業用の動画・抽出JSONを削除します。検索用JSONはPostgreSQLの `products.attributes` に残ります。手動取得で `analyze=false` を指定した場合だけ、解析前提ではないため動画を残します。

```bash
curl -X POST http://localhost:8000/imports/missav \
  -H 'content-type: application/json' \
  -d '{"url":"https://missav.example/作品URL","analyze":true}'

curl http://localhost:8000/imports/返されたジョブID
```

`MAX_VIDEO_BYTES` で1ファイルの上限を変更できます。既定値は2GBです。

Cloudflareの公開ページで403になる場合に備え、取得コンテナにはyt-dlpのブラウザ通信互換用依存（curl-cffi）を含めています。MissAVのページ自体は専用アダプターで取得し、HTMLや公開設定に含まれる直接動画URLだけをyt-dlpへ渡します。反映には再ビルドが必要です。

```bash
docker compose up -d --build backend worker
docker compose logs -f backend
```

サイト側で強いチャレンジやアクセス制限が有効な場合は、公開URLでも自動取得できないことがあります。その場合は無理に回避せず、権利・規約上利用可能な別の公式取得経路を使ってください。

## 1日1〜10本の自動取込

`worker` サービスが指定した新着・一覧ページを定期確認し、未処理URLだけをキューへ追加します。同じURLはDBの一意制約で重複登録を防ぎ、日付が変わると日次件数をリセットします。API費用を確実に抑えるため、成功件数ではなく処理を試した本数を日次上限として数えます。失敗した作品は翌日以降に既定3回まで再試行します。

`.env` に次を設定してください。

```env
AUTO_IMPORT_ENABLED=true
MISSAV_FEED_URL=https://対象ドメイン/新着または一覧ページ
AUTO_IMPORT_DAILY_LIMIT=3
```

日次上限は安全のためコード側でも1〜10に制限されています。ページ確認は既定6時間ごと、作品間は既定5分です。調整する場合は `AUTO_IMPORT_POLL_SECONDS` と `AUTO_IMPORT_BETWEEN_ITEMS_SECONDS` を変更します。

日次上限は自動取込にだけ適用されます。トップ画面からの手動取込と、取込状況画面の「読み込みを実施する」による手動実行には適用しません。後者は一覧ページから未取得・未登録の作品をランダムに1件選び、手動キューへ追加します。

設定反映と状態確認:

```bash
docker compose up -d --build
curl http://localhost:8000/auto-import/status
docker compose logs -f worker
```

一覧ページが通常HTTPアクセスを拒否する場合は、ブラウザで確認した公開作品URLを最大10件まで手動キューへ渡せます。この手動キューは日次上限の対象外です。

```bash
curl -X POST http://localhost:8000/auto-import/enqueue \
  -H 'content-type: application/json' \
  -d '{"urls":["https://対象ドメイン/ja/作品ID"]}'
```

自動取込は `AUTO_IMPORT_ENABLED=false` に戻して `docker compose up -d` を実行すれば停止できます。キューや登録済みJSONは削除されません。
