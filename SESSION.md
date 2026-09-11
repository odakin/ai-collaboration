# SESSION.md — ai-collaboration

## 現状 (2026-09-06)

repo 新設 (Phase 1 = claude-config からの分離)。conventions 3 本 + scripts 4 本を git 履歴つきで移設、骨格 (CLAUDE / DESIGN / README / LICENSE / .gitignore / CI) を作成、claude-config 側は stub + forwarder、呼び元 (owner の private 検証 repo の shim / odakin-prefs check・SKILL) は本 repo の path へ。

## 残タスク

- 状態識別の数式と道具を追加。入口 = [証明と利用範囲](docs/state-discrimination.md)、[library](scripts/state_discrimination.py)、[検証時の certificate](conventions/physics-verification-cycle.md#state-discrimination-certificates)。reporter は未知の foil crash と marker 後の非ゼロ終了を失敗にし、`--run` の失敗を呼び元へ返す。実装判断 = DESIGN.md。

- Session 宛て board との受領経路の接続は [verification-cycle-ops](conventions/verification-cycle-ops.md#board-receipt-boundary)。一般則の正本は README から既存 home へ参照し、Phase 2 の移設は未実施。

- [ ] Phase 2 の trigger 監視 (= DESIGN の表): Codex runner Pilot A 開始で `multi-session-coordination.md` と `codex/` を移設
- [ ] index 生成 tool の共用化 — **trigger 到達 (2026-09-11、 scripts 19 本)**。 それまで README / CLAUDE.md の一覧は手で揃える (DESIGN「index は当面手書き」)

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

## 2026-09-07: 盲検 reviewer 側の hoist (private paper repo の round-2 review、 reviewer session が受領後に昇格)

- scripts 3 本 (`hpd-credible-level.py` / `svg-contour-extract.py` / `floquet-monodromy.py`、 NumPy/SciPy のみ、 selftest 9/9 PASS)、 pvc §17 `#referee-side-kernels` (道具 3 + kernel 5)、 cold-eyes §1(b) 実測追補 + §4 受領後の reviewer session、 CLAUDE / README の一覧。 instance (原稿・reviewer scratch 11 本・promotion note・refs 登録) は owner の private repo 側。
- 次: 変更なし (Phase 2 trigger 監視)。 scripts は 8 本 (index 手書きの再訪 trigger 15 本には未達)。

## 2026-09-08: AI 原稿改稿の意図記録 (edit-intent-record.md + check-edit-intent.py、 spawn worker が起票 spec から実装)

- 起源: 別ベンダー AI の 89 hunk / 474 行改稿を 1 週間後に人手で棚卸しし、 決定超過 2 件 + 棚卸し自身の誤分類 1 件が出た (owner「編集の意図を記録してなかったのは問題」)。 owner の私的 paper repo に instance (README 更新規律 / SOT 行 / shim)、 依頼側は agent-board CLAUDE + owner 層の board 規律に 1 段落ずつ。
- 規約 = `conventions/edit-intent-record.md` (規則 8 = 1 pass 1 sidecar / 3 列 / 裁量は明示 / 削除 verbatim + 共著者本文の単独削除禁止 / 量の指示 / commit 前 gate / 意図は 1 行 / 遡及しない、 sidecar 形式、 検査項目と人間の床、 依頼 spec の 3 行、 routing、 実例 ledger)。 pvc §16 に routing 1 文。
- 道具 = `scripts/check-edit-intent.py` (--scaffold = diff から hunk 行 + 位置 + 削除 verbatim を生成、 検査 = 12 項目 PASS/FAIL + INFO 量の指示、 --selftest 20 checks = parser 4 + 合成 repo の PASS 1 + foil 11 + 未記入 scaffold は通らない)。 実 diff (88 hunk) で scaffold → 位置・被覆・verbatim PASS、 未記入行で FAIL を確認。
- 次: scripts は 9 本 (再訪 trigger 15 本には未達)。 効果判定は次の AI 実装 pass で sidecar が「裁量」 を何件表に出すかを見る (rubric 事前登録: 決定超過が受領前に裁量枠で出れば効いた、 事後棚卸しで見つかれば効いていない)。

## 2026-09-11: 盲検 reviewer 側の hoist 第 4 回 (private paper repo の 1-loop 誘導作用の referee、 reviewer session が受領後に owner 指示で昇格)

- scripts 3 本 (`one_loop_pole.py` / `dirac_algebra.py` / `heat_kernel_a4.py`、 selftest 3/3 PASS、 `985fc67`)、 CI の install に sympy。 pvc §17 に道具 3 行 + kernel 10–13 (Ward 恒等式は不変汎関数で符号ごと検証 / 構造数えで「残差なし」 が自明か / 制限した背景での cross-check の死角 / Stückelberg mode の運動項の符号)。 記号計算の罠 3 型は claude-config `scientific-computing.md#exact-rational-pipelines`。 instance (sandbox の collect・shim・live audit・refs の notes) は owner の private repo 側。
- 同日並走の符号 anchor 再発防止 (`check-sign-anchors.py`) と同じ file 群を触るため、 相手の commit を待ってから追記した (staging-window race の回避)。 README / CLAUDE.md の script 一覧の漏れも補った (DESIGN「index は当面手書き」)。
- 次: index 生成 tool の共用化 (trigger 到達)。 Phase 2 の監視は不変。
