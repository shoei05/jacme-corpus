# jacme-2026.10.0

生成日時: 2026-10-10T23:35:26
層: 研究者限定（本文を含む。再配布しない）

## 入力（canonical/）とSHA-256

| ファイル | 行数 | SHA-256 |
|---|---|---|
| canonical/institutions.csv | 82 | `366640955fd3e656d9ccde71e7b5304de1f8b4f23311c802600ec69de164f24b` |
| canonical/source_manifest.csv | 165 | `3d545ee359ddb636df1205bfd37b936ebdf6e3dd49b32edc666dbda27cb01d8f` |
| canonical/documents.csv | 125 | `8a104c591fd227dcb49db740b17af759bc99e0c018c9442f3dbc0080745fec0e` |
| canonical/review_events.csv | 125 | `87ef087273bc5f96a418bea66017de6240c348369835784ad19fc4f436bd4796` |
| canonical/concepts.csv | 36 | `9a706e86b549eef30b77f3e41e1067f67ae3bec36e3ce5612ab1247ee95196bd` |
| canonical/standard_items.csv | 72 | `5d836d66313c62a19899dd188858f14eb09e32dee8c5f3014d049ce8ce847964` |
| canonical/judgments.csv | 8905 | `03914e3acefe0802b8027198a72b9475dce7b86e07e8834b894693cc98160f5e` |
| canonical/comments.csv | 12364 | `bf89159d490fbb4c54be7054c4540bf4479612de1f1024ef32656248106215c9` |
| canonical/quarantine_judgments.csv | 1 | `cc3d7a463439ce373f080db326fbef44fa8504af60a227ce3d6ddcc140d31e07` |
| canonical/comment_tags.csv | 185460 | `048d922d67188c83abff279516b8fff0885e388d64bc9f2a28673cc81b4e338e` |
| canonical/comment_classes.csv | 12364 | `0815f95a49188f51d84916d105cb381ba136c6a92646b1d3b385bd92c6a861f1` |
| canonical/private/comment_text.csv | 12364 | `901c0ff3f9d28c05b91b1674f71c4954dac9f802f21d26ef02e79c23ac42fecb` |
| canonical/private/sohyo.csv | 124 | `04701114116d38c25305145de3b635b8ca9de2cd59684728da6722c8577073c0` |
| canonical/private/area_gaihyo.csv | 1078 | `1c6406e5d164f219c04d8713ce17cc6e38361932e1c40a89c21d28f7c075d89f` |
| canonical/private/event_evidence.csv | 272 | `085b44450c694c13bb20944814fc047787b8f6d4180c54c81678bb39c3168417` |
| canonical/private/evaluators.csv | 845 | `86fb4ac04a31e0a70f84734d251ae1ed3dc0a254deada6c7bfb2a64bdfe66800` |
| canonical/private/comment_tag_probs.csv | 12364 | `c7976ac55625e7dbac5fa3c0fcd72439da62cbc691e87af7735bc21188e969cd` |

## 表と件数

| 表 | 件数 |
|---|---|
| institutions | 82 |
| source_manifest | 165 |
| documents | 125 |
| review_events | 125 |
| concepts | 36 |
| standard_items | 72 |
| judgments | 8905 |
| comments | 12364 |
| quarantine_judgments | 1 |
| comment_tags | 185460 |
| comment_classes | 12364 |
| comment_text | 12364 |
| sohyo | 124 |
| area_gaihyo | 1078 |
| event_evidence | 272 |
| evaluators | 845 |
| comment_tag_probs | 12364 |

## 検証

- 検査 93 件、失敗 0 件（validation_report.json）
- 総評集計との照合: 123 文書で確認、不一致 0
- フラグ分布: retrospective_reassessment={'false': 98, 'true': 22, 'not_applicable': 5}, mixed_standard={'false': 118, 'true': 6, 'not_applicable': 1}（Jev jev-1.13.0 の noul 確率を閾値 0.8/0.2 で true/false/unknown に写像。確率は正解率ではない。人手確認は未了で private/flag_audit_sample.csv に監査票がある）

## 全文検索

- `comment_fts` は FTS5 trigram。3文字未満の語（IR、FD、AI など）は MATCH で一致しないため、`short_term_hits`（事前計算: IR=300, FD=190, AI=21, SD=21, IT=3, SP=8, GP=7, e-=96, IP=10, EQ=0）または `WHERE text LIKE '%IR%'` を使う。
- 動作確認: `MATCH '診療参加型'` → 235 件

## 使い方

```
sqlite3 releases/jacme-2026.10.0/jacme.sqlite
bash releases/jacme-2026.10.0/run_datasette.sh   # 127.0.0.1:8001 のみ
```

## 既知の未確認事項

- retrospective_reassessment は「本審査の判定が実地調査後の改善を含むか」。追加審査・公表文は not_applicable（本人決定 2026-10-10）。値は Jev（型付き判定）の確率を 0.8/0.2 で写像、0.2〜0.8 は unknown。人手確認は未了（private/flag_audit_sample.csv）。
- mixed_standard の上書き規則（本人承認 2026-10-10）: noul が 0.2〜0.8 でも、choice が別版の下位領域を confidence 0.9 以上で選び、本文に版の明記（regex 根拠）があれば true（verification_status=jev_choice+text）。該当 41, 47, 48, 49, 50, 51。
- observation_start/end は後年再評価の文書だけ本文から取得。他は unknown。
- 版混在文書（6件）で領域4.1・4.2以外の適用版は未確認。
- quarantine_judgments（report72 5.2 B）は原本確認待ち。
- 取り組みカード（canonical/pilot_ir/public_practice_cards.csv）は別モデル（ChatGPT）の盲検判定を経て公開。人による全件確認は未了。
- comment_tags / comment_classes は Jev（codebook v1.1）の自動タグ。妥当性の確認は別モデル（ChatGPT）による盲検判定との比較（60件×3回）であり、人の参照判定ではない。T11・T13 の閾値は pilot03 を見て決めたため独立検証がなく信頼性が低い。scope・multi_function・secondary_function は探索的（集計の主張に使わない）。
