# SESSION.md — ai-collaboration

## 現状 (2026-09-06)

repo 新設 (Phase 1 = claude-config からの分離)。conventions 3 本 + scripts 4 本を git 履歴つきで移設、骨格 (CLAUDE / DESIGN / README / LICENSE / .gitignore / CI) を作成、claude-config 側は stub + forwarder、呼び元 (owner の private 検証 repo の shim / odakin-prefs check・SKILL) は本 repo の path へ。

## 残タスク

- [ ] Phase 2 の trigger 監視 (= DESIGN の表): Codex runner Pilot A 開始で `multi-session-coordination.md` と `codex/` を移設
- [ ] file が 15 本を超えたら index 生成 tool を共用化 (DESIGN)

## 決定ログ

- **2026-09-06: 新設** — 判断は DESIGN.md (分離の理由 / Phase 1 の範囲 / 移し方 = format-patch 履歴 import / stub + forwarder / Phase 2 trigger)

## 2026-09-06 (後半): GitHub 公開 + baseline + 呼び元切替 完了

- `odakin/ai-collaboration` public 作成・push。 `secure-new-repo.sh --code` = Dependabot / public-repo marker (leak gate stub) / CodeQL・branch protection は script の baseline 通り。 **積み残し = Semgrep + auto-merge workflow の push は `gh auth refresh -s workflow` 後に owner が実施** (workflow scope 不足)。
- claude-config 側 = stub 3 (anchor 33 保持) + forwarder 4、 commit 済。 owner 側呼び元は全部新 path。 selftest = 新 path 4 本 / forwarder 4 本 / shim 3 本 すべて PASS。
- 次 = Phase 2 判断 (DESIGN の trigger 表)。 CI 初回 run は次の code push で確認。
