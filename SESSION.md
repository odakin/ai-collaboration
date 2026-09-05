# SESSION.md — ai-collaboration

## 現状 (2026-09-06)

repo 新設 (Phase 1 = claude-config からの分離)。conventions 3 本 + scripts 4 本を git 履歴つきで移設、骨格 (CLAUDE / DESIGN / README / LICENSE / .gitignore / CI) を作成、claude-config 側は stub + forwarder、呼び元 (owner の private 検証 repo の shim / odakin-prefs check・SKILL) は本 repo の path へ。

## 残タスク

- [ ] Phase 2 の trigger 監視 (= DESIGN の表): Codex runner Pilot A 開始で `multi-session-coordination.md` と `codex/` を移設
- [ ] file が 15 本を超えたら index 生成 tool を共用化 (DESIGN)

## 決定ログ

- **2026-09-06: 新設** — 判断は DESIGN.md (分離の理由 / Phase 1 の範囲 / 移し方 = format-patch 履歴 import / stub + forwarder / Phase 2 trigger)
