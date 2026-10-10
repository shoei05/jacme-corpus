# JACME評価報告書コーパス 構成（phase 1、2026-10-10）

## 層

| 層 | 場所 | 中身 | 公開 |
|---|---|---|---|
| 原資料 | `raw/pdf/`（164件）、`raw/duplicates/`、`raw/html/` | JACMEから取得したPDFとHTML。変更しない | しない |
| 抽出 | `text/`、`knowledge/*.csv`、`knowledge/reports/` | scripts 01〜09 の出力。正本の入力 | しない |
| 正本 | `canonical/` | 固定ID付きのCSV/JSONL。`id_map.json` が自然キー→IDを永続化 | しない |
| 正本（自由文） | `canonical/private/` | コメント本文、総評、概評、フラグの根拠断片、評価チーム氏名 | しない |
| 研究リリース | `releases/jacme-YYYY.MM.N/` | SQLite（全表＋FTS5）、RELEASE.md、Datasette設定。127.0.0.1 のみ | 研究者限定 |
| 公開データ | `public/data/` | 許可列だけをゼロから生成したJSON/CSV。本文・引用・氏名なし | する |
| 公開画面 | `public/site/` | 静的HTML/JS 3画面。`../data/` を読む | する |

## 正本の表

| 表 | 主キー | 自然キー（id_map） | 備考 |
|---|---|---|---|
| institutions | institution_id (INST-nnn) | 大学名 | 改称は未対応（名称履歴は次段階） |
| source_manifest | file | — | SHA-256、サイズ、URL、取得日、kind |
| documents | doc_id | — | 既存の doc_id を維持。総評の集計値を含む |
| review_events | event_id (EV-nnnn) | doc_id | 現状は文書1件＝イベント1件。後年再評価・版混在フラグ（true/false/unknown） |
| concepts | concept_id | — | 36下位領域。名称はVer.2系の最頻名称 |
| standard_items | (standard_family, original_subarea) | — | 原番号→concept_id、relation = same/renamed/renumbered |
| judgments | judgment_id (JG-nnnnnn) | doc_id + 原下位領域 + 水準 | judgment_before は追加審査の本審査時判定 |
| comments | comment_id (CM-nnnnnn) | doc_id + 下位領域 + 水準 + 種別 + 連番 + 本文ハッシュ12桁 | 本文は private/comment_text |
| quarantine_judgments | — | — | 誤抽出の隔離行（report72 5.2 B） |

フラグの規則（2026-10-10 変更）: `retrospective_reassessment` と `mixed_standard` は `scripts/14_flags_jev.py` が TypeSafe Jev（型付き判定、返却モデル名 jev-1.13.0）に候補箇所（はじめに・総評の冒頭と、再評価・再開・改善状況・Ver./版・年月まで等を含む文）を読ませた noul 確率を、閾値 0.8 以上=true、0.2 以下=false、中間=unknown で写像する。確率・モデル名・抜粋位置は `private/flag_judgments_jev.csv`、監査用の抜粋は `private/flag_audit_sample.csv`（true 全件＋false 10件＋unknown）。Jev の確率は正解率ではない。人による確認は未了（監査票 flag_audit_sample.csv）。regex による根拠断片は `private/event_evidence.csv` に補助として残す。regex との不一致は `private/flag_disagreements.csv`、review_events には `regex_retrospective` / `regex_mixed`（true/none）を併記する。
第2判定者: Cloudflare Workers AI の Clef（27B、`private/flag_judgments_clef.csv`）の確率を review_events の `p_retro_clef` / `p_mixed_clef` / `clef_model` に併記し、閾値写像後の一致を `jev_clef_agree`（true/false。後年再評価が not_applicable の文書は版混在だけで判定）に置く。正本の値は Jev（上書き規則込み）のまま。これらの列は非公開層だけに置き、公開 events には出さない。
バックエンドは差し替え可能: `--backend typesafe`（Jev、既定）と `--backend workers-ai --model clef|clef-flash`（Cloudflare Workers AI の Clef。`CLOUDFLARE_ACCOUNT_ID` と `CLOUDFLARE_API_TOKEN` が要る。2026-10-10 時点では未設定で未実行）。両方の結果がそろったら `python3 scripts/15_compare_flag_models.py` で一致率を出す。
`retrospective_reassessment` の定義は「本審査（review_type=main）の判定が、当初の実地調査より後の改善を含むか」。追加審査と公表文は対象外で `not_applicable`（本人決定 2026-10-10。Jev の確率は flag_judgments_jev.csv に残すが写像しない）。`mixed_standard` は公表文のみ not_applicable。上書き規則（本人承認 2026-10-10）: noul が閾値の間（0.2〜0.8）でも、choice 質問が別版の下位領域（4.1_4.2 等）を confidence 0.9 以上で選び、かつ本文に版の明記（regex 根拠行）があれば true とし、verification_status=`jev_choice+text` を付ける（該当 41, 47, 48, 49, 50, 51）。監査ファイル `private/flag_audit_sample.csv` の human_verdict_* / chatgpt_verdict / chatgpt_note 列は再生成時に doc_id で引き継ぎ、生成値が変わらなければ上書きしない。質問文 v2 でも追加審査であること自体は yes の理由にしないと明示している。

