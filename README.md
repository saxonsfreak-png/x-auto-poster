# x-auto-poster

X(旧Twitter)向けに、テキスト+画像投稿を自動生成し、1日3回(既定: 07:25 / 11:55 / 19:55 JST、`config.yaml` で変更可)、人の手を介さずGitHub Actions経由で自動投稿するパイプラインです。

## 設計方針(元の依頼との違い)

最初のご依頼にあった「Playwrightでブラウザ操作を人間らしく偽装し、Xのスパム検知/凍結・シャドウBAN判定を回避する」仕組みは、この実装には含めていません。理由は単純で、X自身の開発者ガイドラインが非API経由の自動操作(スクレイピング・ブラウザ自動操作)を明確に禁止し、違反した場合はアカウントの永久凍結対象になると明記しているためです。「人間と見分けがつかない偽装」を目的化した実装は、この規約違反を前提にしたものになってしまいます。

代わりに、投稿そのものは **Buffer の公式API** 経由で行うよう設計を変更しました。

- Bufferは投稿の予約・実行についてXから正式に許可された連携方法を使っているため、検知回避のための偽装(ランダム待機・タイピングゆらぎ・ダミースクロール等)が原理的に不要です。
- ちなみにX自体のAPIは2026年2月に無料枠が廃止され、従量課金(投稿1件あたり約$0.015〜)のみになりました。今回の投稿量(1日3件)なら数百円/月程度で収まりますが、「完全無料」というご要望に合わせて、無料枠のあるBuffer経由に倒しています。
- 「トレンドを収集して学習」の部分も、Xを外部からスクレイピングするのではなく、**このアカウント自身の過去の投稿実績(インプレッション等)をBuffer経由で取得し、次の生成に反映する**形にしました(`self_analysis` 設定、詳細は下記)。他人の投稿を無断でスクレイピングして真似る形は避けています。
- 画像生成についても当初はGemini(Nano Banana)を想定していましたが、**2026年8月時点でGeminiのネイティブ画像生成モデルは軒並み無料枠が廃止**されていたため、画像生成だけ無料枠のある **Cloudflare Workers AI**(FLUX.1-schnell)に変更しています。テキスト生成は引き続きGeminiです。

結果として、「完全無人・1日3回・画像付き・保守しやすい構成」というご要望はそのまま実現しつつ、規約違反にならず、かつ無料枠だけで動く形にしています。

## 全体構成

```
config.yaml                  # 投稿時間・文字数・NGワード・モデル名などの設定(機密情報なし)
.env.example                 # 必要な環境変数(APIキー等)のテンプレート
requirements.txt
src/
  config.py                   # 設定読み込み
  gemini_client.py            # Gemini API(テキスト生成専用)
  cloudflare_image_client.py  # Cloudflare Workers AI(画像生成専用)
  content_strategy.py         # プロンプト組み立て(フック原則 + 自己分析データ)
  image_host.py                # Cloudinaryへの画像アップロード
  buffer_client.py             # Buffer API(投稿予約・過去実績取得)
  scheduling.py                 # JST時刻→UTC dueAt 変換
  logging_setup.py             # フェーズ別ログ
  main.py                      # 全体のオーケストレーション
scripts/
  find_buffer_ids.py           # 組織ID・チャンネルIDを調べるための補助スクリプト
.github/workflows/post.yml    # 1日1回、その日の3投稿をBufferへ予約するワークフロー
```

**処理の流れ**: GitHub Actionsが1日1回(06:00 JST)起動 → その日の3時刻それぞれについて、Buffer上の自己分析データを踏まえてGeminiがテキストを生成 → Cloudflare Workers AIが画像を生成 → 画像をCloudinaryにアップロード → Buffer APIで「その時刻に投稿」を予約 → 実際の投稿(Xへの公開)は指定時刻にBufferが実行、という流れです。

## 必要なアカウント(すべて無料枠で開始可能)

