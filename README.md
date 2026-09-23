# AV AI Search

作品メタデータをJSONで保存し、自然文の検索条件化・属性フィルタ・FANZA送客を行うMVPです。

## 起動

```bash
./av run
```

Frontend: http://localhost:3000 / Backend: http://localhost:8000/docs

`av run` はフロントエンドをNext.jsの開発モードで起動します。`frontend`
配下のページ・コンポーネント・CSSを変更すると、コンテナを作り直さなくても
自動でブラウザに反映されます。

`POST /admin/products/seed` でサンプル作品を登録できます。検索条件化、動画フレーム解析、5件の画像解析報告の統合にGemini APIを利用します。タイトルやMissAVの概要はGeminiへ送らず、取得値を `source` にそのまま保存します。画像由来の統合結果は `visual_analysis` へ保存し、統合API障害時はローカル統合へフォールバックします。

## 本番サーバーへの接続

本番はDocker Composeではなく、ユーザー単位のsystemdサービスで動作しています。
本番反映時は、まず次のコマンドで接続します。

```bash
ssh harazyuku@av-search.tailc7d85e.ts.net
```

### バックエンドだけを更新する

`backend/`だけを変更した場合は、SSH接続後に次のブロックをそのまま貼り付けます。
サーバーに未コミットの変更がある場合は、安全のため更新を中止します。

```bash
(
set -e
cd /home/harazyuku/AV

if [ -n "$(git status --porcelain)" ]; then
  echo "サーバーに未コミットの変更があります。内容を確認してから再実行してください。" >&2
  git status --short
  exit 1
fi

git pull --ff-only origin main
backend/.venv/bin/pip install -r backend/requirements.txt
systemctl --user restart av-backend.service

systemctl --user is-active av-backend.service
curl -fsS http://127.0.0.1:8000/health
)
```

サムネイル取得まで確認する場合は、続けて次を実行します。

```bash
curl -fsS \
  -o /tmp/start-638.jpg \
  -w 'HTTP %{http_code} / %{content_type} / %{size_download} bytes\n' \
  'http://127.0.0.1:8000/media/thumbnail/START-638?v=2'

file /tmp/start-638.jpg
```

### フロントエンドを含めて全体を更新する

フロントエンドとバックエンドの両方を変更した場合は、SSH接続後に次のブロックを
そのまま貼り付けます。

```bash
(
set -e
cd /home/harazyuku/AV

if [ -n "$(git status --porcelain)" ]; then
  echo "サーバーに未コミットの変更があります。内容を確認してから再実行してください。" >&2
  git status --short
  exit 1
fi

git pull --ff-only origin main
backend/.venv/bin/pip install -r backend/requirements.txt

cd frontend
npm ci
npm run build
cd ..

systemctl --user restart av-backend.service
systemctl --user restart av-frontend.service

systemctl --user is-active av-backend.service av-frontend.service
curl -fsS http://127.0.0.1:8000/health
curl -fsS -o /dev/null -w 'Frontend HTTP %{http_code}\n' http://127.0.0.1:3100/
)
```

`av-worker.service`は動画取込中に再起動すると処理中のジョブへ影響します。
`backend/app/worker.py`や、workerが利用する取込処理を変更した場合だけ、取込中でないことを
確認してから次を実行してください。

```bash
systemctl --user restart av-worker.service
systemctl --user is-active av-worker.service
```

AI設定は3系統に分けています。`QUERY_AI_API_KEY` はユーザーの希望を検索条件JSONへ変換し、Embeddingを作る検索AI用です。`IMPORT_AI_API_KEY`〜`IMPORT_AI_API_KEY_5` は30枚の動画フレームを6枚ずつ解析するGemini用です。`DESCRIPTION_AI_API_KEY` は5件の画像解析報告だけを `visual_analysis` へ統合するGemini用で、未設定時は最初の取込キーを使います。

取込JSONには `schema_version` を保存します。この値は検索用JSONのトップレベル項目数（`schema_version` 自身を除く）で、現在は11です。項目を追加・削除するとコード上のフィールド定義から自動的に更新されます。`source_title` には取得元ページの正式タイトル、`source_metadata` にはHTMLから取得した概要・配信日・品番・ジャンル・メーカー・監督・レーベル、`title` にはAIが作った検索向けタイトル、`summary` には正式タイトルと先行JSONから説明AIが作った短い説明を保存します。動画解析AIと説明AIは `source_metadata` を一次情報として優先します。

## MissAVからローカル取得

規約・権利上取得可能な公開作品URLを1件ずつバックグラウンド取得します。取得後、動画から6枚の画像をローカル抽出し、画像だけをGemini APIへ送信して検索用JSONを作成し、DBへ自動登録します。動画本体はAPIへ送りません。ログイン回避、DRM解除、プレイリスト一括取得は行いません。

既定の `KEEP_SOURCE_VIDEO=false` では解析の成否にかかわらず作業用の動画・抽出JSONを削除します。検索用JSONはPostgreSQLの `products.attributes` に残ります。手動取得で `analyze=false` を指定した場合だけ、解析前提ではないため動画を残します。

```bash
curl -X POST http://localhost:8000/admin/imports/missav \
  -H 'content-type: application/json' \
  -d '{"url":"https://missav.example/作品URL","analyze":true}'

curl http://localhost:8000/admin/imports/返されたジョブID
```

`MAX_VIDEO_BYTES` で1ファイルの上限を変更できます。既定値は2GBです。

Cloudflareの公開ページで403になる場合に備え、取得コンテナにはyt-dlpのブラウザ通信互換用依存（curl-cffi）を含めています。MissAVのページ自体は専用アダプターで取得し、HTMLや公開設定に含まれる直接動画URLだけをyt-dlpへ渡します。ローカルのDocker Compose環境への反映には再ビルドが必要です。本番では前述のsystemd用手順を使ってください。

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

ローカルのDocker Compose環境での設定反映と状態確認:

```bash
docker compose up -d --build
curl http://localhost:8000/admin/auto-import/status
docker compose logs -f worker
```

一覧ページが通常HTTPアクセスを拒否する場合は、ブラウザで確認した公開作品URLを最大10件まで手動キューへ渡せます。この手動キューは日次上限の対象外です。

```bash
curl -X POST http://localhost:8000/admin/auto-import/enqueue \
  -H 'content-type: application/json' \
  -d '{"urls":["https://対象ドメイン/ja/作品ID"]}'
```

自動取込は `AUTO_IMPORT_ENABLED=false` に戻して `docker compose up -d` を実行すれば停止できます。キューや登録済みJSONは削除されません。

## 管理画面とCloudflare Access

管理画面は `/admin/*`、登録・削除・ワーカー操作APIは `/admin/*` に集約しています。公開ヘッダーには管理画面へのリンクを表示しません。ローカルでは `http://localhost:3000/admin` を直接開けます。本番でCloudflare Accessを設定すると、同じURLの手前にCloudflareのログイン画面が表示されます。

設定項目と本番公開時の確認手順は [`docs/cloudflare-access.md`](docs/cloudflare-access.md) を参照してください。
