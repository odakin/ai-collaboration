# SESSION.md — ai-collaboration

## 現状 (2026-09-11)

論文の推敲 session (2026-09-11) から、 [`conventions/edit-intent-record.md`](conventions/edit-intent-record.md) §7 に 2 点を追加した。 gate をパイプの後ろに置かないことと、 Claude Code の Bash tool の最上位では `set -e` が効かないこと ([`#apply-then-record`](conventions/edit-intent-record.md#apply-then-record)、 実測つき)。 著者の手編集を carrier commit する前に、 確認した差分の hash を照合すること ([`#carrier-commit-hash`](conventions/edit-intent-record.md#carrier-commit-hash)、 項目 7)。

非有界 moment operator と有限観測窓の campaign から、一般化した検証規律と script 3 本を層1へ昇格し、multi-stage review の結果を受領する collect の欠落も修正した。判断と instance 境界は [DESIGN](DESIGN.md#unbounded-moment-hoist)、規律は [unbounded moment-domain audit](conventions/physics-verification-cycle.md#unbounded-moment-domain-audit)、道具の全数は [generated script index](scripts/README.md) から辿る。全 script の selftest、公開層 leak、entrypoint、生成索引の検査を通した。次の campaign は同規律の hoist station と生成索引を入口にする。

## 残タスク

- 状態識別の数式と道具を追加。入口 = [証明と利用範囲](docs/state-discrimination.md)、[library](scripts/state_discrimination.py)、[検証時の certificate](conventions/physics-verification-cycle.md#state-discrimination-certificates)。reporter は未知の foil crash と marker 後の非ゼロ終了を失敗にし、`--run` の失敗を呼び元へ返す。実装判断 = DESIGN.md。

- Session 宛て board との受領経路の接続は [verification-cycle-ops](conventions/verification-cycle-ops.md#board-receipt-boundary)。一般則の正本は README から既存 home へ参照し、Phase 2 の移設は未実施。

- [ ] Phase 2 の trigger 監視 (= DESIGN の表): Codex runner Pilot A 開始で `multi-session-coordination.md` と `codex/` を移設
## 2026-09-12: 記法の一括改稿を盲検検査させた回 (第 6 回) — 「読む」 を「逆写像する」 に置き換えた

対象が主張でなく**原稿全体にわたる記法の一括改稿**だった初めての round。 owner 指示「script も知見もできるだけ上層へ」 で reviewer session がそのまま hoist した ([#hoist-station](conventions/verification-cycle-ops.md#hoist-station))。 kernel 9 (worker に `HANDOFF.md` を書かせる) が入った後の最初の round で、 **hoist の材料が事後指示でなく sandbox の中から出てきた** = 9 が想定どおり効いた。

- **道具 2 本** (全数は [generated script index](scripts/README.md)): [`check-rename-purity.py`](scripts/check-rename-purity.py) = 「機械的な置換だけ」 の主張を、 目視でなく **new→old の逆写像を後版に当てて前版と diff** して検査する (純粋な置換は畳まれ、 残差だけが非機械変更の全部)。 実データで 85 変更行 → 70 行が畳まれ、 残差 15 行が人手の hunk 単位棚卸しと完全一致した。 `--forbid` で旧綴りの残存を comment 行まで走査。 [`compare-tex-builds.py`](scripts/compare-tex-builds.py) = 2 版の組版 gate (log の**折返しを復元**してから新規 overfull を名指し / `.aux` の label→頁 drift / 配布 PDF の再現証明)。 foil = 前者は renamed 行に仕込んだ符号反転が残差に出ること、 後者は 79 桁で折れた警告が復元されること。
- **kernel 17-21** ([#referee-side-kernels](conventions/physics-verification-cycle.md#referee-side-kernels)): 逆写像で読む量を残差に落とす / **配布物は自分の build が再現することを証明してから観察を相手の source に帰属する** / **総頁数の一致は組版が動いていない証拠でない** / 未記載の規約は印字済みの兄弟結果を control に pin し誤った向きでも走らせて落ちることを確認する (規約版 foil、 kernel 10 の裏面) / **機械 pass に混じった散文 1 文がその pass で最も risk の高い hunk** (実測ではそれが同定文で、 厳密には成り立たない強さで、 必要な位置より後ろに在った)。
- **組版 gate の補強**: [`#build-gate`](conventions/edit-intent-record.md#build-gate) の「頁数・未定義参照・error 0」 に、 **頁数は総和なので相殺する**ことと `.aux` 比較を追記。 overfull を pass 中の gate にしない規律 ([`#overfull-not-a-gate`](conventions/edit-intent-record.md#overfull-not-a-gate)) は不変 — 新 kernel は**報告**であって修正ではない。
- **sandbox recipe への差し戻し** ([#spec-leakage](conventions/cold-eyes-isolation.md#spec-leakage) 追補): 規約の定義 (記号・添字・**運動量の向き**) は verdict でないので **spec に書いてよく、 書かないと reviewer が逆算に 1 pass 燃やす** / §2-2 の `.aux` 同梱は手書きの label 一覧で代用しない、 比較を課すなら**両版**の `.aux` / **射程を 1 行で宣言する** (変更の外側の既存不整合を finding にしてよいか。 第 6 回の reviewer は severity を自作して逃がした)。
- 個人層の instance (原稿・検査結果・未手当表) は該当 paper repo に残置。 SoT registry に 7 topic 登録済。

## 2026-09-12: 盲検書面審査 ×4 の hoist — 同じ道具を 4 回書き直していたことが見えた回

申請書 2 本 × 独立した審査員 2 名の封じた sandbox ([`cold-eyes-isolation.md#sealed-sandbox`](conventions/cold-eyes-isolation.md#sealed-sandbox)) を受領後、4 本の `HANDOFF.md` を突き合わせた。**4 sandbox が独立に INSPIRE client を、2 sandbox が図の軸 digitize と窓×減衰の閉形式を書いていた** = 層1 判断基準「2 campaign 目で同じ形」 ([#hoist-station](conventions/verification-cycle-ops.md#hoist-station) 2) が 3 つ同時に成立していた。道具は [generated script index](scripts/README.md) から辿る: 本 repo に [`window-decay-closed-form.py`](scripts/window-decay-closed-form.py) (erfc 閉形式・閾値・(1/2)e^{-n²/2}。**起草時に書いた「閾値での比は常に 1/2」 は selftest が反証した** — 振動位相があると `sqrt(1+erfi(Eτ/√2)²)/2` になる) と [`inspire-bibliography.py`](scripts/inspire-bibliography.py) (kibanB-A が 4 本を統合)、raster 図の読み戻しは `claude-config/scripts/read-plot-axes.py` (houga-A)。vector 版 [`svg-contour-extract.py`](scripts/svg-contour-extract.py) と相互参照を張った (**両者が互いを知らずに書かれたのが重複の原因**)。

⚠️ **hoist を 4 session 並列でやると SoT が競る** ([#hoist-station](conventions/verification-cycle-ops.md#hoist-station) は「受領側 1 session が直列」 と書いてある = そのとおりだった)。実際に `kakenhi-proposal.md` を 3 session が同時に編集し、`git commit -- <path>` でも**他人の非 path 指定 commit が自分の hunk を吸う**現象が 3 回起きた。回避できたのは lane を宣言して file 単位で時間分割したから。新しい規律 = `multi-session-coordination.md#absence-check-staleness` (「既存被覆は無い」 の調査は並列編集下で数分で腐るので、分担宣言では調査結果を渡さず「足す前に引き直して」 と渡す)。

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
- 追補 (同日): HANDOFF (d) の spec の穴 2 件 (用語定義の例 = tadpole、 label → 印字番号の `.aux` 同梱) を REVIEW-SPEC 雛形と cold-eyes §2 へ。 pvc kernel 11・12 の例示から原稿固有の計数と原稿の文言を外した (公開履歴には前の文面が残る)。 DESIGN の 09-07 節に sympy 依存と境界を追記。 kernel 14 (多添字の場の横・縦は分解の添字を書く、 HANDOFF (b) 9) を追加。 ops `#hoist-station` 3 に公開層の例示の内容走査を、 claude-config `shell-env.md#claude-issued-shell-commands` に zsh の単語分割で走査対象を取り違えた件を追記。
- 次: index は同日の別 session が生成へ移した (DESIGN `#script-index-generation`、 3 本も収録済)。 Phase 2 の監視は不変。

## 2026-09-11: 符号 anchor の engine (`check-sign-anchors.py`) + `--readers`

- 起源: private paper repo で、 有効作用の全体符号が逆のまま検査 fleet が全 PASS した (fleet は全体反転に不変で、 見分けたのは外部の絶対量に結ぶ anchor だけ)。 engine = 登録簿 (印字量 → 外部 anchor → 全体反転 foil) の coverage / `--run` (foil の歯を end-to-end で、 traceback は歯に数えない) / `--fleet-scan` / `--deferrals` (carrier の無い「規約差」 の ratchet)、 `164d762`。 規則 = claude-config `paper-audit.md#absolute-sign-external-anchor` / `#convention-difference-closure`、 pvc §3 `#global-flip-foil`。
- 追補 (同日、 owner「スクリプトと知見をなるべく上層に」): `--readers` = fleet の各検査が原稿 file を実行時に何回開くか (audit hook、 resolved path で比較、 子 process は数えない = 下限)。 source の grep は docstring の言及で過大に数える (同じ repo で grep 16 本 / 実行時 1 本)。 実 repo では 15 本中 3 本 (うち 2 本は今回足した anchor)。 selftest 27。 使い方 = CLAUDE.md の 1 行。
- 次: 変化なし (Phase 2 の監視)。

## 2026-09-12: 相手側の AI への作業委譲 (`delegated-work-packages.md`)

- 起源: 卒論を共著の国際誌論文に育てる解析 (50 年の観測データ、主実行者 = 学生本人 + その AI) を 15 本の作業書に分割した owner session。判断 (定義・手法・閾値・地点選定・解釈) を依頼側の SPEC に固め、実行だけを 1 セッション 1 本の WP に出す形。
- 規約 = `conventions/delegated-work-packages.md` (§1 何を分離するか / §2 常設 3 層 + WP / §3 WP の 7 要素 / §4 **受入基準は依頼側の独立実装で埋める** = 交差検証を仕組みに組み込む、書けないなら合成データの回収 test / §5 全部書いて ready だけ着手 + 確定待ち項目 / §6 書き込み zone / §7 結果ノートと「仕様への提案」 が仕様改訂の唯一の入口 / §8 解釈・基準値の書き換え・仕様外解析は渡さない / §9 使わない場面 / §10 起源と evidence base 1 例)。README / CLAUDE.md の一覧、DESIGN に判断。
- 同 session の姉妹 hoist (claude-config 側): `jma-obsdl-download.md` に一次資料の品質列表と長期系列 QC 4 点 (行数の暦検算・品質符号の分布・痕跡時間 15%・記録分解能の年代)、`paper-audit.md` に分布形の主張と venue 較正の 2 anchor。
- 次: 変化なし (Phase 2 の監視)。効果判定 = 最初の 2〜3 本の結果ノートで「受入基準の判定表」 と「仕様への提案」 が実質を持つか (儀式化していたら基準の本数を減らす)。
