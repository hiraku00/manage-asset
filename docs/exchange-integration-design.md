# 暗号資産取引所統合・ダッシュボード詳細設計書

- 文書版: 1.0
- 作成日: 2026-07-11
- 対象: 個人利用・ローカル Web アプリ
- 状態: 実装済み仕様（2026-07-12時点の画面・取得処理を反映）
- 関連文書: [crypto-asset-tracker-design.md](crypto-asset-tracker-design.md)、[dashboard-ux-redesign.md](dashboard-ux-redesign.md)

## 1. 設計の結論

現在の「複数EVMウォレットをDeBank HTMLから取り込む」アプリを、暗号資産取引所の残高も同じポートフォリオとして集計できる構造へ拡張する。

1. ETH、stETH、USDT等の実体資産を、ウォレット・DeFi・取引所を横断して合算する。
2. Binance、Bybit、bitFlyer等は資産名ではなく「保管場所」として扱う。
3. 取引所APIから取得した現在残高を、その取得時点のスナップショットとしてローカル保存する。
4. APIが提供しない過去残高を、日付指定で後から取得できたようには見せない。
5. 取引、注文、送金、出金、振替は実装しない。

```text
DeBank HTML ─ WalletConnector ─┐
Binance API ─ BinanceConnector ┤
Bybit API ─── BybitConnector ──┼─> 共通AssetPosition ─> JSONL ─> 統合画面
国内取引所API ─ Connector群 ──┘                   資産別 / 保管場所別 / 履歴
```

## 2. 目的

会計・売買アプリではなく、利用者が次を短時間で把握できる個人用ダッシュボードとする。

1. 全ウォレットと全取引所を合わせて、現在いくら保有しているか。
2. BTC、ETH、stETH、USDT等をそれぞれ合計で何単位持っているか。
3. 各資産はどのウォレット、DeFi、取引所に置かれているか。
4. 前回記録時から総額・数量・構成比がどう変わったか。
5. どの接続先が最新で、どこが古い・失敗・部分取得か。
6. 利用可能、注文拘束、Earn、借入等をどう評価したか。

## 3. スコープ

### 3.1 Phase 1に含める

- 複数ウォレットと複数取引所口座
- 利用者が更新ボタンを押した時だけAPI接続
- 現物・通常資産口座の現在残高
- 資産数量と評価額の横断合算
- 資産別、取引所別、口座別、保管場所別の内訳
- JSONLスナップショットと履歴
- USD/JPY表示切替、取引所内JPY残高
- 接続成功、部分成功、失敗、鮮度の表示
- 1 USD相当未満の標準非表示と表示切替
- API認証情報のローカル安全保管

### 3.2 Phase 1に含めない

- 注文、売買、送金、出金、内部振替
- 取引自動化、定期バッチ、常時監視
- 取引履歴からの取得原価、実現損益、税務計算
- 任意の過去日時の取引所残高再構築
- NFT、取引所Web3ウォレット、コピー取引
- 証拠金、先物、オプションの完全な純資産・リスク計算
- クラウド同期、外部公開、複数ユーザー

### 3.3 段階対応

| 段階 | 対象 |
|---|---|
| Phase 1 | Spot、UTA、国内通常残高、JPY現金 |
| Phase 2 | Funding、Simple Earn、ステーキング等の別口座・運用口座 |
| Phase 3 | マージン借入、先物・無期限契約の純資産 |
| Phase 4 | 取引履歴、取得原価、損益。別設計とする |

未対応口座を推測で総資産へ加えない。検出可能な場合は「取得範囲外」と明示する。

## 4. 対応取引所

2026-07-11時点の公式公開資料を基準に、初期対象を次とする。実装時に仕様を再確認し、コネクタのバージョンと確認日を記録する。

