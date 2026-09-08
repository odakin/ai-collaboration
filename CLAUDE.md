# CLAUDE.md — ai-collaboration

**AI との協働で研究を回すための運用基盤 (layer 1、public)。** 「AI に何を任せ、何を人が確かめるか」を、規約 (何を検査するか) + 運用 (どう回し続けるか) + 道具 (機械 gate・runner・sandbox) の三点セットで持つ。vendor 中立 (Claude Code / Codex / 別ベンダーの pass を同じ規律で扱う)。

2026-09-06 に [`claude-config`](https://github.com/odakin/claude-config) から分離 (= あちらは Claude Code の setup / hooks / domain 規約の harness に戻る、本 repo は AI 協働の platform として育てる)。分離の判断と段階は `DESIGN.md`。移設 file の git 履歴は `git format-patch` で持ち込み済 (= 「実践が講演に先行した」 等の credit 主張の根拠)。

## 構造

```
ai-collaboration/
├── CLAUDE.md / SESSION.md / DESIGN.md / README.md / LICENSE / .gitignore
├── conventions/
│   ├── physics-verification-cycle.md   # 何を検査するか: 4 station / 機械 anchor / foil / tier / 3 状態 / verify-to-learn /
│   │                                   #   第二の目 / rubric 事前登録 / 止まる規律 / cross-vendor / campaign 運用 A-K
│   ├── verification-cycle-ops.md       # どう回し続けるか: 6 原則 / 導出 state 機械 / 台帳 3 種 + retro / 無人層 / fresh session の手順
│   ├── cold-eyes-isolation.md          # 第二の目の隔離: 汚染経路 6 口 / 封じた sandbox / spec に書いてよいこと / 受領後の汚染 grep
│   └── edit-intent-record.md           # AI による原稿改稿の意図記録: 1 pass 1 sidecar (hunk → finding / decision / 種類 = 実装・裁量・削除) / 裁量枠 / 削除 verbatim + 共著者本文の単独削除禁止 / 量の指示 / commit 前 gate / 依頼 spec の 3 行
├── docs/state-discrimination.md       # 状態識別の一般数式・凸錐と座標の仮定・certificate の正本
├── template/                           # clone-and-run skeleton of a private verification repo (scripts/init-verification-repo.py が展開)
├── examples/verification-repo/         # 完結した見本 campaign 1 本 (spec / ledger / check+foil / results AUTO block / retro + hoist)
└── scripts/
    ├── verification-campaign-report.py # campaign の集計: --index (導出 state + efficacy dataset) / --surface / --run (foil 契約) / --carryover / --write
    ├── ledger-commit-cadence-gate.py   # pre-commit gate: 1 commit の ledger entry 上限 + worker scope (CAMPAIGN_WORKER_DIR 外を refuse)
    ├── check-edit-intent.py            # edit-intent sidecar: --scaffold (diff から hunk 行 + 位置 + 削除 verbatim を生成) / 検査 (hunk 被覆・位置・種類・ID 実在・裁量枠・削除 verbatim・意図、 PASS/FAIL + exit code) / --selftest
    ├── make-review-sandbox.py          # 封じた review sandbox を 1 コマンドで切る / 受領時に collect
    ├── gpt_measurements.py             # GPT / POVM の間主観性・sharpness・極値性を定義から検査する数学 library (有限 + 無限次元 anchor)
    ├── state_discrimination.py         # NumPy のみで 2 状態識別の下界・slack・最適 POVM・qubit / cube を検査
    ├── hpd-credible-level.py           # 公開 MCMC chain の 2D 周辺分布に対する点 / 軌跡の HPD 信用水準 (境界反射 KDE、 帯域 sweep、 Gaussian 照合、 2 dof Δχ²)
    ├── svg-contour-extract.py          # 論文 PDF 図 (pdftocairo -svg) の等高線 path を transform 合成 + 公開等高線の bbox で自己較正して data 座標へ
    ├── floquet-monodromy.py            # Mathieu / kinetic-function / conformal 質量項の Floquet 指数を厳密周期背景の monodromy で (k=0 marginal を selftest に固定)
    ├── nstar-fixed-point.py            # 単一場 inflation の N_* fixed point (reheating history 込み、 厳密背景の観測量、 history 間の (n_s, r) 分離)
    ├── expanding-mode-growth.py        # 膨張する振動背景での daughter mode の線形成長 (真空を置く時刻を knob に = 共鳴境界の onset 依存性)
    └── dilaton-spectator-growth.py     # dilaton 型結合 e^{-γχ/M_P}(∂φ)² の spectator 零モードが inflation の roll 全体で Weyl 因子だけ伸びることの検算 (末期の質量、 λ 符号別の落ち着き先)
```

全 script は `--selftest` を持つ。各 file の 1 行説明は file 冒頭 (docstring 1 行目 / doc-meta) が正本。

## 4 層モデルでの位置

layer 1 (public、全 Claude Code / Codex ユーザー向け)。**依存できるのは layer 1 のみ** (`claude-config` とは相互参照可 = 同じ層)。個人の instance (campaign dir・台帳の中身・launchd routine・hook 配線) は owner の private layer に置き、本 repo には kernel だけを書く (kernel-up / instance-down、正本 = `claude-config/docs/personal-layer.md`)。

## 使い方 (最小)

- 規約を読む順: `physics-verification-cycle.md` (§1 サイクルの形 → §15 campaign 運用) → `verification-cycle-ops.md` (§5 fresh session の手順) → 必要なら `cold-eyes-isolation.md`
- 自分の検証 repo を作る: 必須 4 file + `campaigns/<date>-<slug>/{spec.md, ledger.yaml}`、pre-commit から `ledger-commit-cadence-gate.py --pre-commit --worker-scope-env CAMPAIGN_WORKER_DIR`、完了時 `verification-campaign-report.py <dir> --run --write`、受領後 `--carryover --write` と `--index --write`。schema は `physics-verification-cycle.md#campaign-tooling` A
- 第二の目を別 session に出す: `make-review-sandbox.py create <slug> --spec REVIEW-SPEC.md --include <paper.pdf>` → cwd を sandbox に pin して spawn → `collect`
- AI に決定 ledger どおりの原稿改稿を実装させる: 依頼 spec に `edit-intent-record.md#requester-spec-line` の 3 行 → 実装側は `check-edit-intent.py --scaffold … --out review/edit-intent-<date>.md` → 種類 / ID / 意図 を埋める → 同 script の検査 ALL PASS → 原稿と同じ pass で commit。 受領は裁量枠から読む

## 安全規則 (public repo)

`claude-config/CLAUDE.md §安全規則` と同じ: 実名・email・非公開 repo 名 (例外 list 以外)・所属・金融・他ユーザー名を file 本文 / commit message / PR に書かない。campaign の finding (他者論文の誤り疑い) は本 repo に書かない (default 非公開 = `physics-verification-cycle.md#verify-to-learn`)。

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
