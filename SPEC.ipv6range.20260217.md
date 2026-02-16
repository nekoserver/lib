# 仕様書: ipv6range.shtml

**バージョン:** 1.0
**作成日:** 2026-02-17
**対象ファイル:** `ipv6range.shtml`

---

## 1. 概要

Apache SSI（Server Side Includes）を用いて、HTTPリクエストの `X-Forwarded-For` ヘッダからクライアントのIPアドレスを取得し、IPv6の場合は `/64` CIDRを算出して出力するスクリプト。

主な用途：リバースプロキシ配下でのIPアドレス・レンジ確認、デバッグ表示。

---

## 2. 実行環境の前提条件

### 2.1 Webサーバー
- **Apache HTTP Server** が必須
- `mod_include`（SSI）が有効であること
- `.shtml` 拡張子に対してSSIが有効化されていること（`Options +Includes` または `XBitHack` 設定）
- `<!--#exec cmd="..." -->` ディレクティブが許可されていること（`Options +ExecCGI` または `IncludesNOEXEC` でないこと）

### 2.2 実行環境の制約（重要）

#### 環境変数スコープの制約
SSIの `exec cmd` から起動されるシェルコマンドでは、`os.environ` / `$ENV_VAR` によるApache環境変数の直接参照が**できない場合がある**。
→ 解決策：`printenv` コマンドの出力をパイプ経由でstdinに渡し、Python側でパースする。

```
printenv | python3 -c "..."
```

#### クォートの入れ子制約
SSIの `cmd` 属性値はダブルクォートで囲まれるため、Python コード内でダブルクォートやシングルクォートを使うと構文エラーになる。
→ 解決策：Pythonコード全体をbase64エンコードし、`exec(base64.b64decode(...).decode())` で実行する。

```html
<!--#exec cmd="printenv | python3 -c \"import base64,sys; exec(base64.b64decode('BASE64_HERE').decode())\"" -->
```

### 2.3 依存コマンド・ライブラリ
| 依存物 | 用途 |
|---|---|
| `printenv` | Apache環境変数の一覧出力 |
| `python3` | IPアドレス処理スクリプトの実行 |
| `ipaddress` (Python標準ライブラリ) | IPアドレスのパース・バージョン判定・CIDR算出 |

---

## 3. 機能仕様

### 3.1 入力

| 項目 | 内容 |
|---|---|
| 入力元 | `printenv` の出力（stdin経由） |
| 対象環境変数 | `HTTP_X_FORWARDED_FOR` |
| 複数IP | カンマ区切りの場合は**先頭のIPのみ**使用 |
| 前後空白 | `strip()` で除去 |

### 3.2 出力

常に2行出力する。

#### 1行目（デバッグ行）
```
HTTP_X_FORWARDED_FOR=<生の値>
```
- `HTTP_X_FORWARDED_FOR` が未設定の場合は空文字：`HTTP_X_FORWARDED_FOR=`

#### 2行目（IP/CIDR行）

| 条件 | 出力形式 | 例 |
|---|---|---|
| IPv6アドレス | `<IPアドレス>,</64 CIDR>` | `2001:db8:1234:5678::1,2001:db8:1234:5678::/64` |
| IPv4アドレス | `<IPアドレス>` | `203.0.113.1` |
| 未設定・パース失敗 | `N/A` | `N/A` |

### 3.3 CIDR算出ロジック

- IPv6アドレスに `/64` を付与し `ipaddress.ip_network(..., strict=False)` で算出
- `strict=False` により、ホスト部ビットが立っていても正しくネットワークアドレスに丸める
- 先頭64ビットをネットワーク部として固定（理由：IPv6のSLAAC/DHCPv6環境では `/64` がサブネット単位として一般的なため）

---

## 4. 処理フロー

```
[Apache SSI] <!--#exec cmd="..."-->
    ↓
printenv（全環境変数を出力）
    ↓ stdin
python3（base64デコード→exec）
    ↓
HTTP_X_FORWARDED_FOR を取得（なければ空文字）
    ↓
先頭IPを抽出・strip
    ↓
1行目: "HTTP_X_FORWARDED_FOR=<raw>" を出力
    ↓
ipaddress.ip_address() でパース
    ├─ IPv6 → "<ip>,<ip_network /64>" を出力
    ├─ IPv4 → "<ip>" を出力
    └─ 例外（空・不正） → "N/A" を出力
```

---

## 5. 今後の拡張指針

### 5.1 対応CIDRの変更・選択
現在は `/64` 固定。用途によって変更・可変化が考えられる。
- `/48`（ISPのPrefixレベル）
- `/56`（一般的なホームルーター割当）
- クエリパラメータやSSI変数で動的に指定する方式

### 5.2 複数IPの扱い
現在は `X-Forwarded-For` の先頭IPのみ使用。
プロキシ段数を考慮して末尾（最初のプロキシが付与したIP）を使う方式への変更も検討余地あり。

### 5.3 出力フォーマットの変更
現在はプレーンテキスト2行。
HTML埋め込み用途では `<span>` タグや JSON形式への変更も考えられる。

### 5.4 `REMOTE_ADDR` へのフォールバック
`HTTP_X_FORWARDED_FOR` が未設定の場合に `REMOTE_ADDR` を代替として使う拡張。
直接接続（プロキシなし）環境でも動作するようになる。

### 5.5 セキュリティ考慮
- `X-Forwarded-For` はクライアントが偽装可能なヘッダであるため、信頼できるプロキシ経由かどうかの検証は呼び出し側の責任とする
- `exec cmd` は強力な機能のため、本ファイルへのアクセス制御（Basic認証・IPフィルタ等）を推奨
