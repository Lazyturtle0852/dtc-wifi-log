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

`data/wifi_clients.csv`

```csv
timestamp,scope,client_count
2026-09-22T12:10:00+09:00,all,1234
2026-09-22T12:10:00+09:00,kappa,120
2026-09-22T12:10:00+09:00,epsilon,98
```

- `scope=all` … 建物別 `apClientCount` の合計
- `scope=<buildingKey>` … 建物（κ館= `kappa` など）ごとの AP 接続数

## ベースライン・差分

平日 02:00–05:00（JST）の中央値を日次ベースラインとし、`delta = client_count - baseline` を出力します。

```bash
python3 src/compute_baseline.py
# => data/wifi_clients_with_delta.csv
```

## GitHub Actions

`.github/workflows/collect.yml` が10分おきに `fetch.py` を実行し、CSVをコミットします。  
PCを閉じていてもデータが溜まります。

## API 形式

| `WIFI_API_FORMAT` | エンドポイント | 内容 |
|---|---|---|
| `dtc_crowd`（既定） | `/crowd` | 建物別 `apClientCount` + 合計 |
| `dtc_wifi_clients` | `/wifi/clients/list` | ユニーク端末数（`clients` 件数） |
| `plain` / `conbu` | 任意 | プレーンテキスト数値 |
| `json_total` / `json_per_ap` | 任意 | 汎用 JSON |
| `mock` | なし | テスト用 |
