#!/usr/bin/env python3
"""MusicDeLoc - Apple Music アーティスト名 → MusicBrainz 正式名 変換ツール"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from apple_music import AppleMusicClient
from cache import CacheManager

# ユーザーデータディレクトリ
DATA_DIR = Path.home() / ".musicdeloc"
from exceptions import (
    AppleMusicError,
    AppleMusicNotRunningError,
    MusicBrainzError,
    ArtistNotFoundError,
)
from musicbrainz import MusicBrainzClient


class Spinner:
    """スピナー表示クラス（別スレッドでアニメーション）"""

    CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, message: str = "処理中..."):
        self._message = message
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """スピナーを開始"""
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self) -> None:
        """スピナーアニメーション"""
        idx = 0
        while self._running:
            char = self.CHARS[idx % len(self.CHARS)]
            sys.stdout.write(f"\r{char} {self._message}")
            sys.stdout.flush()
            idx += 1
            time.sleep(0.1)

    def stop(self, final_message: Optional[str] = None) -> None:
        """スピナーを停止"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=0.5)
        # 行をクリアして最終メッセージを表示
        sys.stdout.write("\r" + " " * (len(self._message) + 3) + "\r")
        if final_message:
            print(final_message)
        sys.stdout.flush()

    def __enter__(self) -> "Spinner":
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.stop()


@dataclass
class ConversionCandidate:
    """変換候補"""

    library_name: str
    musicbrainz_name: str
    sort_name: str
    mbid: Optional[str]
    track_count: int
    action: str  # "convert" or "skip"