| 優先度 | 取引所 | 初期範囲 | 公式API・扱い |
|---:|---|---|---|
| P0 | Binance | Spot | `GET /api/v3/account`。`free + locked`を数量にする |
| P0 | Bybit | Unified Trading Account | `GET /v5/account/wallet-balance`。資産と借入を分離する |
| P0 | bitFlyer | 通常残高 | `GET /v1/me/getbalance`。`amount`と`available`を保存 |
| P0 | Coincheck | 通常、拘束、貸暗号資産、積立等 | `GET /api/accounts/balance`。`debt`は負債 |
| P0 | bitbank | 保有資産 | `GET /v1/user/assets`。Private REST API |
| P0 | GMOコイン | 資産残高 | `GET /private/v1/account/assets`。JPY換算値も照合可能 |
| P1 | BitTrade | 取引・凍結残高 | `GET /v1/account/accounts/{account-id}/balance` |
| P1 | Zaif | 実装時に現行Private APIを再検証 | 認証と残高レスポンス確認後に採用 |
| 調査 | SBI VCトレード、BITPOINT、OKJ等 | 個人口座残高APIの公式提供状況を確認 | 確認できなければ未対応。画面スクレイピングはしない |

公式資料:

- [Binance Spot REST API](https://developers.binance.com/en/docs/products/spot/rest-api)
- [Binance Account information](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#account-information-user_data)
- [Bybit V5 Get Wallet Balance](https://bybit-exchange.github.io/docs/v5/account/wallet-balance)
- [bitFlyer Lightning API](https://lightning.bitflyer.com/docs)
- [Coincheck Exchange API](https://coincheck.com/ja/documents/exchange/api)
- [bitbank Private REST API](https://github.com/bitbankinc/bitbank-api-docs/blob/master/rest-api_JP.md)
- [GMOコイン API](https://api.coin.z.com/docs/)
- [BitTrade API Reference](https://api-doc.bittrade.co.jp/)

「国内取引所対応」は、公式APIがあり、個人がキーを発行でき、残高を取得できる取引所をコネクタとして順次追加する意味とする。API非提供の取引所は将来のCSV手動取込を別機能として検討する。

## 5. 情報モデル

### 5.1 用語

| 用語 | 意味 | 例 |
|---|---|---|
| source | 外部データ取得元 | DeBank、Binance、bitFlyer |
| account | 残高を持つ口座単位 | Main Wallet、Binance Spot、Bybit UTA |
| location | 資産の保管・運用場所 | Wallet、Aave、Binance |
| asset | 合算対象となる実体資産 | BTC、ETH、stETH、USDT |
| position | 資産と保管場所の組合せ | Binance SpotのETH 2.5 |
| snapshot | 取得時点の残高集合 | 2026-07-11 13:15 UTC |
| run | 1回の更新操作・更新セッション | 全接続先を順に更新した単位 |

### 5.2 資産識別

シンボル文字列だけで同一資産と判断しない。

1. 法定通貨: `fiat:JPY`等のISO 4217
2. ネイティブ資産: 内部レジストリ。例 `coin:ETH`
3. EVMトークン: `chain_id + contract_address`
4. 取引所コード: 資産レジストリで正規資産へ対応付け
5. 不明: `source_asset:<exchange>:<symbol>`として別資産

ETH、WETH、stETHは別資産である。USDT等をチェーン横断でまとめる場合も、元のネットワーク別内訳を保持する。資産レジストリで明示的に確認できたものだけを合算する。

## 6. 共通データ構造

### 6.1 接続設定

秘密情報を含まない設定を `data/sources.json` に保存する。

```json
{
  "schema_version": 2,
  "sources": [{
    "source_id": "src_binance_main",
    "source_type": "exchange",
    "provider": "binance",
    "display_name": "Binance Main",
    "enabled": true,
    "credential_ref": "keychain:manage-asset/src_binance_main",
    "region": "jp",
    "account_scopes": ["spot"],
    "group": "取引所"
  }]
}
```

`credential_ref` は参照名だけであり、APIシークレットをJSONへ書かない。

### 6.2 共通スナップショット

```json
{
  "schema_version": 2,
  "record_type": "portfolio_snapshot",
  "snapshot_id": "snap_01...",
  "run_id": "run_01...",
  "source_id": "src_binance_main",
  "source_type": "exchange",
  "provider": "binance",
  "account_id": "acct_binance_spot",
  "account_name": "Binance Spot",
  "captured_at": "2026-07-11T13:15:50Z",
  "effective_at": "2026-07-11T13:15:49Z",
  "as_of_date": "2026-07-11",
  "status": "success",
  "valuation_currency": "USD",
  "positions": [],
  "totals": {
    "gross_asset_usd": "12500.00",
    "liability_usd": "0.00",
    "net_asset_usd": "12500.00",
    "fiat_usd": "0.00",
    "unpriced_count": 0
  },
  "connector": {"name": "binance", "version": "1.0.0"},
  "quality": {"coverage": "spot_only", "warnings": [], "raw_response_sha256": "..."}
}
```

`captured_at` は取得完了UTC時刻、`effective_at` はAPIに基準時刻があればその時刻とする。過去日を自由入力して現在残高へ付け替えない。

### 6.3 ポジション

```json
{
  "canonical_asset_id": "coin:ETH",
  "source_asset_code": "ETH",
  "symbol": "ETH",
  "asset_name": "Ethereum",
  "location_type": "exchange",
  "location_id": "binance",
  "location_name": "Binance",
  "account_type": "spot",
  "balance_type": "available",
  "quantity": "2.50000000",
  "available_quantity": "2.10000000",
  "locked_quantity": "0.40000000",
  "borrowed_quantity": "0",
  "net_quantity": "2.50000000",
  "price": "3200.00",
  "price_currency": "USD",
  "usd_value": "8000.00",
  "jpy_value": "1280000.00",
  "price_source": "binance:ETHUSDT",
  "price_at": "2026-07-11T13:15:49Z",
  "is_liability": false,
  "raw_fields": {}
}
```

数量・価格・評価額はJSONでは10進文字列、Python内部では `Decimal` とし、floatを使わない。

### 6.4 残高区分

| 区分 | 総資産への扱い |
|---|---|
| available | 加算 |
| locked / reserved / frozen | 加算。注文中でも所有資産 |
| earn / staked / lent | 加算。現物との二重計上を禁止 |
| reward_pending | API上確定済みの場合のみ加算 |
| borrowed / debt | 負債として控除 |
| collateral | 元資産を加算。別口座との重複を検証 |
| derivative_equity | Phase 3で純資産として扱う |

availableがtotalの内数か別構成要素かは取引所ごとに定義し、汎用式を無条件に当てない。

## 7. コネクタ設計

```python
class ExchangeConnector(Protocol):
    provider: str
    version: str
    def validate_config(self, config) -> ValidationResult: ...
    def test_connection(self, credential_ref) -> ConnectionResult: ...
    def fetch_accounts(self) -> list[ExternalAccount]: ...
    def fetch_balances(self, account) -> RawBalanceResult: ...
    def normalize(self, raw) -> list[AssetPosition]: ...
    def describe_coverage(self) -> Coverage: ...
```

署名、nonce、timestamp、recvWindow、APIホスト、レート制限は各コネクタ内に閉じ込める。UIと集計層へ取引所固有フィールドを漏らさない。監査用に秘密情報を除いた `raw_fields` とレスポンスハッシュを保持する。

### 7.1 取引所別ルール

- Binance: Spotに加えてSimple EarnのLDトークンを原資産へ正規化する。価格評価できない微小残高は明細に保持しつつ総額警告から除外する。
- Bybit: Unified Walletが権限で取得できない場合はAsset APIへフォールバックし、Funding・Unified・Earn（FlexibleSaving/OnChain）を保管場所別に取得する。
- bitFlyer: `amount`を総数量、`available`を利用可能数量として保存。
- Coincheck: 通常、reserved、lending、lend_in_use、lent、debt、tsumitateを別区分へ写像。debtは負債。
- bitbank: 公式フィールド定義に従い保有、利用可能、注文拘束を正規化。
- GMOコイン: `amount`を保有、`available`を利用可能とする。`conversionRate`はJPY評価の照合候補。
- BitTrade: `trade`と`frozen`を分け、同一通貨の所有残高として合算。

## 8. 認証情報とセキュリティ

### 8.1 保存

- macOS Keychainを第一選択とする。
- `sources.json`、JSONL、ログへAPIキー・Secret・Passphraseを書かない。
- Keychain非対応環境だけ環境変数を代替とする。
- `.env` は標準保存手段にしない。
- UIにはキー末尾4文字だけを表示し、Secretは再表示しない。
- 認証ヘッダー、生レスポンス、署名対象をログへ出さない。

### 8.2 権限

> 残高参照専用のAPIキーを使用してください。取引・送金・出金権限を有効にしないでください。

- 権限確認APIがあれば接続テストで検査する。
- Withdraw権限を検出した場合は保存を拒否する。
- 不要なTrade権限は警告する。
- IP制限は取引所から見える固定グローバルIPが必要であることを案内し、`127.0.0.1`を設定させない。

### 8.3 通信

- HTTPSのみ。接続先ホストはコネクタの許可リストで固定する。
- TLS証明書検証を無効化しない。
- 接続5秒、全体20秒でタイムアウト。
- 429は `Retry-After` を尊重し最大2回まで指数バックオフ。
- 時刻ずれは差分を表示するがOS時刻を自動変更しない。

## 9. 価格、換算、合計

### 9.1 表示と総額

- 内部基準評価はUSD、表示はUSD/JPY切替。
- JPY現金は `fiat:JPY` として保存する。
- ダッシュボードは `純資産`、`暗号資産小計`、`法定通貨小計`、`負債` を区別する。
- 初期値は法定通貨も総資産に含め、設定で「暗号資産のみ」を選べる。

### 9.2 価格優先順位

1. 同一取得時刻に近い公式評価値・換算レート
2. 保管取引所の対象ペア公開ティッカー
3. 共通価格プロバイダー
4. 価格不明

JPYは暗号資産のティッカーとして扱わず、取得時点のUSD/JPYレートを使う。したがって、JPYのUSD評価額は `JPY残高 ÷ USD/JPY` とし、Binanceの `USDTJPY` のような暗号資産価格APIへ問い合わせない。ダッシュボードのUSD合算と円併記を維持する。

資産別合算には原則同一の共通価格を使い、保管場所ごとの価格差で同じETHの評価が変わらないようにする。取引所評価値は照合用に保持する。価格不明は数量だけ表示し、推測で総額へ加えない。

```text
資産数量 = Σ 各ポジションのnet_quantity
暗号資産評価額 = Σ(net_quantity × 共通価格)
法定通貨評価額 = Σ(残高 × FXレート)
純資産 = 総資産評価額 - 負債評価額
```

負債がある場合は総資産と負債を隣接表示し、純資産だけで負債を隠さない。

### 9.3 二重計上防止

- SpotからEarnへ移動済みの元本を両方へ含めない。
- Bybit UTAのtotalEquityと通貨別評価を重ねない。
- DeBankの直持ちとDeFi預入資産を重ねない。
- 同じ取引所の複数APIは `external_account_id + asset + balance_type` で重複検査。
- 取引所Web3ウォレットはDeBank登録アドレスと重複し得るため初期対象外。

## 10. 取得と履歴

### 10.1 単一更新

1. 利用者が「残高を更新」を押す。
2. 認証情報と権限を確認する。
3. API残高を取得する。
4. 共通ポジションへ正規化する。
5. 公開価格を取得してUSD/JPY評価する。
6. API側総額、重複、負数、異常増減を検査する。
7. 保存前プレビューを表示する。
8. 利用者が確認後にJSONLへ追記する。

プレビューには前回差、資産件数、未評価数、取得範囲、警告を出す。認証失敗や不完全レスポンスを0円として保存しない。

### 10.2 すべて更新

- 登録接続先を最大2並列で取得し、同一取引所は直列にする。
- API接続先とDeBankウォレットは、画面の個別更新・一括更新から取得する。
- 取引所の一括更新は接続先ごとの非同期ジョブとして実行し、対象・完了・残り・成功・失敗・経過時間を表示する。
- 完了時は成功・失敗件数、処理時間、失敗した接続先とエラー内容を表示する。
- 一部失敗しても成功結果は保存できる。
- 失敗接続先を0円にせず、以前の値を使う場合は時刻と接続先を明示する。
- 全接続先が同時点でない場合、総額へ「取得時点が揃っていません」と表示する。

### 10.3 基準日

- API更新に基準日入力欄を出さない。
- `as_of_date` は `effective_at` をローカル日付へ変換し自動決定する。
- 過去画面は保存済みスナップショットだけを表示する。
- 記録がない日は「記録なし」とする。
- 比較対象が直前記録なら `前日比` ではなく `前回記録比` と表示する。
- 将来再構築する値は `reconstructed`、API実測は `observed` と区別する。

## 11. ローカルAPI

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/sources` | 秘密を除いた接続先一覧 |
| POST | `/api/sources` | 接続先追加 |
| PUT | `/api/sources/{source_id}` | 設定更新 |
| DELETE | `/api/sources/{source_id}` | 無効化。履歴は残す |
| POST | `/api/sources/{source_id}/credentials` | Keychainへ保存 |
| POST | `/api/sources/{source_id}/test` | 権限・疎通テスト。残高は保存しない |
| POST | `/api/sources/{source_id}/preview` | 現在残高取得とプレビュー |
| POST | `/api/sources/{source_id}/snapshots` | プレビューの確定保存 |
| POST | `/api/update-runs` | 一括更新開始 |
| GET | `/api/update-runs/{run_id}` | 更新結果 |
| GET | `/api/portfolio` | 最新統合ポートフォリオ |
| GET | `/api/portfolio/history` | 保存済み履歴 |
| GET | `/api/assets/{asset_id}` | 資産の保管場所別内訳 |

確定保存にはサーバー発行の短寿命 `preview_token` とレスポンスハッシュを要求し、ブラウザから数量・評価額を改変して保存できないようにする。

## 12. 保存と既存データ移行

```text
data/
  wallets.json                 既存
  sources.json                 秘密情報なしの接続設定
  snapshots.jsonl              既存schema v1
  portfolio-snapshots.jsonl    schema v2共通スナップショット
  runs.jsonl                   更新セッション
  asset-registry.json          資産対応表
  app-settings.json            表示設定
```

全ファイルは引き続きGit管理外とする。APIキーは `data/` にも保存しない。

1. 既存ファイルを変更せず保持する。
2. schema v1を共通ポジションへ変換する読取アダプタを追加する。
3. 新規取引所はschema v2へ保存する。
4. v1/v2混在で合算できることを確認する。
5. 起動時の破壊的自動移行はしない。

## 13. UI/UXとデジタル庁デザイン

2026-07-11時点のデジタル庁デザインシステムβ版 v2.16.0を参照し、単に青色を似せるのではなく、情報階層、状態、アクセシビリティ、コンポーネントを一貫させる。

- [デジタル庁デザインシステム](https://design.digital.go.jp/dads/)
- [カラー](https://design.digital.go.jp/dads/foundations/color/)
- [スタイルガイド](https://design.digital.go.jp/dads/guidance/style-guides/)
- [テーブル／データテーブル](https://design.digital.go.jp/dads/components/table/)

適用規則:

- プライマリーブルーは主要操作と選択状態に限定する。
- テキスト対背景4.5:1以上、UI境界3:1以上を確保する。
- 成功・警告・エラーは色、アイコン、ラベル、説明文を併用する。
- 明確なフォーカスリング、キーボード操作、主要操作44px以上を維持する。
- カードを過剰に並べず、見出し、余白、罫線で階層を作る。
- 数値は右揃え、桁区切り、単位、評価時刻を明示する。
- テーブルは列を潰さず、狭い画面では横スクロールまたはカード化する。

ナビゲーションは次とする。

```text
資産概要 | 保有資産 | 保管場所 | 履歴 | データ更新 | 設定
```

現行の「ウォレット」を「保管場所」へ拡張し、`すべて / ウォレット / 取引所 / DeFi`で絞る。設定・更新操作は資産概要から分離する。

## 14. ダッシュボード

```text
┌──────────────────────────────────────────────────────────────┐
│ 暗号資産ポートフォリオ          最終更新 7/11 20:15 [すべて更新] │
├──────────────────────────────────────────────────────────────┤
│ 純資産 $250,420 / ¥40,067,200                                 │
│ 前回記録比 +$3,210 (+1.30%)                                  │
│ 暗号資産 $245,000  法定通貨 $5,420  負債 $0                  │
│ 5/6 接続先更新済み  bitFlyerは2日前 [状態を確認]              │
├─────────────────────────────┬────────────────────────────────┤
│ 資産推移                     │ 資産配分                        │
│ 1M / 3M / ALL               │ 上位6資産 + その他             │
├─────────────────────────────┴────────────────────────────────┤
│ 保有資産                                                      │
│ ETH 72.50 $232,000  Wallet 65% / Binance 25% / Bybit 10%     │
├──────────────────────────────────────────────────────────────┤
│ 保管場所  すべて | ウォレット | 取引所 | DeFi                 │
└──────────────────────────────────────────────────────────────┘
```

総資産を画面最上部の主役とし、API設定、キー、内部ID、取得回IDを置かない。

### 14.1 資産配分

- 標準はトークン別。取引所別円グラフではない。
- ウォレット、DeFi、取引所の同一資産を合算する。
- 上位6資産とその他。1 USD未満は注記へまとめる。
- ドーナツはデスクトップ最低280px。
- 凡例は `資産 / 数量 / 評価額 / 比率` を独立行で折返し可能にし、狭い列へ押し込まない。
- 総資産と内訳に差があれば差額と原因候補を表示する。

### 14.2 保有資産一覧

| 列 | 内容 |
|---|---|
| 資産 | シンボルと名称 |
| 合計数量 | 全保管場所の純数量 |
| 参考価格 | 共通価格と時刻 |
| 評価額 | USD/JPY切替 |
| 比率 | 純資産比とバー |
| 保管場所 | 上位3件と他N件 |
| 状態 | 価格不明、負債、古いデータ等 |

資産行から保管場所別の足し算を確認できる。

```text
ETH 合計 72.500000 ETH / $232,000
  Main Wallet       50.000000   $160,000   69.0%
  Binance Spot      15.000000    $48,000   20.7%
  Bybit UTA          7.500000    $24,000   10.3%
```

### 14.3 保管場所一覧

| 保管場所 | 種別 | 評価額 | 比率 | 最終取得 | 状態 |
|---|---|---:|---:|---|---|
| Main Wallet | Wallet | $180,000 | 71.9% | 10分前 | 最新 |
| Binance Main | Exchange | $48,000 | 19.2% | 8分前 | 最新 |
| Bybit UTA | Exchange | $22,420 | 9.0% | 8分前 | 一部未取得 |

各行に比率バーを表示し、選択すると独立した詳細画面へ進む。

## 15. 取引所詳細と設定

```text
保管場所 > 取引所 > Binance Main

Binance Main                         [残高を更新] [接続設定]
Spot / 最終取得 7/11 20:15 / API正常
評価額 $48,000   全体比 19.2%   取得範囲 Spotのみ

資産内訳 | 口座 | 取得履歴 | データ品質
資産   総数量      利用可能      注文拘束      評価額
ETH    15.0000     14.5000       0.5000       $48,000
```

- APIキー設定を詳細データへ常時展開しない。
- 未対応のEarn等があれば「評価額に含まれない可能性」を表示する。
- API側総額と本アプリ評価の差をデータ品質で確認できる。
- エラーは利用者が取るべき行動を日本語で示す。

取引所追加手順:

1. 設定 > 保管場所 > 取引所を追加。
2. 対応取引所を名称付き一覧から選択。
3. 取得対象とAPIキー作成手順を確認。
4. Key、Secret、必要時Passphraseを入力。
5. 接続と権限を確認。
6. 取得範囲と不要権限の警告を確認。
7. 表示名を設定して保存。
8. 初回残高をプレビューし確定。

未対応取引所にはキー入力欄を出さない。キー削除、接続先無効化、履歴完全削除を別操作にする。Secretは上書き入力のみで現在値を表示しない。

## 16. データ更新画面

| 接続先 | 方式 | 最終取得 | 状態 | 操作 |
|---|---|---|---|---|
| Main Wallet | DeBank HTML | 10分前 | 最新 | HTMLを取り込む |
| Binance Main | API | 8分前 | 最新 | 更新 |
| Bybit UTA | API | 8分前 | 一部未取得 | 更新 |
| bitFlyer | API | 2日前 | 認証エラー | 再試行 |

- 一括更新中は進行中、成功、要確認、失敗を行単位で表示する。
- 失敗しても成功済みデータを失わない。
- プレビューに前回差、資産数、未評価数、取得範囲を出す。
- 終了後の主操作は「ダッシュボードへ戻る」。

## 17. エラー、部分成功、鮮度

| 状態 | 意味 | 総額への扱い |
|---|---|---|
| success | 想定範囲を取得 | 最新値 |
| partial | 一部口座・価格が未取得 | 取得分と警告 |
| stale | 更新失敗、以前の値のみ | 以前の値と時刻強調 |
| auth_error | キー・署名・権限エラー | 以前の値。再設定案内 |
| rate_limited | レート制限 | 再試行後、以前の値 |
| unavailable | 障害・通信失敗 | 以前の値 |
| never_fetched | 未取得 | 総額に含めない |

- 24時間以上: 注意、7日以上: 警告。
- 最古と最新の差が24時間以上: 取得時点不一致を表示。
- 履歴グラフは原則として当時保存した評価額を使う。

異常検知:

- 前回比50%以上
- 資産件数が前回の半分以下
- API側総額との評価差が1 USD以上かつ0.1%以上
- 負数、NaN、桁上限超過
- 価格時刻が残高より24時間以上古い
- 同一ポジションキーの重複

異常は自動破棄せずプレビューで理由を示す。残高未取得を0円として保存しない。

## 18. アクセシビリティとレスポンシブ

- 入力には可視ラベルと補足を付ける。
- エラーは入力付近とページ上部サマリーに示す。
- フォーカス順と視覚順を一致させる。
- `aria-live`で更新完了・失敗を通知する。
- チャートと同じ情報を表でも提供する。
- 色だけで増減、状態、資産を識別させない。
- 960px以上は推移60%、配分40%。配分が狭ければドーナツと凡例を縦積み。
- 959px以下は主要セクションを1列化。
- テーブルは重要列を維持し横スクロール可能にする。
- 200%ズームで一文字ずつ縦折返しになるレイアウトを禁止する。

## 19. 非機能要件

| 項目 | 要件 |
|---|---|
| 実行 | `127.0.0.1`のみ |
| 初期表示 | 最新1000スナップショットで2秒以内を目標 |
| API更新 | 1接続先20秒。UIをブロックしない |
| 並列数 | 最大2。同一プロバイダーは直列 |
| 数値 | `Decimal`、10進文字列保存 |
| 永続化 | 追記型JSONL、UTF-8 |
| 排他 | 同一接続先の同時更新を拒否 |
| 監査 | run_id、connector version、ハッシュ、警告 |
| ログ | 秘密を出さずエラーコードと相関IDのみ |

## 20. テストと受入条件

### 20.1 コネクタ契約テスト

- 0残高を除外する。
- availableとlockedを正しく扱う。
- 負債を資産へ加算しない。
- 数値をfloatへ変換しない。
- 未知資産を落とさない。
- エラーを0残高として扱わない。
- 認証ヘッダーをログへ出さない。

### 20.2 集計例

```text
Wallet: ETH 10
Lido: stETH 5
Binance: ETH free 2 + locked 1
Bybit: ETH wallet 4, borrowed 1

期待値:
ETH純数量 = 10 + 3 + (4 - 1) = 16
stETH数量 = 5
Binance、Bybit、Lidoは保管場所であり資産行にならない
```

### 20.3 UI受入条件

- 起動直後に統合純資産、前回記録比、主要資産、更新状態が分かる。
- ETH等がウォレットと取引所を横断して合算される。
- 資産行から保管場所別の数量を検算できる。
- BinanceやAaveを資産名にしない。
- キー設定がダッシュボードを占有しない。
- Secretが画面再表示、ログ、JSONL、Git差分に出ない。
- 更新失敗口座が0円にならない。
- 存在しない過去残高を表示しない。
- 凡例が切れず、一文字単位の縦折返しにならない。
- キーボードのみで追加、更新、詳細確認ができる。

## 21. 実装順序

1. schema v2、Decimal、資産レジストリ、schema v1読取アダプタ。
2. 統合集計、負債、二重計上、照合テスト。
3. Keychain credential store。
4. Binance Spot、Bybit UTA、bitFlyerコネクタ。
5. プレビュー、確定保存、一括更新。
6. Coincheck、bitbank、GMOコイン、BitTrade。
7. ナビゲーション、統合ダッシュボード、資産詳細、保管場所一覧。
8. 取引所詳細、更新、設定。
9. DADS準拠、レスポンシブ、アクセシビリティの実機確認。
10. Earn、Funding、Margin、Derivativesは個別設計後に拡張。

## 22. 実装時の既定値

- 初期対応: Binance Spot、Bybit UTA、bitFlyer、Coincheck、bitbank、GMOコイン
- 総資産: 暗号資産と取引所内法定通貨を含む純資産。小計と負債を併記
- 評価: USD内部基準。取得時点のUSD/JPYレートをスナップショットへ保存し、USD/JPYを併記
- 更新: 利用者操作時のみ
- 過去値: 保存済みスナップショットのみ
- 秘密情報: macOS Keychain
- 権限: 読取専用、出金権限禁止
- 保存: schema v2 JSONL、schema v1読取互換
- UI: DADS v2系を踏襲し、資産把握を設定より優先

実装前に利用者判断が必要なのは、実際に使う取引所の優先順位と、取引所内JPYを総資産へ含める既定値を変えたい場合だけとする。

## 23. Phase 1完了条件

- 海外2社・国内1社以上で読取専用接続が成功する。
- APIキーがファイル、ログ、Git管理対象へ保存されない。
- ウォレットと取引所の同一資産数量が正しく合算される。
- available、locked、負債を区別できる。
- 失敗、部分取得、古いデータを完全な最新値として見せない。
- 総資産、資産内訳、保管場所内訳の照合差が許容内である。
- 保存済み履歴だけで推移を描く。
- 狭い画面と200%ズームで情報が欠落しない。
- DADSに基づくコントラスト、フォーカス、状態、データテーブル要件を満たす。
