# Cloudflare Accessで管理画面を保護する

このプロジェクトでは、公開ページと管理機能を次のパスで分離しています。

## 保護対象

- フロントエンド: `https://app.example.com/admin/*`
- バックエンド: `https://api.example.com/admin/*`

公開検索、作品詳細、サムネイル取得など、`/admin/*`以外はAccessの対象にしません。

## 事前条件

1. フロントエンドとAPIのホスト名がCloudflareでプロキシされていること
2. 可能ならオリジンをCloudflare Tunnel経由で公開すること
3. `.env`の`NEXT_PUBLIC_API_URL`を本番API URLへ変更すること
4. `.env`の`CORS_ALLOW_ORIGINS`を本番フロントエンドのオリジンへ変更すること

```env
NEXT_PUBLIC_API_URL=https://api.example.com
CORS_ALLOW_ORIGINS=https://app.example.com
```

## Accessアプリケーション

Cloudflare Dashboardの **Zero Trust → Access controls → Applications** から、Self-hosted applicationを1つ作成します。

同じアプリケーションへ次の2ホストを追加します。

| Hostname | Path |
| --- | --- |
| `app.example.com` | `admin/*` |
| `api.example.com` | `admin/*` |

フロントエンドとAPIを同じAccessアプリケーションへ入れ、`Eager redirect cookie`を有効にします。これにより、フロントエンドで認証した後にAPI用の認証Cookieも発行されます。

## ログイン方式

GoogleをIdentity Providerとして追加するか、One-time PINを有効にします。

Allowポリシーは次のように設定します。

- Action: `Allow`
- Include: `Emails`
- Value: 管理者本人のメールアドレスだけ
- Session duration: `24 hours`または好みの期間

`Include: Everyone`や、メールアドレス制限のない`Login Methods: One-time PIN`は使用しないでください。

## 動作確認

1. シークレットウィンドウで公開トップを開き、ログインなしで表示されることを確認
2. `/admin`を開き、Cloudflareのログイン画面へ移動することを確認
3. 許可したメールアドレスでログインし、管理画面が表示されることを確認
4. 許可していないアドレスでは拒否されることを確認
5. `https://api.example.com/admin/auto-import/status`も未ログインでは拒否されることを確認
6. `/videos/1`などの公開作品詳細がAccessで遮断されないことを確認

## ローカル開発

`localhost`はCloudflareを通らないため、`http://localhost:3000/admin`を直接開けます。ローカル専用のログインフォームは実装していません。

本番のオリジンIPを直接公開する場合、Accessを迂回されないようファイアウォールでCloudflare以外からの通信を拒否するか、アプリ側で`Cf-Access-Jwt-Assertion`の署名・issuer・audienceを検証してください。ヘッダーの有無だけを確認する実装は安全ではありません。