class MusicDeLoc:
    """MusicDeLoc メインアプリケーション"""

    def __init__(
        self, cache_path: Optional[Path] = None, backup_dir: Optional[Path] = None
    ):
        self.music = AppleMusicClient()
        self.musicbrainz = MusicBrainzClient()
        self.cache = CacheManager(cache_path)
        self.backup_dir = backup_dir or (Path.home() / ".musicdeloc" / "backups")

    def scan(self, show_all: bool = False) -> list[tuple[str, int]]:
        """全アーティスト名をスキャン

        Returns:
            [(アーティスト名, トラック数), ...] トラック数順
        """
        spinner = Spinner("Music アプリをスキャン中...")
        spinner.start()

        try:
            artists = self.music.get_unique_artists()
            track_counts = self.music.get_artist_track_count()
        except AppleMusicNotRunningError:
            spinner.stop()
            print("エラー: Music アプリが起動していません。起動してから再実行してください。")
            sys.exit(1)
        except AppleMusicError as e:
            spinner.stop()
            print(f"エラー: {e}")
            sys.exit(1)

        # トラック数でソート（全アーティスト対象）
        result = [(a, track_counts.get(a, 0)) for a in artists]
        result.sort(key=lambda x: x[1], reverse=True)

        # キャッシュ状態を表示
        cached_count = sum(1 for a, _ in result if a in self.cache)
        new_count = len(result) - cached_count

        spinner.stop(f"→ アーティスト名を {len(result)} 件検出（うち新規 {new_count} 件）\n")

        if show_all:
            print("アーティスト一覧:")
            for artist, count in result:
                status = "✓" if artist in self.cache else " "
                print(f"  [{status}] {artist} ({count} トラック)")
            print()

        return result

    def fetch(
        self, artists: Optional[list[str]] = None, interactive: bool = True
    ) -> list[ConversionCandidate]:
        """MusicBrainz から正式名を取得

        Args:
            artists: 処理するアーティスト名のリスト（None の場合は新規のみ）
            interactive: インタラクティブモード

        Returns:
            変換候補のリスト
        """
        if artists is None:
            # スキャンして新規のみ取得
            all_artists = self.scan()
            artists = [a for a, _ in all_artists if a not in self.cache]

        if not artists:
            print("新規のアーティストはありません。")
            return []

        track_counts = self.music.get_artist_track_count()
        candidates = []

        print(f"\nMusicBrainz で照合中...")
        for i, artist in enumerate(artists, 1):
            print(f"  [{i}/{len(artists)}] {artist}", end=" → ", flush=True)

            try:
                result = self.musicbrainz.get_official_name(artist)
            except MusicBrainzError as e:
                print(f"エラー: {e}")
                continue

            if result is None:
                print("(見つかりません)")
                if interactive:
                    manual = self._prompt_manual_input(artist)
                    if manual:
                        self.cache.set_manual(artist, manual)
                        candidates.append(
                            ConversionCandidate(
                                library_name=artist,
                                musicbrainz_name=manual,
                                sort_name=manual,
                                mbid=None,
                                track_count=track_counts.get(artist, 0),
                                action="convert",
                            )
                        )
                    else:
                        self.cache.set_not_found(artist)
                else:
                    self.cache.set_not_found(artist)
                continue

            mb_name, sort_name, mbid = result

            if self.musicbrainz.should_convert(artist, mb_name):
                print(f"{mb_name} ✓")
                self.cache.set_convert(artist, mb_name, mbid)
                candidates.append(
                    ConversionCandidate(
                        library_name=artist,
                        musicbrainz_name=mb_name,
                        sort_name=sort_name,
                        mbid=mbid,
                        track_count=track_counts.get(artist, 0),
                        action="convert",
                    )
                )
            else:
                print(f"{mb_name}（一致）→ スキップ")
                self.cache.set_skip(artist, mb_name, mbid)

        return candidates

    def _prompt_manual_input(self, artist: str) -> Optional[str]:
        """手動入力を促す"""
        try:
            response = input(f"    '{artist}' の英語名を入力（スキップは Enter）: ").strip()
            return response if response else None
        except (EOFError, KeyboardInterrupt):
            print()
            return None

    def review(self) -> list[ConversionCandidate]:
        """変換候補をレビュー"""
        conversions = self.cache.get_conversions()
        if not conversions:
            print("変換候補がありません。")
            return []

        track_counts = self.music.get_artist_track_count()
        candidates = []

        print("\n変換候補:")
        for library_name, mb_name in conversions.items():
            count = track_counts.get(library_name, 0)
            print(f"  {library_name} → {mb_name} ({count} トラック)")
            candidates.append(
                ConversionCandidate(
                    library_name=library_name,
                    musicbrainz_name=mb_name,
                    sort_name=mb_name,
                    mbid=self.cache.get(library_name).mbid if self.cache.get(library_name) else None,
                    track_count=count,
                    action="convert",
                )
            )

        skipped = self.cache.get_skipped()
        if skipped:
            print(f"\nスキップ（正式名と一致）: {len(skipped)} 件")

        not_found = self.cache.get_not_found()
        if not_found:
            print(f"未解決: {len(not_found)} 件")
            for artist in not_found:
                print(f"  - {artist}")

        return candidates

    def apply(
        self,
        candidates: Optional[list[ConversionCandidate]] = None,
        dry_run: bool = False,
        auto_confirm: bool = False,
    ) -> dict:
        """変換を適用

        Args:
            candidates: 変換候補リスト
            dry_run: True の場合は実際には変更しない
            auto_confirm: True の場合は確認プロンプトをスキップ

        Returns:
            {"applied": 件数, "skipped": 件数, "failed": 件数, "backup": パス}
        """
        if candidates is None:
            candidates = self.review()

        if not candidates:
            return {"applied": 0, "skipped": 0, "failed": 0, "backup": None}

        # 確認プロンプト
        total_tracks = sum(c.track_count for c in candidates)
        print(f"\n{len(candidates)} アーティスト、{total_tracks} トラックを更新します。")

        if dry_run:
            print("（dry-run モード: 実際には変更しません）")
            return {"applied": 0, "skipped": len(candidates), "failed": 0, "backup": None}

        if not auto_confirm:
            try:
                response = input("適用しますか？ [Y/n]: ").strip().lower()
                if response and response != "y":
                    print("キャンセルしました。")
                    return {"applied": 0, "skipped": len(candidates), "failed": 0, "backup": None}
            except (EOFError, KeyboardInterrupt):
                print("\nキャンセルしました。")
                return {"applied": 0, "skipped": len(candidates), "failed": 0, "backup": None}

        # バックアップ作成
        backup_path = self._create_backup(candidates)
        print(f"バックアップ: {backup_path}")

        # 適用
        applied = 0
        failed = 0
        failed_artists: list[dict] = []

        print("\n適用中...")
        for c in candidates:
            print(f"  {c.library_name} → {c.musicbrainz_name}", end=" ", flush=True)
            try:
                count = self.music.batch_update_by_artist(
                    c.library_name, c.musicbrainz_name
                )
                print(f"({count} トラック) ✓")
                applied += 1
            except AppleMusicError as e:
                print(f"エラー: {e}")
                failed += 1
                failed_artists.append({
                    "library_name": c.library_name,
                    "musicbrainz_name": c.musicbrainz_name,
                    "error": str(e),
                })

        print(f"\n完了: {applied} 件適用、{failed} 件失敗")

        # 失敗したアーティストをファイルに出力
        if failed_artists:
            failed_path = self.backup_dir / "failed.json"
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            with open(failed_path, "w", encoding="utf-8") as f:
                json.dump(failed_artists, f, ensure_ascii=False, indent=2)
            print(f"失敗リスト: {failed_path}")

        return {"applied": applied, "skipped": 0, "failed": failed, "backup": backup_path}

    def _create_backup(self, candidates: list[ConversionCandidate]) -> Path:
        """バックアップを作成"""
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"backup_{timestamp}.json"

        tracks = []
        for c in candidates:
            track_info = self.music.get_track_info_for_backup(c.library_name)
            for t in track_info:
                tracks.append(
                    {
                        "persistent_id": t["persistent_id"],
                        "name": t["name"],
                        "original": {
                            "artist": t["artist"],
                            "album_artist": t["album_artist"],
                            "sort_artist": t["sort_artist"],
                            "sort_album_artist": t["sort_album_artist"],
                        },
                        "converted_to": {
                            "artist": c.musicbrainz_name,
                            "album_artist": c.musicbrainz_name,
                            "sort_artist": c.sort_name,
                            "sort_album_artist": c.sort_name,
                        },
                    }
                )

        backup_data = {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "tracks": tracks,
            "summary": {
                "total_tracks": len(tracks),
                "artists_converted": [c.library_name for c in candidates],
                "conversion_map": {c.library_name: c.musicbrainz_name for c in candidates},
            },
        }

        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)

        return backup_path

    def restore(self, backup_path: Path) -> int:
        """バックアップから復元

        Returns:
            復元されたトラック数
        """
        if not backup_path.exists():
            print(f"エラー: バックアップファイルが見つかりません: {backup_path}")
            return 0

        with open(backup_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        tracks = data.get("tracks", [])
        if not tracks:
            print("復元するトラックがありません。")
            return 0

        print(f"{len(tracks)} トラックを復元します...")

        restored = 0
        for t in tracks:
            original = t["original"]
            try:
                success = self.music.restore_track(
                    persistent_id=t["persistent_id"],
                    artist=original.get("artist"),
                    album_artist=original.get("album_artist"),
                    sort_artist=original.get("sort_artist"),
                    sort_album_artist=original.get("sort_album_artist"),
                )
                if success:
                    restored += 1
            except AppleMusicError:
                pass

        print(f"完了: {restored}/{len(tracks)} トラックを復元しました。")
        return restored

    def export_not_found(
        self, output_path: Path, llm: Optional[str] = None, mappings_path: Optional[Path] = None,
        batch_size: int = 100
    ) -> int:
        """見つからなかったアーティストを TSV ファイルに出力

        Args:
            output_path: 出力ファイルパス（1行1アーティスト）
            llm: LLM CLI を使用して変換 ("claude" or "gemini")
            mappings_path: LLM 出力先 (デフォルト: mappings.tsv)
            batch_size: LLM 処理時のバッチサイズ (デフォルト: 100)

        Returns:
            出力した件数
        """
        not_found = self.cache.get_not_found()
        if not not_found:
            print("見つからなかったアーティストはありません。")
            return 0

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(not_found) + "\n")

        print(f"{len(not_found)} 件を {output_path} に出力しました。")

        # LLM で変換
        if llm:
            if mappings_path is None:
                mappings_path = DATA_DIR / "mappings.tsv"
            self._translate_with_llm(not_found, llm, mappings_path, batch_size)

        return len(not_found)

    def _translate_with_llm(
        self, artists: list[str], llm: str, output_path: Path, batch_size: int = 100
    ) -> bool:
        """LLM CLI を使用してアーティスト名を変換（バッチ処理）

        Args:
            artists: アーティスト名リスト
            llm: LLM CLI ("claude" or "gemini")
            output_path: 出力先パス
            batch_size: バッチサイズ (デフォルト: 100)

        Returns:
            成功した場合 True
        """
        total_batches = (len(artists) - 1) // batch_size + 1
        print(f"\n{llm} で変換中... ({len(artists)} 件を {total_batches} バッチに分割)")

        all_mappings = {}

        for i in range(0, len(artists), batch_size):
            batch = artists[i:i + batch_size]
            batch_num = i // batch_size + 1
            print(f"  バッチ {batch_num}/{total_batches} ({len(batch)} 件)...", end=" ", flush=True)

            result = self._call_llm_batch(batch, llm)
            if result:
                all_mappings.update(result)
                print(f"✓ {len(result)} 件")
            else:
                print("✗ 失敗")

        if not all_mappings:
            print("エラー: すべてのバッチが失敗しました")
            return False

        # 結果をTSV形式で保存
        with open(output_path, "w", encoding="utf-8") as f:
            for original, converted in all_mappings.items():
                f.write(f"{original}\t{converted}\n")

        print(f"→ {len(all_mappings)} 件を {output_path} に保存しました")
        print(f"→ 次のコマンドでインポート: python3 musicdeloc.py import-mappings {output_path}")
        return True

    def _call_llm_batch(self, artists: list[str], llm: str) -> Optional[dict]:
        """単一バッチを LLM で処理

        Args:
            artists: アーティスト名リスト（バッチ）
            llm: LLM CLI ("claude" or "gemini")

        Returns:
            マッピング辞書、失敗時は None
        """
        prompt = f"""以下のアーティスト名を正式名に変換してください。

ルール:
- 海外アーティストのカタカナ表記 → 英語の正式名に変換（例: ビートルズ → The Beatles）
- 日本人アーティスト → 日本語のまま保持（例: 木村カエラ、スガシカオ、篠原ともえ はそのまま）
- 英語名がそのままの場合はそのまま出力
- コラボレーション（A & B）は各アーティストに上記ルールを適用
- 分からない場合は元の名前をそのまま使用

重要: 日本人アーティストをローマ字に変換しないでください。

JSON形式のみで出力してください（説明不要）:
{{"元の名前": "正式名", ...}}

アーティスト一覧:
{json.dumps(artists, ensure_ascii=False, indent=2)}
"""

        try:
            if llm == "claude":
                result = subprocess.run(
                    ["claude", "-p", prompt],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            elif llm == "gemini":
                result = subprocess.run(
                    ["gemini", "-p", prompt],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            else:
                return None

            if result.returncode != 0:
                return None

            # JSON を抽出
            output = result.stdout.strip()
            return self._extract_json(output)

        except subprocess.TimeoutExpired:
            return None
        except FileNotFoundError:
            return None

    def _extract_json(self, text: str) -> Optional[dict]:
        """テキストから JSON を抽出"""
        # まずそのまま試す
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # ```json ... ``` ブロックを探す
        import re
        match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # { から } までを探す
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and start < end:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        return None

    def import_mappings(self, input_path: Path) -> int:
        """TSV マッピングファイルをキャッシュにインポート

        Args:
            input_path: マッピングファイル（タブ区切り: 元の名前 → 正式名）

        Returns:
            インポートした件数
        """
        if not input_path.exists():
            print(f"エラー: ファイルが見つかりません: {input_path}")
            return 0

        mappings: dict[str, str] = {}
        with open(input_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    mappings[parts[0]] = parts[1]

        if not mappings:
            print("エラー: インポートするデータがありません。")
            return 0

        imported = 0
        for original, converted in mappings.items():
            if original and converted:
                self.cache.set_manual(original, converted)
                imported += 1
                print(f"  {original} → {converted}")

        print(f"\n{imported} 件をインポートしました。")
        return imported


def main():
    parser = argparse.ArgumentParser(
        description="Apple Music のアーティスト名を MusicBrainz 正式名に変換"
    )
    parser.add_argument(
        "-y", "--yes", action="store_true",
        help="確認プロンプトをスキップ"
    )
    subparsers = parser.add_subparsers(dest="command", help="コマンド")

    # scan
    scan_parser = subparsers.add_parser("scan", help="アーティスト名をスキャン")
    scan_parser.add_argument("--all", "-a", action="store_true", help="全アーティストを一覧表示")

    # fetch
    fetch_parser = subparsers.add_parser("fetch", help="MusicBrainz から正式名を取得")
    fetch_parser.add_argument("--artist", type=str, help="特定のアーティストのみ処理")
    fetch_parser.add_argument(
        "--non-interactive", action="store_true", help="非インタラクティブモード"
    )

    # review
    subparsers.add_parser("review", help="変換候補をレビュー")

    # apply
    apply_parser = subparsers.add_parser("apply", help="変換を適用")
    apply_parser.add_argument("--dry-run", action="store_true", help="実際には変更しない")

    # restore
    restore_parser = subparsers.add_parser("restore", help="バックアップから復元")
    restore_parser.add_argument("backup_file", type=Path, help="バックアップファイル")

    # cache
    cache_parser = subparsers.add_parser("cache", help="キャッシュ管理")
    cache_subparsers = cache_parser.add_subparsers(dest="cache_command")
    cache_subparsers.add_parser("list", help="キャッシュ一覧")
    cache_subparsers.add_parser("clear", help="キャッシュをクリア")
    cache_remove = cache_subparsers.add_parser("remove", help="エントリを削除")
    cache_remove.add_argument("artist", type=str, help="削除するアーティスト名")

    # export-not-found
    export_parser = subparsers.add_parser(
        "export-not-found", help="見つからないアーティストを TSV 出力"
    )
    export_parser.add_argument(
        "-o", "--output", type=Path, default=DATA_DIR / "not_found.tsv",
        help=f"出力ファイル (デフォルト: {DATA_DIR}/not_found.tsv)"
    )
    export_parser.add_argument(
        "--llm", choices=["claude", "gemini"],
        help="LLM CLI でカタカナ名を英語正式名に変換し mappings.tsv に出力"
    )
    export_parser.add_argument(
        "--mappings", type=Path, default=DATA_DIR / "mappings.tsv",
        help=f"LLM 出力先 (デフォルト: {DATA_DIR}/mappings.tsv)"
    )
    export_parser.add_argument(
        "--batch-size", type=int, default=100,
        help="LLM 処理時のバッチサイズ (デフォルト: 100)"
    )

    # import-mappings
    import_parser = subparsers.add_parser(
        "import-mappings", help="変換マッピングをインポート"
    )
    import_parser.add_argument(
        "input_file", type=Path, help="マッピングファイル (TSV)"
    )

    args = parser.parse_args()

    app = MusicDeLoc()

    if args.command is None:
        # デフォルト: 非対話で一括処理
        app.scan(show_all=False)
        candidates = app.fetch(interactive=False)

        # 見つからないアーティストを自動出力
        not_found = app.cache.get_not_found()
        if not_found:
            output_path = DATA_DIR / "not_found.tsv"
            app.export_not_found(output_path)
            print(f"→ Gemini/Claude で変換後、import-mappings でインポートしてください\n")

        if candidates:
            app.apply(candidates, auto_confirm=args.yes)

    elif args.command == "scan":
        app.scan(show_all=args.all)

    elif args.command == "fetch":
        artists = [args.artist] if args.artist else None
        app.fetch(artists=artists, interactive=not args.non_interactive)

    elif args.command == "review":
        app.review()

    elif args.command == "apply":
        app.apply(dry_run=args.dry_run, auto_confirm=args.yes)

    elif args.command == "restore":
        app.restore(args.backup_file)

    elif args.command == "cache":
        if args.cache_command == "list":
            entries = app.cache.get_all()
            if not entries:
                print("キャッシュは空です。")
            else:
                print(f"キャッシュ: {len(entries)} 件")
                for name, entry in entries.items():
                    action_str = {
                        "convert": f"→ {entry.musicbrainz_name}",
                        "skip": "(スキップ)",
                        "not_found": "(未解決)",
                        "manual": f"→ {entry.musicbrainz_name} (手動)",
                    }.get(entry.action, "")
                    print(f"  {name} {action_str}")

        elif args.cache_command == "clear":
            app.cache.clear()
            print("キャッシュをクリアしました。")

        elif args.cache_command == "remove":
            if app.cache.remove(args.artist):
                print(f"'{args.artist}' を削除しました。")
            else:
                print(f"'{args.artist}' はキャッシュにありません。")

        else:
            cache_parser.print_help()

    elif args.command == "export-not-found":
        app.export_not_found(
            args.output,
            llm=getattr(args, 'llm', None),
            mappings_path=getattr(args, 'mappings', None),
            batch_size=getattr(args, 'batch_size', 100)
        )

    elif args.command == "import-mappings":
        app.import_mappings(args.input_file)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
