# dtc-wifi-log

慶應SFCキャンパスのWiFi接続台数を10分おきに取得し、CSVへ追記する最小構成のコレクターです。  
[SFC Digital Twin API](https://api.dtc.wide.ad.jp/#tag/wifi) の `/crowd`（建物別 `apClientCount`）をデフォルトで利用します。

> `/wifi/clients/list` は SNMP 処理待ちのとき **503**（`SNMP observations in the merge window are still being processed.`）を返すことがあります。現状は `/crowd` を使うのが安定です。

夜間ベースラインとの差分算出は `src/compute_baseline.py` で行います（tokupro-bus 連携用）。

## セットアップ

1. `sfc-icar` org に空のリポジトリを作成（例: `sfc-wifi-collector`）
2. このディレクトリを push
3. 必要なら Repository Variables で上書き（省略時は DTC API デフォルト）
   - `WIFI_API_URL` … 既定 `https://api.dtc.wide.ad.jp/crowd`
   - `WIFI_API_FORMAT` … 既定 `dtc_crowd`

## ローカル実行

```bash
pip install -r requirements.txt
python3 src/fetch.py
```

ユニーク端末数（`/wifi/clients/list` の件数）を取る場合:

```bash
export WIFI_API_URL='https://api.dtc.wide.ad.jp/wifi/clients/list'
export WIFI_API_FORMAT='dtc_wifi_clients'
python3 src/fetch.py
```

## CSV 形式

### 収集用（長形式）`data/wifi_clients.csv`

ベースライン計算など処理向け。1タイムスタンプ×館で1行。

```csv
timestamp,scope,client_count
2026-09-22T12:10:00+09:00,all,1234
2026-09-22T12:10:00+09:00,kappa,120
2026-09-22T12:10:00+09:00,epsilon,98
```

- `scope=all` … 建物別 `apClientCount` の合計
- `scope=<buildingKey>` … 建物（κ館= `kappa` など）ごとの AP 接続数

### 閲覧用（横形式）`data/wifi_clients_wide.csv`

人間が見やすい版。1タイムスタンプで1行、列が `total` と各館。

```csv
timestamp,total,kappa,epsilon,iota,omicron,delta,tau,mu,omega,alpha,theta,lambda,sigma,lounge
2026-09-22T19:51:00+09:00,133,18,4,3,9,39,17,11,0,9,4,16,2,1
```

長形式から `python3 src/reshape_wide.py` で再生成できます（収集時にも自動更新）。

## ベースライン・差分

平日 02:00–05:00（JST）の中央値を日次ベースラインとし、`delta = client_count - baseline` を出力します。

```bash
python3 src/compute_baseline.py
# => data/wifi_clients_with_delta.csv
```

## GitHub Actions

`.github/workflows/collect.yml` が約10分おきに `fetch.py` を実行し、CSVをコミットします。

GitHub の `schedule` だけでは発火しないことがあるため、**一度起動したら PAT で次の実行を自分でキックする**方式にしています（`WORKFLOW_DISPATCH_TOKEN` secret）。初回だけ Actions から Run workflow、または:

```bash
gh workflow run "Collect WiFi clients" --repo Lazyturtle0852/dtc-wifi-log
```

## API 形式

| `WIFI_API_FORMAT` | エンドポイント | 内容 |
|---|---|---|
| `dtc_crowd`（既定） | `/crowd` | 建物別 `apClientCount` + 合計 |
| `dtc_wifi_clients` | `/wifi/clients/list` | ユニーク端末数（`clients` 件数） |
| `plain` / `conbu` | 任意 | プレーンテキスト数値 |
| `json_total` / `json_per_ap` | 任意 | 汎用 JSON |
| `mock` | なし | テスト用 |
