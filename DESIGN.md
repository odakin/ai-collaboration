# DESIGN.md — ai-collaboration

現在採用している設計判断の snapshot。超越されたら `claude-config/docs/convention-design-principles.md#design-snapshot-operation` の lifecycle で処理。

## claude-config から分離した理由と、何を持ってきたか (2026-09-06)

**判断**: 検証サイクルの platform (規約 3 本 + script 4 本) を新 repo `ai-collaboration` (layer 1、public) に移す。`claude-config` は Claude Code の harness (setup / hooks / gitignore / domain 規約 / 生成 tool) として残す。
**Why**: `claude-config` の中身は conventions 106 本 + scripts 71 本 + Codex 統合で、名前 (Claude の設定) が実態 (AI 協働の運用基盤) と合わなくなった (user「ありえん、新しいリポを作ろう」)。rename は literal path 496 件 / 参照 file 803 件の移行で hook・routine が一斉に壊れる窓を作るので不採用。「説明で誤魔化す (rebrand)」は user が却下。∴ **中身の方を、名前が正しい新しい箱へ段階的に移す**。
**なぜこの 7 file が Phase 1 か**: 2026-08-31〜09-06 に生まれた検証サイクルの kernel と道具で、(a) 互いに閉じている (相互参照が repo 内で完結) (b) 呼び元が owner の private layer 4 箇所だけで path 更新が小さい (c) vendor 中立 (Claude / Codex の pass を同じ規律で扱う) = 新 repo の名の実体そのもの。
**移し方**: clone でなく一から骨格を書き、移す file の git 履歴だけ `git format-patch --root -- <paths>` → `git am` で持ち込む。clone は 106 規約の二重化 = drift 源 (今日一番痛かった型) なので棄却。
**claude-config 側**: 移した規約は **anchor id を保った stub** (旧 `<a id>` を全部列挙し「移設先はこちら」)、script は **forwarder** (同名で新 path を exec)。∴ 496 件の literal path も `#anchor` link も壊れない。呼び元は順次新 path へ。
**限界**: 規約 corpus が 2 repo に割れる → routing cost。生成 tool (`generate-tree.py` 等) は claude-config 側にあり、本 repo の index は当面手書き (file が 7 本なので足りる)。

## Phase 2 (trigger 付き、speculative 実行禁止)

| 移設候補 | trigger |
|---|---|
| `multi-session-coordination.md` (委譲・返送 spine・worktree 判定・sizing) | Codex runner の Pilot A が始まった時 (= AI–AI 協働の中核規約が vendor 中立の箱に要る) |
| `codex/` (AGENTS / HOME-AGENTS / PARITY / skills / hooks / setup-codex.sh) | 同上 (Codex が co-equal な runner になる時)。setup-codex.sh の path は移設時に一括更新 |
| `output-cap-death-loop.md` / `tool-call-robustness.md` (worker の死に方) | multi-session-coordination と同時 |
| agent-board の一般則 (`#git-immutable-event-board`) | multi-session-coordination と同時 |

**移さないもの**: setup.sh / hooks (Claude Code 固有の harness)、LaTeX・Office・mail 等の domain 規約、generate-tree 等の生成 tool。= claude-config の名前で true な範囲。

## index は当面手書き (2026-09-06)

**判断**: README / CLAUDE.md の file 一覧は手書き。**Why**: file 7 本で生成 tool を持ち込む cost に見合わない。**再訪 trigger**: file が 15 本を超えたら claude-config の `generate-tree.py` を `--root` 引数で共用できるよう hoist する。
