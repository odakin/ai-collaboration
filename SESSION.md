# SESSION.md — ai-collaboration

## 現状 (2026-09-06)

repo 新設 (Phase 1 = claude-config からの分離)。conventions 3 本 + scripts 4 本を git 履歴つきで移設、骨格 (CLAUDE / DESIGN / README / LICENSE / .gitignore / CI) を作成、claude-config 側は stub + forwarder、呼び元 (owner の private 検証 repo の shim / odakin-prefs check・SKILL) は本 repo の path へ。

## 残タスク

- 状態識別の数式と道具を追加。入口 = [証明と利用範囲](docs/state-discrimination.md)、[library](scripts/state_discrimination.py)、[検証時の certificate](conventions/physics-verification-cycle.md#state-discrimination-certificates)。reporter は未知の foil crash と marker 後の非ゼロ終了を失敗にし、`--run` の失敗を呼び元へ返す。実装判断 = DESIGN.md。

- Session 宛て board との受領経路の接続は [verification-cycle-ops](conventions/verification-cycle-ops.md#board-receipt-boundary)。一般則の正本は README から既存 home へ参照し、Phase 2 の移設は未実施。

- [ ] Phase 2 の trigger 監視 (= DESIGN の表): Codex runner Pilot A 開始で `multi-session-coordination.md` と `codex/` を移設
- [ ] file が 15 本を超えたら index 生成 tool を共用化 (DESIGN)

## 2026-09-06 (夜): 昇格 station + 公開 skeleton + 見本 campaign + 受領で見えた道具の穴 3 件

- **昇格 station** (owner 指示「作った script も含めて知見をできるだけ上層に、毎度」): campaign state に終端 `hoisted` (retro front matter `hoist:`)、`--surface` が記録まで 📤 を押す、`make-review-sandbox.py collect` は scratch/ も copy し既存注記を上書きしない、ops §3.5 `#hoist-station`、pvc §15 L。
- **システムの公開** (owner「システムの公開はみんなの役に立つのでは」): `template/` (clone して回せる骨格: CLAUDE / spec・retro 雛形 / QUEUE・improvements schema / hooks + shim / 無人 tick 手順、個人 path は placeholder) + `scripts/init-verification-repo.py` (展開 + git init + hook + selftest) + `examples/verification-repo/` (完結した見本 campaign 1 本 = qubit Helstrom 閉形式、check + foil + AUTO block + retro + hoist)。private に残るのは campaign の中身のみ。
- 受領で直した道具: report loader が `{items}` wrapper 受理 / sandbox campaign の所要は file mtime fallback / 2 回目の collect が注記を silent 上書き → 拒否。foil runner は Codex が fail-closed 化 (`64db7aa`)。
- 層1 規約: pvc §6 addendum (受領側 AI の手追認も AI-refuted、gate は owner の理解)、§14 kernel 18-21 + 第 3 経路 anchor (c3 worker hoist)、`docs/state-discrimination.md` + `scripts/state_discrimination.py` (Codex hoist)。
- 次: Phase 2 trigger 監視は不変。template の README pointer は landed。

## 決定ログ

- **2026-09-06: 新設** — 判断は DESIGN.md (分離の理由 / Phase 1 の範囲 / 移し方 = format-patch 履歴 import / stub + forwarder / Phase 2 trigger)

## 2026-09-06 (後半): GitHub 公開 + baseline + 呼び元切替 完了

- `odakin/ai-collaboration` public 作成・push。 `secure-new-repo.sh --code` = Dependabot / public-repo marker (leak gate stub) / CodeQL・branch protection は script の baseline 通り。 Semgrep + auto-merge workflow も同日 push 済 (= remote が SSH なので gh の workflow scope は不要だった、 secure-new-repo.sh の注意は HTTPS token 経路の話)。 Dependabot の actions bump PR 2 本は auto-merge を arm。
- claude-config 側 = stub 3 (anchor 33 保持) + forwarder 4、 commit 済。 owner 側呼び元は全部新 path。 selftest = 新 path 4 本 / forwarder 4 本 / shim 3 本 すべて PASS。
- 次 = Phase 2 判断 (DESIGN の trigger 表)。 CI 初回 run は次の code push で確認。