## 再生成の手順

```bash
cd "<案件フォルダ>"
python3 scripts/01_parse_table.py; python3 scripts/02_manifest_download.py; python3 scripts/04_past_links.py
python3 scripts/03_extract_text.py; python3 scripts/05_structure.py; python3 scripts/06_validate.py
python3 scripts/07_comments.py; python3 scripts/09_harmonize.py; python3 scripts/08_markdown.py
python3 scripts/10_canonical.py            # 正本（IDは id_map.json で固定。Jev判定ファイルがあればフラグに反映）
zsh -lc 'python3 scripts/14_flags_jev.py'   # フラグをJevで判定（外部API。再判定するときだけ）
# Clef で同じ質問を流す（トークン設定後）: CLOUDFLARE_ACCOUNT_ID=… CLOUDFLARE_API_TOKEN=… python3 scripts/14_flags_jev.py --backend workers-ai --model clef && python3 scripts/15_compare_flag_models.py
python3 scripts/11_validate_canonical.py   # 失敗があれば終了コード1
python3 scripts/12_release.py jacme-2026.10.0
python3 scripts/13_public_export.py jacme-2026.10.0   # 漏えい検査込み。違反時は public/data を削除
```

公開画面の確認（配備はしない）:

```bash
cd public && python3 -m http.server 8765 --bind 127.0.0.1
# http://127.0.0.1:8765/site/index.html
```

研究者限定の閲覧: `bash releases/jacme-2026.10.0/run_datasette.sh`（127.0.0.1:8001。Tailscale等の外部公開は設定しない）。

## 漏えい検査（13_public_export.py）

公開ファイル（public/data と public/site）の空白を除いた本文に対し、次の文字列が含まれないことを確認する。
コメント本文500件の先頭・中央・末尾20文字、総評と概評の同様の断片、評価チーム氏名（3文字以上）、語「全文」。
加えて公開CSVの列名に text、sohyo、snippet、file、n_evaluators などが無いことを確認する。

## 意味タグ（試行中）

- コードブック: `canonical/codebook/codebook_v0.yaml`（定義のみ）、原文引用例は `canonical/private/codebook_v0_examples.md`。
- 試行: `zsh -lc 'python3 scripts/16_tag_pilot_jev.py --n 200 --run-id pilot01'`（Jev。全コーパスには走らせない）。出力は `canonical/private/tags_jev_<run_id>.jsonl`（全確率、モデル名、コードブック版）。監査は `private/tag_audit_packet.md`（答えなし）と `private/tag_audit_key.csv`。
- v1 以降: `scripts/18_tag_pilot_v1.py --codebook codebook_v1.1 --run-id pilot03 --exclude-run pilot01 --exclude-run pilot02`（Jev）。`--backend workers-ai --model clef` で Clef の比較判定。閾値はコードブックの thresholds（T01〜T10 0.3、T11 0.7、T13 0.8 は暫定）。
- 全件（本人承認後）: `zsh -lc 'python3 scripts/20_tag_full_jev.py --run-id full_v1.1 --codebook codebook_v1.1 --concurrency 4'`。再開可能（追記専用、判定済みを飛ばす）、200件ごとに checkpoint、使用量は `private/tags_jev_full_v1.1_usage.json`。`--dry-run` で件数と推定トークンだけ表示。
- 監査との比較: `python3 scripts/17_compare_tag_audit.py --run-id pilot03`（ChatGPT の盲検判定 CSV を `private/tag_audit_chatgpt_pilot03.csv` に置く）。
- 全件タグの正本化: `python3 scripts/21_tag_tables.py --run-id full_v1.1`。作業ディレクトリに生成し、ID集合・重複・余分・コードブック版・閾値・モデル・質問ハッシュの関門（`canonical/tag_tables_manifest.json`）を満たすときだけ正本へ置換。13 は manifest の complete と入出力ハッシュの一致がなければテーマ集計を出さない。
- 公開はテーマ別の集計（event × concept × level × type × theme の件数、大学数）と定義だけ。妥当性の確認は別モデル（ChatGPT）による盲検判定との比較（60件×3回）で、人の参照判定ではない。リリースの `MANIFEST.json` に構成要素ごとの状態（implemented / data_generated / validated / published）を機械生成する。

## 未整備（次段階）

- テーマ（意味タグ）、主張単位、コードブック、Jev分類。
- 大学の名称履歴、文書の改訂版、イベントと文書の多対多。
- observation_start/end と評価時点を全文書で確認。unknown のフラグの人手確認。
- 非公開Gitへの正本の登録と、公開サイトの配備先。
