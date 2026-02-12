# MusicDeLoc

Apple Music のアーティスト名を MusicBrainz 正式名に変換するツール

## 概要

Apple Music（日本のApple ID）では、海外アーティスト名がサーバー側でカタカナにローカライズされて配信されます（例: Yes → イエス、Queen → クイーン）。このツールは、MusicBrainz の正式名と照合し、英語の正式名に変換します。

日本人アーティスト（例: 木村カエラ、宇多田ヒカル）は MusicBrainz でも日本語名が正式名のため、そのまま保持されます。

## 動作環境

- macOS（Music アプリがインストールされていること）
- Python 3.9+
- 追加パッケージ不要（標準ライブラリのみ）
- LLM変換を使う場合: [Gemini CLI](https://github.com/google-gemini/gemini-cli)（推奨）または [Claude Code](https://docs.anthropic.com/en/docs/claude-code)

## インストール

```bash
git clone https://github.com/your/musicdeloc.git
cd musicdeloc
```

## 使い方

### 基本的な使い方

```bash
# デフォルト動作（データ準備）
python3 musicdeloc.py

# LLM変換を使う場合
python3 musicdeloc.py --llm gemini

# 変換を適用
python3 musicdeloc.py apply
```

デフォルト動作では以下が実行されます：
1. Music アプリからアーティスト名をスキャン
2. MusicBrainz で正式名を照合
3. 見つからないアーティストをエクスポート
4. LLM変換とインポート（`--llm` 指定時のみ）

変換の適用は `apply` コマンドで別途実行します。

### グローバルオプション

```bash
-y, --yes              確認プロンプトをスキップ
--llm {claude,gemini}  LLM CLI でカタカナ名を英語正式名に変換
```

### コマンド

#### スキャン

```bash
# アーティスト名をスキャン
python3 musicdeloc.py scan

# 全アーティストを表示（-a, --all）
python3 musicdeloc.py scan --all
```

#### 照合

```bash
# 新規アーティストを MusicBrainz で照合
python3 musicdeloc.py fetch

# 特定のアーティストのみ
python3 musicdeloc.py fetch --artist "イエス"

# 非インタラクティブモード
python3 musicdeloc.py fetch --non-interactive
```

#### レビュー

```bash
# 変換候補を確認
python3 musicdeloc.py review
```

#### 適用

```bash
# 変換を適用
python3 musicdeloc.py apply

# 確認をスキップして適用
python3 musicdeloc.py apply -y

# dry-run（実際には変更しない）
python3 musicdeloc.py apply --dry-run
```

#### 復元

```bash
# バックアップから復元
python3 musicdeloc.py restore ~/.musicdeloc/backups/backup_20240115_103000.json
```

#### キャッシュ管理

```bash
# キャッシュ一覧
python3 musicdeloc.py cache list

# キャッシュをクリア
python3 musicdeloc.py cache clear

# 特定のエントリを削除
python3 musicdeloc.py cache remove "イエス"
```

#### 見つからないアーティストのエクスポート

```bash
# TSV出力（デフォルト: ~/.musicdeloc/not_found.tsv）
python3 musicdeloc.py export-not-found

# 出力先を指定（-o, --output）
python3 musicdeloc.py export-not-found -o ~/Desktop/not_found.tsv

# LLM変換付き（--mappings で出力先指定、--batch-size でバッチサイズ指定可）
python3 musicdeloc.py export-not-found --llm gemini
```

#### マッピングのインポート

```bash
# TSVファイルからマッピングをインポート
python3 musicdeloc.py import-mappings ~/.musicdeloc/mappings.tsv
```

## 実行例

```
$ python3 musicdeloc.py --llm gemini

Music アプリをスキャン中...
→ アーティスト名を 150 件検出（うち新規 5 件）

MusicBrainz で照合中...
  [1/5] 木村カエラ → 木村カエラ（一致）→ スキップ
  [2/5] イエス → Yes ✓
  [3/5] クイーン → Queen ✓
  [4/5] 宇多田ヒカル → 宇多田ヒカル（一致）→ スキップ
  [5/5] ザ・ビートルズ → 見つかりません

→ 見つからないアーティスト: not_found.tsv
LLM で変換中...
→ マッピングをインポートしました

→ 変換候補 4 件。適用: python3 musicdeloc.py apply -y

$ python3 musicdeloc.py apply

変換候補:
  イエス → Yes (12 トラック)
  クイーン → Queen (24 トラック)
  ザ・ビートルズ → The Beatles (48 トラック)

スキップ（正式名と一致）: 2 件

3 アーティスト、84 トラックを更新します。
適用しますか？ [Y/n]: y

バックアップ: /Users/xxx/.musicdeloc/backups/backup_20240115_103000.json

適用中...
  イエス → Yes (12 トラック) ✓
  クイーン → Queen (24 トラック) ✓
  ザ・ビートルズ → The Beatles (48 トラック) ✓

完了: 3 件適用、0 件失敗
```

## ファイル構成

```
~/.musicdeloc/
├── cache.json                          # アーティスト照合結果のキャッシュ
├── not_found.tsv                       # 見つからなかったアーティスト
├── mappings.tsv                        # LLM変換結果
└── backups/
    ├── backup_YYYYMMDD_HHMMSS.json     # 変換前のバックアップ
    └── failed.json                     # 失敗リスト
```

## 注意事項

- 初回実行時、Music アプリへのオートメーション許可が必要です
- MusicBrainz API のレートリミット（1秒/リクエスト）を遵守しています
- 変換前に必ずバックアップが作成されます
- iCloud ミュージックライブラリが有効な場合、変更は他のデバイスにも同期されます

## ライセンス

MIT
