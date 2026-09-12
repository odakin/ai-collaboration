# CLAUDE.md — ai-collaboration

**AI との協働で研究を回すための運用基盤 (layer 1、public)。** 「AI に何を任せ、何を人が確かめるか」を、規約 (何を検査するか) + 運用 (どう回し続けるか) + 道具 (機械 gate・runner・sandbox) の三点セットで持つ。vendor 中立 (Claude Code / Codex / 別ベンダーの pass を同じ規律で扱う)。

2026-09-06 に [`claude-config`](https://github.com/odakin/claude-config) から分離 (= あちらは Claude Code の setup / hooks / domain 規約の harness に戻る、本 repo は AI 協働の platform として育てる)。分離の判断と段階は `DESIGN.md`。移設 file の git 履歴は `git format-patch` で持ち込み済 (= 「実践が講演に先行した」 等の credit 主張の根拠)。

## 構造

```
ai-collaboration/
├── AGENTS.md / CLAUDE.md / SESSION.md / DESIGN.md / README.md / LICENSE / .gitignore
├── conventions/
│   ├── physics-verification-cycle.md   # 何を検査するか: 4 station / 機械 anchor / foil / tier / 3 状態 / verify-to-learn /
│   │                                   #   第二の目 / rubric 事前登録 / 止まる規律 / cross-vendor / campaign 運用 A-K
│   ├── verification-cycle-ops.md       # どう回し続けるか: 6 原則 / 導出 state 機械 / 台帳 3 種 + retro / 無人層 / fresh session の手順
│   ├── cold-eyes-isolation.md          # 第二の目の隔離: 汚染経路 7 口 / 封じた sandbox / spec に書いてよいこと / 審査文書の変種 / 受領後の汚染 grep
│   ├── edit-intent-record.md           # AI による原稿改稿の意図記録: 1 pass 1 sidecar (hunk → finding / decision / 種類 = 実装・裁量・削除) / 裁量枠 / 削除 verbatim + 共著者本文の単独削除禁止 / 量の指示 / commit 前 gate / 依頼 spec の 3 行 /
│   │                                   #   §7 実装 pass の作業規律 (当てる→組版 gate→記録、 anchor assert、 削除前の blame、 清掃版どうしの diff) / §8 投稿前の清掃
│   └── delegated-work-packages.md      # 相手側の AI への作業委譲: 判断と実行の分離 / 常設 3 層 (入口・手順・定義) + WP 1 本 = 1 セッション / WP の 7 要素 /
│                                       #   受入基準は依頼側の独立実装の出力 / 全部書いて ready だけ着手 / 書き込み zone / 結果ノート / 解釈は書かせない
├── docs/state-discrimination.md       # 状態識別の一般数式・凸錐と座標の仮定・certificate の正本
├── template/                           # clone-and-run skeleton of a private verification repo (scripts/init-verification-repo.py が展開)
├── examples/verification-repo/         # 完結した見本 campaign 1 本 (spec / ledger / check+foil / results AUTO block / retro + hoist)
└── scripts/
    ├── README.md                       # docstring から生成する全数索引
    ├── generate-script-index.py        # README を --write / --check、CI が drift を拒否
    └── *.py                            # 検証器・library・sandbox/receipt tooling、全て --selftest
```

全 script は `--selftest` を持つ。各 file の 1 行説明は file 冒頭の docstring が正本で、[`scripts/README.md`](scripts/README.md) は生成 view。

## 4 層モデルでの位置

layer 1 (public、全 Claude Code / Codex ユーザー向け)。**依存できるのは layer 1 のみ** (`claude-config` とは相互参照可 = 同じ層)。個人の instance (campaign dir・台帳の中身・launchd routine・hook 配線) は owner の private layer に置き、本 repo には kernel だけを書く (kernel-up / instance-down、正本 = `claude-config/docs/personal-layer.md`)。

## 使い方 (最小)

- 規約を読む順: `physics-verification-cycle.md` (§1 サイクルの形 → §15 campaign 運用) → `verification-cycle-ops.md` (§5 fresh session の手順) → 必要なら `cold-eyes-isolation.md`
- 自分の検証 repo を作る: 必須 4 file + `campaigns/<date>-<slug>/{spec.md, ledger.yaml}`、pre-commit から `ledger-commit-cadence-gate.py --pre-commit --worker-scope-env CAMPAIGN_WORKER_DIR`、完了時 `verification-campaign-report.py <dir> --run --write`、受領後 `--carryover --write` と `--index --write`。schema は `physics-verification-cycle.md#campaign-tooling` A。非有界な moment operator と有限窓を扱う場合は同 doc の [`#unbounded-moment-domain-audit`](conventions/physics-verification-cycle.md#unbounded-moment-domain-audit) を追加で使う
- 第二の目を別 session に出す: `make-review-sandbox.py create <slug> --spec REVIEW-SPEC.md --include <paper.pdf>` → cwd を sandbox に pin して spawn → `collect`
- AI に決定 ledger どおりの原稿改稿を実装させる: 依頼 spec に `edit-intent-record.md#requester-spec-line` の 3 行 → 実装側は `check-edit-intent.py --scaffold … --out review/edit-intent-<date>.md` → 種類 / ID / 意図 を埋める → 同 script の検査 ALL PASS → 原稿と同じ pass で commit。 受領は裁量枠から読む / --fill (JSON から 種類・ID・意図 を一括で埋めて検査)
- 自分が実装側のとき: 当てる → 別 dir で組版 → 記録 → commit の順 ([`#apply-then-record`](conventions/edit-intent-record.md#apply-then-record))。 削除の前に `git blame`。 共著 review 中の原稿の読み合わせは `review-markup-clean.py` を基準版と現在版の両方に当ててから latexdiff ([`#cleaned-base-diff`](conventions/edit-intent-record.md#cleaned-base-diff))、 投稿前清掃も同じ script ([`#submission-cleanup`](conventions/edit-intent-record.md#submission-cleanup))
- 数か月の解析を共同研究者 (人間 + その AI) に実行してもらう: 定義を 1 つの SPEC に固め、1 セッション分の作業書 (WP) に割り、**受入基準は自分の独立実装で出した数値**で埋める ([`delegated-work-packages.md`](conventions/delegated-work-packages.md))。解釈・結論・基準値の書き換えは作業者に渡さない ([`#what-the-worker-must-not-write`](conventions/delegated-work-packages.md#what-the-worker-must-not-write))
- 印字した係数の符号を外部の絶対量で守る: project に登録簿 `sign-anchors.json` (印字量 → 外部 anchor → 全体反転 foil) → `check-sign-anchors.py --run --deferrals` (gate = anchor が現稿で PASS し、 全体反転の foil で assertion により FAIL、 carrier の無い「規約差」 0) / `--fleet-scan` (fleet のどの検査が変換を見分けるか) / `--readers` (どの検査が原稿を実行時に開くか)。 規則 = claude-config `paper-audit.md#absolute-sign-external-anchor` / `#convention-difference-closure`

## 安全規則 (public repo)

`claude-config/CLAUDE.md §安全規則` と同じ: 実名・email・非公開 repo 名 (例外 list 以外)・所属・金融・他ユーザー名を file 本文 / commit message / PR に書かない。**識別子を含まない文章でも leak は成立する** — 審査・査読中の文書や未公開原稿から文言を verbatim で引く / 図から読んだ実測値を写す / それを selftest fixture に使う、 は既存 gate を素通りする ([`claude-config/CLAUDE.md#non-identifier-content-leak`](../claude-config/CLAUDE.md#non-identifier-content-leak))。 campaign の finding (他者論文の誤り疑い) は本 repo に書かない (default 非公開 = `physics-verification-cycle.md#verify-to-learn`)。

## 規約参照

- 共通: `claude-config/CONVENTIONS.md` (git / 必須 file / sweep / 安全規則)
- 委譲と返送 spine (Claude 内): `claude-config/conventions/multi-session-coordination.md` (Phase 2 で本 repo へ移設予定 = DESIGN)
- Codex 統合 (AGENTS / PARITY / setup-codex): `claude-config/codex/` (同上)
- 無人 routine の一般則: `claude-config/conventions/scheduled-tasks.md` / `multi-machine-state.md`

## 検査

```bash
set -e
for s in scripts/*.py; do python3 "$s" --selftest; done
```

CI = `.github/workflows/checks.yml` (全 script の selftest。`secure-new-repo.sh --code` の baseline)。失敗した script の終了値を loop で失わない。

## How to Resume

1. `SESSION.md` → 直近の変更と残タスク
2. `DESIGN.md` → 分離の判断 / Phase 2 の trigger
3. 呼び元 (owner の private layer) は path を本 repo に向けている: owner の private 検証 repo の `scripts/*` shim / `odakin-prefs/scripts/check-verification-campaigns.py` / `odakin-prefs/skill/daily-verification-cycle-tick/SKILL.md`。旧 path (`claude-config/scripts/<same name>`) は forwarder として残る