| サービス | 用途 | 無料枠の目安 |
|---|---|---|
| [Google AI Studio](https://aistudio.google.com/apikey) | Gemini APIキー取得(テキスト生成) | 無料枠あり(モデルは変動するため下記「注意点」参照) |
| [Cloudflare](https://dash.cloudflare.com/sign-up) | Workers AIでの画像生成 | 無料枠 10,000 neurons/日(画像1枚≒50〜100 neurons目安) |
| [Buffer](https://buffer.com) | Xへの投稿予約・実行、実績取得 | Freeプラン: 3チャンネル、チャンネルあたり予約10件まで、API 3,000回/30日 |
| [Cloudinary](https://cloudinary.com/users/register/free) | 生成画像をBufferに渡す公開URL化 | 無料枠 25クレジット/月(画像数百KB程度なら十分すぎる余裕) |
| GitHub | 定期実行(Actions) | Publicリポジトリなら無料 |

## セットアップ手順

### 1. Gemini APIキー(テキスト生成)

[Google AI Studio](https://aistudio.google.com/apikey) でAPIキーを発行し、`.env`(`cp .env.example .env` で作成)の `GEMINI_API_KEY` に設定します。

### 2. Cloudflare Workers AI(画像生成)

1. [Cloudflareアカウント](https://dash.cloudflare.com/sign-up)を作成します(未取得の場合)。
2. ダッシュボード左メニューの **Workers AI** ページを開きます。
3. **Use REST API** を選択します。
4. **Create a Workers AI API Token** → 内容確認 → **Create API Token** → **Copy API Token**。
5. 同じ画面に表示されている **Account ID** も控えます。
6. `.env` の `CLOUDFLARE_API_TOKEN` と `CLOUDFLARE_ACCOUNT_ID` に設定します。

### 3. Buffer

1. [Buffer](https://buffer.com) にサインアップし、投稿したいXアカウントを接続します。
2. [Settings → API](https://publish.buffer.com/settings/api) でPersonal Access Tokenを発行し、`.env` の `BUFFER_API_KEY` に設定します。
3. 以下を実行して組織ID・チャンネルIDを確認します。

   ```bash
   pip install -r requirements.txt
   python scripts/find_buffer_ids.py
   ```

4. 表示された `BUFFER_ORGANIZATION_ID` と(Xチャンネルの)`BUFFER_CHANNEL_ID` を `.env` に追記します。

### 4. Cloudinary

[無料登録](https://cloudinary.com/users/register/free) 後、Dashboardに表示される Cloud Name / API Key / API Secret を `.env` に設定します。

### 5. ローカルで試す(dry-run)

実際にBufferへ予約を作成せず、Gemini・Cloudflare・Cloudinaryまでの生成/アップロードを確認できます。

```bash
python -m src.main --dry-run
```

ログは標準出力と `logs/run.log` の両方に出力されます。

### 6. GitHub Actionsへの登録

1. このプロジェクトをGitHubリポジトリにpushします(`.env` は `.gitignore` 済みなのでpushされません)。
2. リポジトリの **Settings → Secrets and variables → Actions** で、`.env.example` に列挙されているのと同じ名前で9つのSecretsを登録します。
3. **Actions** タブでワークフローを有効化すれば、以後は `post.yml` の cron に従って毎日自動実行されます。手動実行は同タブの "Run workflow" から可能です。

## カスタマイズ(`config.yaml`)

- `posting_times_jst`: 投稿時刻(JST)のリスト。増減・変更は自由です。
- `content.min_chars` / `max_chars` / `avoid_phrases`: 文字数とNGワード。
- `self_analysis.top_n_reference_posts`: 過去投稿のうち上位何件を参考データとして使うか。
- `gemini.text_model`: テキスト生成モデル名。
- `cloudflare.image_model`: 画像生成モデル名(既定は `@cf/black-forest-labs/flux-1-schnell`。他の選択肢は[モデル一覧](https://developers.cloudflare.com/workers-ai/models/)参照)。

## 運用上の注意点

- **Geminiのモデル名・無料枠は数か月単位で変わります。** 実行前に一度 [ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing) で対象モデルの「Free Tier」列が "Free of charge" になっているか確認し、必要なら `config.yaml` を更新してください。2026年8月時点、旧 `gemini-2.0-flash` は完全終了(shut down)しているため使用できません。
- Cloudflare Workers AIの無料枠(10,000 neurons/日)は今回の投稿量(画像3枚/日)であれば通常消費しきりません。
- Bufferの投稿実績(インプレッション等)は反映まで最大24時間ほど遅れることがあります。自己分析はその点を踏まえた設計にしています。
- Buffer Freeプランは「チャンネルあたり予約10件まで」という上限があります。本構成は1日1回・3件ずつ予約する運用なので通常は問題になりませんが、何日も実行せず放置すると予約が積み上がる可能性はあります。
- X自身の自動化ポリシー上、Bot運用は原則プロフィールへの明記(自動化アカウントである旨、運用者情報)が求められます。プロフィール文に一言添えておくことをおすすめします。
- 「1日10万インプレッション」を保証する仕組みではありません。フックの作り方や自己分析の反映はエンゲージメントを狙うための土台であり、実際の伸びはアカウントの実績やXのアルゴリズム側の要因にも左右されます。

## トラブルシューティング

- **GitHub Actionsの実行結果**: Actionsタブ → 該当のrun → `run-logs-*` アーティファクトをダウンロードすると、`logs/run.log` と(エラー時は)`errors/*.json` で詳細を確認できます。
- **`429 RESOURCE_EXHAUSTED` / `quota` エラー(Gemini)**: エラーメッセージ中の `limit: 0` は「一時的に使い切った」ではなく「そのモデルは今この無料枠で使えない」ことを意味します。モデル名が古くなっていないか [pricing](https://ai.google.dev/gemini-api/docs/pricing) で確認してください。
- **Cloudflare側のエラー**: `errors/*.json` に生のレスポンスが残るので、`success: false` の場合の `errors` フィールドを確認してください。
- **Buffer API呼び出しを直接試したい**: [GraphQL Explorer](https://developers.buffer.com/explorer.html) で認証済みのままクエリを試せます。スキーマ名の細部を確認したいときに便利です。
- **投稿が公開されない**: Buffer側でチャンネルの接続が切れていないか([publish.buffer.com](https://publish.buffer.com))、`errors/` 内のJSONにエラーメッセージが残っていないかを確認してください。
