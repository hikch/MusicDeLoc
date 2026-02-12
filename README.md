# MusicDeLoc

Apple Music の日本語アーティスト名を MusicBrainz 正式名に変換するツール

## 概要

Apple Music（日本のApple ID）では、アーティスト名がサーバー側で日本語にローカライズされて配信されます（例: Yes → イエス、Queen → クイーン）。このツールは、MusicBrainz の正式名と照合し、異なる場合のみ英語名に変換します。

日本人アーティスト（例: 木村カエラ、宇多田ヒカル）は MusicBrainz でも日本語名が正式名のため、自動的にスキップされます。

## 動作環境

- macOS（Music アプリがインストールされていること）
- Python 3.9+
- 追加パッケージ不要（標準ライブラリのみ）

## インストール

```bash
git clone https://github.com/your/musicdeloc.git
cd musicdeloc
```

## 使い方

### 基本的な使い方（対話モード）

```bash
python musicdeloc.py
```

これにより以下が実行されます：
1. Music アプリから日本語アーティスト名をスキャン
2. MusicBrainz で正式名を照合
3. 変換候補を確認して適用

### コマンド

#### スキャン

```bash
# 日本語アーティスト名を検出
python musicdeloc.py scan

# 全アーティストを表示
python musicdeloc.py scan --all
```

#### 照合

```bash
# 新規アーティストを MusicBrainz で照合
python musicdeloc.py fetch

# 特定のアーティストのみ
python musicdeloc.py fetch --artist "イエス"

# 非インタラクティブモード
python musicdeloc.py fetch --non-interactive
```

#### レビュー

```bash
# 変換候補を確認
python musicdeloc.py review
```

#### 適用

```bash
# 変換を適用
python musicdeloc.py apply

# dry-run（実際には変更しない）
python musicdeloc.py apply --dry-run
```

#### 復元

```bash
# バックアップから復元
python musicdeloc.py restore ~/.musicdeloc/backups/backup_20240115_103000.json
```

#### キャッシュ管理

```bash
# キャッシュ一覧
python musicdeloc.py cache list

# キャッシュをクリア
python musicdeloc.py cache clear

# 特定のエントリを削除
python musicdeloc.py cache remove "イエス"
```

## 実行例

```
$ python musicdeloc.py

Music アプリをスキャン中...
→ 日本語アーティスト名を 150 件検出（うち新規 5 件）

MusicBrainz で照合中...
  [1/5] 木村カエラ → 木村カエラ（一致）→ スキップ
  [2/5] イエス → Yes ✓
  [3/5] クイーン → Queen ✓
  [4/5] 宇多田ヒカル → 宇多田ヒカル（一致）→ スキップ
  [5/5] ザ・ビートルズ → The Beatles ✓

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
└── backups/
    └── backup_YYYYMMDD_HHMMSS.json     # 変換前のバックアップ
```

## 注意事項

- 初回実行時、Music アプリへのオートメーション許可が必要です
- MusicBrainz API のレートリミット（1秒/リクエスト）を遵守しています
- 変換前に必ずバックアップが作成されます
- iCloud ミュージックライブラリが有効な場合、変更は他のデバイスにも同期されます

## ライセンス

MIT
