# SESSION-archive — ai-collaboration

> 📦 SESSION.md から移した日付つき節 (grep 専用、 verbatim)。 現在地は SESSION.md。

## 2026-09-28 SESSION.md の日付つき節を verbatim MOVE (形の契約 = 案件ごとの現在地、 層1 claude-config/CONVENTIONS.md#session-no-durable-record、 道具 = migrate-session-shape.py)

## 現在地：CI の依存 (2026-09-23)

CI の selftest に PyMuPDF を足した (`e992822`)。 `scripts/pdf-locator-grep.py` の selftest が `fitz` を使い、 入れていない runner で red が続いていた。 新しい script が selftest で import する package は、 同じ commit で `.github/workflows/checks.yml` の `pip install` にも足す。


## 現状 (2026-09-11)

隔離の出口 (2026-09-14): 封じた sandbox の reviewer session が「知見を上層に」 の口頭指示で公開 doc に審査対象の件数・日付を書いた回の再点検から、 [`conventions/cold-eyes-isolation.md#post-check`](conventions/cold-eyes-isolation.md#post-check) に「hoist の中身 — 出口の規律」 (reviewer は公開 repo を直接編集せず `scratch/hoist-candidates.md` に一般形で渡す)、 [`scripts/make-review-sandbox.py`](scripts/make-review-sandbox.py) の sandbox CLAUDE.md template に rule 9 (exit rule)、 [`conventions/verification-cycle-ops.md#hoist-station`](conventions/verification-cycle-ops.md#hoist-station) 3 に同じ 1 文を追補。 例示から相対時間の日付を外した。

論文の推敲 session (2026-09-11) から、 [`conventions/edit-intent-record.md`](conventions/edit-intent-record.md) §7 に 2 点を追加した。 gate をパイプの後ろに置かないことと、 Claude Code の Bash tool の最上位では `set -e` が効かないこと ([`#apply-then-record`](conventions/edit-intent-record.md#apply-then-record)、 実測つき)。 著者の手編集を carrier commit する前に、 確認した差分の hash を照合すること ([`#carrier-commit-hash`](conventions/edit-intent-record.md#carrier-commit-hash)、 項目 7)。

非有界 moment operator と有限観測窓の campaign から、一般化した検証規律と script 3 本を層1へ昇格し、multi-stage review の結果を受領する collect の欠落も修正した。判断と instance 境界は [DESIGN](DESIGN.md#unbounded-moment-hoist)、規律は [unbounded moment-domain audit](conventions/physics-verification-cycle.md#unbounded-moment-domain-audit)、道具の全数は [generated script index](scripts/README.md) から辿る。全 script の selftest、公開層 leak、entrypoint、生成索引の検査を通した。次の campaign は同規律の hoist station と生成索引を入口にする。

論文の推敲 session (2026-09-13、原稿の通読 pass 40 本) から、 著者の並行編集の前検査を道具にした: [`scripts/editor-guard.py`](scripts/editor-guard.py) (`check` = 未 commit 変更で exit 3 + 差分 hash 保存、 `carrier` = 読んだ差分と同じ hash のときだけ commit)。 [`edit-intent-record.md` 規則 9](conventions/edit-intent-record.md#editor-open-precheck) に破られ方 (`git status --short` は exit 0 で鎖を止めない、 2 回) と「見つけても自動 carrier しない」、 規則 1 にパイプ後 gate の再発を追記。 同日夜に 3 例目 (検査を別の tool 呼び出しにした間に著者が保存) → `mark` / `verify` を足し、 規則 9 を「書き込みと commit を、 それぞれ検査と同じ command 行に置く」 に改めた。 同日夜 = [`verification-cycle-ops.md#hoist-station`](conventions/verification-cycle-ops.md#hoist-station) 3 に、 公開 repo の Tier D (未公開文書の逐語を止める gate) への pointer。 同日夕 = script 2 本 [`torsion_irreducible.py`](scripts/torsion_irreducible.py) (torsion の既約分解と Einstein–Cartan + Holst の二次形式、 消去因子、 規格化 foil を selftest に同梱) / [`inspire-phrase-frequency.py`](scripts/inspire-phrase-frequency.py) (呼び名の文献件数を title と全文で横並び) と、 [`physics-verification-cycle.md#scratch-foil-not-bundled`](conventions/physics-verification-cycle.md#scratch-foil-not-bundled) (scratch で回した foil は同梱ではない)。

論文の推敲 session (2026-09-13 夜〜09-14、ledger 項目 123–159) からの昇格: [`scripts/torsion_irreducible.py`](scripts/torsion_irreducible.py) に convention maps 3 つ (weight-½ torsion と contorsion の $T_{[\cdot]}=-K_{[\cdot]}$、接続の添字順で unit-weight torsion が ±2 倍、form 言語の Immirzi 項 = Holst 形の −¼) を selftest 込みで追加 / [`scripts/check-sign-anchors.py`](scripts/check-sign-anchors.py) に foil の literal がずれた時と閉じた deferral の直し方 / 非盲検の通読 spec の雛形 [`template/READTHROUGH-SPEC-non-blind.md`](template/READTHROUGH-SPEC-non-blind.md) (受領手順つき、初回 11 件全部真) / [`conventions/edit-intent-record.md`](conventions/edit-intent-record.md) §7 規則 11–13 (著者の疑問形は指示でない、diff の基準は著者の完成版、identity は hash を宣言する file を全部) と規則 8 の順序 (ledger → `--fill`)。

例示の見直し (2026-09-13〜14): 物理 script 4 本 (`nstar-fixed-point` / `floquet-monodromy` / `expanding-mode-growth` / `dilaton-spectator-growth`) の既定値・usage の例・selftest の pin を合成値に替え (pin は再計算)、`hpd-credible-level` と `svg-contour-extract` の例の点と、`gpt_measurements` の由来の段落を一般形にした。script を層1 へ上げるときの手順 = [`verification-cycle-ops.md#hoist-synthetic-parameters`](conventions/verification-cycle-ops.md#hoist-synthetic-parameters)。

foil の歯の確かめ方 (2026-09-14): [`physics-verification-cycle.md#foil-teeth-per-fix-part`](conventions/physics-verification-cycle.md#foil-teeth-per-fix-part) = 修正の一部だけを外した mutant ごとに、 落ちるはずの check が落ち、 残るはずの check が PASS のまま (= foil の独立性) を見る。 機械は claude-config の `scripts/check-foil-teeth.py` + `<script>.mutants.json` (最初の spec で、 一致数のラベルなのに別の検査で落ちていた foil と、 状態を共有していた foil を見つけた)。

未公表の結果の扱い (2026-09-14): `physics-verification-cycle.md` §14 を一般則だけに書き直し、 campaign 固有の構成と結果を書いた節と、 それを実装した `gpt_measurements.py` の関数・docstring を owner の非公開の検証 repo へ移した (`a5738fe`)。 盲検の規約と SESSION の例から、 審査を受けた文書の件数・日付・sandbox の名前を外した (`e691a5a`)。


## 2026-09-15: 自分が辿り着いた構造の先行研究照合 — 主張でなく「操作」 で引く

- **kernel 19** ([#prior-art-by-operation](conventions/physics-verification-cycle.md#prior-art-by-operation)): 引く前に**操作を分類する** (同じ言い方が 2 つの別操作を指していると、文献のほぼ全部が片方に集まり、もう片方はその論文の**極限の段落**に 1 つだけ在る) / 検索語は主張でなく**手つき**の語 / **abstract では必要条件が読めない** (その構成に何が要るかは本文の最初の数式にある。確かめずに「既出」 とも「未踏」 とも言わない) / **数往復で辿り着いた構造は先行研究の 1 段落に既出のことがある** ので、結論が出た瞬間に最も近い論文の極限・特殊ケース・脚注を開く / 結果は **既出 / 未踏 (検索範囲を明記) / 自分の外挿 (⚠️ + 未検算)** の 3 つに仕分けて書く / 書誌は `inspire-bibliography.py` で照合してから書く。
- 自著側の対 = layer 1 [`paper-audit.md#invariant-structure-before-asymmetry-claim`](../claude-config/conventions/paper-audit.md#invariant-structure-before-asymmetry-claim) (「X だけが運動項を持つ / X は補助場」 と言う前に背景まわりの 2 次形式を書く)。起源は同じ回で、**先に 2 次形式を書いていれば往復も文献調査も 1 回で済んだ**。


## 2026-09-12: 記法の一括改稿を盲検検査させた回 (第 6 回) — 「読む」 を「逆写像する」 に置き換えた

対象が主張でなく**原稿全体にわたる記法の一括改稿**だった初めての round。 owner 指示「script も知見もできるだけ上層へ」 で reviewer session がそのまま hoist した ([#hoist-station](conventions/verification-cycle-ops.md#hoist-station))。 kernel 9 (worker に `HANDOFF.md` を書かせる) が入った後の最初の round で、 **hoist の材料が事後指示でなく sandbox の中から出てきた** = 9 が想定どおり効いた。

- **道具 2 本** (全数は [generated script index](scripts/README.md)): [`check-rename-purity.py`](scripts/check-rename-purity.py) = 「機械的な置換だけ」 の主張を、 目視でなく **new→old の逆写像を後版に当てて前版と diff** して検査する (純粋な置換は畳まれ、 残差だけが非機械変更の全部)。 実データで 85 変更行 → 70 行が畳まれ、 残差 15 行が人手の hunk 単位棚卸しと完全一致した。 `--forbid` で旧綴りの残存を comment 行まで走査。 [`compare-tex-builds.py`](scripts/compare-tex-builds.py) = 2 版の組版 gate (log の**折返しを復元**してから新規 overfull を名指し / `.aux` の label→頁 drift / 配布 PDF の再現証明)。 foil = 前者は renamed 行に仕込んだ符号反転が残差に出ること、 後者は 79 桁で折れた警告が復元されること。
- **kernel 17-21** ([#referee-side-kernels](conventions/physics-verification-cycle.md#referee-side-kernels)): 逆写像で読む量を残差に落とす / **配布物は自分の build が再現することを証明してから観察を相手の source に帰属する** / **総頁数の一致は組版が動いていない証拠でない** / 未記載の規約は印字済みの兄弟結果を control に pin し誤った向きでも走らせて落ちることを確認する (規約版 foil、 kernel 10 の裏面) / **機械 pass に混じった散文 1 文がその pass で最も risk の高い hunk** (実測ではそれが同定文で、 厳密には成り立たない強さで、 必要な位置より後ろに在った)。
- **組版 gate の補強**: [`#build-gate`](conventions/edit-intent-record.md#build-gate) の「頁数・未定義参照・error 0」 に、 **頁数は総和なので相殺する**ことと `.aux` 比較を追記。 overfull を pass 中の gate にしない規律 ([`#overfull-not-a-gate`](conventions/edit-intent-record.md#overfull-not-a-gate)) は不変 — 新 kernel は**報告**であって修正ではない。
- **sandbox recipe への反映** ([#spec-leakage](conventions/cold-eyes-isolation.md#spec-leakage) 追補): 規約の定義 (記号・添字・**運動量の向き**) は verdict でないので **spec に書いてよく、 書かないと reviewer が逆算に 1 pass 燃やす** / §2-2 の `.aux` 同梱は手書きの label 一覧で代用しない、 比較を課すなら**両版**の `.aux` / **射程を 1 行で宣言する** (変更の外側の既存不整合を finding にしてよいか。 宣言が無いと reviewer が severity を自作して逃がす = 実測)。
- **掬い残しの回収 (owner「スクリプトはなるべく掬い上げようぜ」)**: (a) `--census '<regex>'` = 記号族の綴りごとに出現数・行範囲・**住んでいる節**を出す (2 綴りが別の節に居るのが一目で分かる = 純粋性検査では出ない残り物、 [`paper-audit.md#notation-rename-sweep`](../claude-config/conventions/paper-audit.md#notation-rename-sweep) 4 の機械化)。 (b) `--build <REV>:<file>.tex` = `git archive` で版ごと取り出して組む build driver。 [`#frozen-revision-build`](conventions/edit-intent-record.md#frozen-revision-build) は規律だけあって道具が無かった (= `#documented-not-wired`)。 selftest に「live の図を差し替えても revision build はその版の図で組む」 foil 入り。
- **09-13 著者裁定を受けた較正** (報告した組版 2 件が両方とも据え置き): kernel 22 = [`#typesetting-severity-calibration`](conventions/physics-verification-cycle.md#typesetting-severity-calibration) (draft の盲検で組版の見た目に severity を付けない。 組版は事実だけ別表) / hoist の順序 = [`#hoist-after-ruling`](conventions/verification-cycle-ops.md#hoist-after-ruling) (受領側の裁定が出る前に finding を規則として上げない。 先に上げてよいのは道具と手順だけ)。 書換え・commit の道具 (置換 pair の契約・origin worktree からの commit・push 範囲の監査) は層1 claude-config 側 = [`DESIGN.md#link-guard-and-safe-edit-tools`](../claude-config/DESIGN.md#link-guard-and-safe-edit-tools)。
- 個人層の instance (原稿・検査結果・未手当表) は該当 paper repo に残置。 SoT registry に 10 topic 登録済 (09-13 に +2 = 上の 2 anchor)。


## 2026-09-12: 盲検書面審査の hoist — 同じ道具を何度も書き直していたことが見えた回

複数の文書をそれぞれ独立した審査員の封じた sandbox ([`cold-eyes-isolation.md#sealed-sandbox`](conventions/cold-eyes-isolation.md#sealed-sandbox)) に渡し、受領後に各 `HANDOFF.md` を突き合わせた。**全 sandbox が独立に INSPIRE client を、一部の sandbox が図の軸 digitize と窓×減衰の閉形式を書いていた** = 層1 判断基準「2 campaign 目で同じ形」 ([#hoist-station](conventions/verification-cycle-ops.md#hoist-station) 2) が 3 つ同時に成立していた。道具は [generated script index](scripts/README.md) から辿る: 本 repo に [`window-decay-closed-form.py`](scripts/window-decay-closed-form.py) (erfc 閉形式・閾値・(1/2)e^{-n²/2}。**起草時に書いた「閾値での比は常に 1/2」 は selftest が反証した** — 振動位相があると `sqrt(1+erfi(Eτ/√2)²)/2` になる) と [`inspire-bibliography.py`](scripts/inspire-bibliography.py) (sandbox の 1 つの実装を元に統合)、raster 図の読み戻しは `claude-config/scripts/read-plot-axes.py` (別の sandbox の実装)。vector 版 [`svg-contour-extract.py`](scripts/svg-contour-extract.py) と相互参照を張った (**両者が互いを知らずに書かれたのが重複の原因**)。

⚠️ **hoist を複数 session 並列でやると SoT が競る** ([#hoist-station](conventions/verification-cycle-ops.md#hoist-station) は「受領側 1 session が直列」 と書いてある = そのとおりだった)。実際に `kakenhi-proposal.md` を 3 session が同時に編集し、`git commit -- <path>` でも**他人の非 path 指定 commit が自分の hunk を吸う**現象が 3 回起きた。回避できたのは lane を宣言して file 単位で時間分割したから。新しい規律 = `multi-session-coordination.md#absence-check-staleness` (「既存被覆は無い」 の調査は並列編集下で数分で腐るので、分担宣言では調査結果を渡さず「足す前に引き直して」 と渡す)。


## 2026-09-06 (夜): 昇格 station + 公開 skeleton + 見本 campaign + 受領で見えた道具の穴 3 件

- **昇格 station** (owner 指示「作った script も含めて知見をできるだけ上層に、毎度」): campaign state に終端 `hoisted` (retro front matter `hoist:`)、`--surface` が記録まで 📤 を押す、`make-review-sandbox.py collect` は scratch/ も copy し既存注記を上書きしない、ops §3.5 `#hoist-station`、pvc §15 L。
- **システムの公開** (owner「システムの公開はみんなの役に立つのでは」): `template/` (clone して回せる骨格: CLAUDE / spec・retro 雛形 / QUEUE・improvements schema / hooks + shim / 無人 tick 手順、個人 path は placeholder) + `scripts/init-verification-repo.py` (展開 + git init + hook + selftest) + `examples/verification-repo/` (完結した見本 campaign 1 本 = qubit Helstrom 閉形式、check + foil + AUTO block + retro + hoist)。private に残るのは campaign の中身のみ。
- 受領で直した道具: report loader が `{items}` wrapper 受理 / sandbox campaign の所要は file mtime fallback / 2 回目の collect が注記を silent 上書き → 拒否。foil runner は Codex が fail-closed 化 (`64db7aa`)。
- 層1 規約: pvc §6 addendum (受領側 AI の手追認も AI-refuted、gate は owner の理解)、§14 kernel 18-21 + 第 3 経路 anchor (c3 worker hoist)、`docs/state-discrimination.md` + `scripts/state_discrimination.py` (Codex hoist)。
- 次: Phase 2 trigger 監視は不変。template の README pointer は landed。


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


## 2026-09-11: 盲検 reviewer 側の hoist 第 4 回 (private paper repo の原稿の referee、 reviewer session が受領後に owner 指示で昇格)

- scripts 3 本 (`one_loop_pole.py` / `dirac_algebra.py` / `heat_kernel_a4.py`、 selftest 3/3 PASS、 `985fc67`)、 CI の install に sympy。 pvc §17 に道具 3 行 + kernel 10–13 (Ward 恒等式は不変汎関数で符号ごと検証 / 構造数えで「残差なし」 が自明か / 制限した背景での cross-check の死角 / Stückelberg mode の運動項の符号)。 記号計算の罠 3 型は claude-config `scientific-computing.md#exact-rational-pipelines`。 instance (sandbox の collect・shim・live audit・refs の notes) は owner の private repo 側。
- 同日並走の符号 anchor 再発防止 (`check-sign-anchors.py`) と同じ file 群を触るため、 相手の commit を待ってから追記した (staging-window race の回避)。 README / CLAUDE.md の script 一覧の漏れも補った (DESIGN「index は当面手書き」)。
- 追補 (同日): HANDOFF (d) の spec の穴 2 件 (用語定義の例 = tadpole、 label → 印字番号の `.aux` 同梱) を REVIEW-SPEC 雛形と cold-eyes §2 へ。 pvc kernel 11・12 の例示から原稿固有の計数と原稿の文言を外した (公開履歴には前の文面が残る)。 DESIGN の 09-07 節に sympy 依存と境界を追記。 kernel 14 (多添字の場の横・縦は分解の添字を書く、 HANDOFF (b) 9) を追加。 ops `#hoist-station` 3 に公開層の例示の内容走査を、 claude-config `shell-env.md#claude-issued-shell-commands` に zsh の単語分割で走査対象を取り違えた件を追記。
- 次: index は同日の別 session が生成へ移した (DESIGN `#script-index-generation`、 3 本も収録済)。 Phase 2 の監視は不変。


## 2026-09-11: 符号 anchor の engine (`check-sign-anchors.py`) + `--readers`

- 起源: private paper repo で、 有効作用の全体符号が逆のまま検査 fleet が全 PASS した (fleet は全体反転に不変で、 見分けたのは外部の絶対量に結ぶ anchor だけ)。 engine = 登録簿 (印字量 → 外部 anchor → 全体反転 foil) の coverage / `--run` (foil の歯を end-to-end で、 traceback は歯に数えない) / `--fleet-scan` / `--deferrals` (carrier の無い「規約差」 の ratchet)、 `164d762`。 規則 = claude-config `paper-audit.md#absolute-sign-external-anchor` / `#convention-difference-closure`、 pvc §3 `#global-flip-foil`。
- 追補 (同日、 owner「スクリプトと知見をなるべく上層に」): `--readers` = fleet の各検査が原稿 file を実行時に何回開くか (audit hook、 resolved path で比較、 子 process は数えない = 下限)。 source の grep は docstring の言及で過大に数える (同じ repo で grep の数は実行時の十倍以上)。 実 repo では原稿を開く検査は少数で、 その多くは今回足した anchor だった。 selftest 27。 使い方 = CLAUDE.md の 1 行。
- 次: 変化なし (Phase 2 の監視)。


## 2026-09-12: 相手側の AI への作業委譲 (`delegated-work-packages.md`)

- 起源: 卒論を共著の国際誌論文に育てる解析 (50 年の観測データ、主実行者 = 学生本人 + その AI) を 15 本の作業書に分割した owner session。判断 (定義・手法・閾値・地点選定・解釈) を依頼側の SPEC に固め、実行だけを 1 セッション 1 本の WP に出す形。
- 規約 = `conventions/delegated-work-packages.md` (§1 何を分離するか / §2 常設 3 層 + WP / §3 WP の 7 要素 / §4 **受入基準は依頼側の独立実装で埋める** = 交差検証を仕組みに組み込む、書けないなら合成データの回収 test / §5 全部書いて ready だけ着手 + 確定待ち項目 / §6 書き込み zone / §7 結果ノートと「仕様への提案」 が仕様改訂の唯一の入口 / §8 解釈・基準値の書き換え・仕様外解析は渡さない / §9 使わない場面 / §10 起源と evidence base 1 例)。README / CLAUDE.md の一覧、DESIGN に判断。
- 同 session の姉妹 hoist (claude-config 側): `jma-obsdl-download.md` に一次資料の品質列表と長期系列 QC 4 点 (行数の暦検算・品質符号の分布・痕跡時間 15%・記録分解能の年代)、`paper-audit.md` に分布形の主張と venue 較正の 2 anchor。
- 次: 変化なし (Phase 2 の監視)。効果判定 = 最初の 2〜3 本の結果ノートで「受入基準の判定表」 と「仕様への提案」 が実質を持つか (儀式化していたら基準の本数を減らす)。


## 2026-09-13: `--intents` の JSON 直渡し + 記録道具の競合への pointer

- `scripts/check-edit-intent.py --fill` の `--intents` が、JSON file の path に加えて `{` で始まる JSON そのものを受ける (file path だと思わず文字列を渡して止まったため。selftest +2、shim 経由の `--fill` で 12/12 を確認)。[`#fill-mode`](conventions/edit-intent-record.md#fill-mode) の説明も合わせた。
- [`#apply-then-record`](conventions/edit-intent-record.md#apply-then-record) に、live の HEAD を書き込み時に実測する記録道具が並列 session の commit を自分の pass として記録する件への pointer (正本 = claude-config `multi-session-coordination.md#measured-record-race`)。
- 次: 変化なし (Phase 2 の監視)。

## pointer 化退避 (2026-11-18): 検証の再利用道具の現在地 5 節

SESSION.md の行数の警告を払うため、 次に使うときの入口だけを持つ 5 節を全文のまま移した (SESSION には 1 行ずつの入口 = 「検証の再利用道具」 の節)。

## 現在地：Lindblad 観測量の検査

再利用 API と合成 selftest を整備した。次の利用では、
[作用空間とチャネルの境界](docs/lindblad-observables.md)を確認してから、
[生成索引](scripts/README.md)の module を使う。独立検査の原本は呼び元で保持する。

## 現在地：有限積分・外積・式の転記

共通道具を追加した。再利用時は [実装の分担](DESIGN.md#finite-vacuum-and-transcription-tools) と
[主張の依存関係・物理的な解釈](conventions/physics-verification-cycle.md#claim-dependencies-and-observables) を読み、
[生成索引](scripts/README.md)から該当 module へ進む。caller の量子測度・適用範囲・個別判定は各 project が持つ。
次の利用では必要な module の selftest を通し、独立検査の原本を共通実装への別名に置き換えない。

## 現在地：共変作用・密度frameの検査module

作用の等価性・境界項・有限多項式性を再利用可能な形にした。
入口は [検証kernel](conventions/physics-verification-cycle.md#action-equivalence-and-polynomiality)、
実装判断は [DESIGN](DESIGN.md#covariant-action-audit-hoist)、コードは生成された
[script索引](scripts/README.md)から辿る。次の利用時は、制限背景の必要条件と一般共変な十分条件、
有限ambient polynomialと場依存制約を別々に判定する。個別論文の判定はこのpublic repoに置かない。

## 現在地：レビュー成果物の不変性確認

再開前後の比較には [snapshot helper](scripts/review-artifact-snapshot.py) を使える。次の利用時は baseline の対象と writer の停止を確認し、追加物の回収範囲は呼び元で指定する。運用入口は [CLAUDE](CLAUDE.md)。

## 現在地：事前登録した比較実験の受領

受領時に照合する範囲を [共通手順](conventions/physics-verification-cycle.md#preregistered-comparison-receipt) に整理した。
次の比較実験では、登録した版と判定規則、匿名対応表の固定時点、部分確認した指摘の加点単位を仕様で確かめる。
個別の得点・採用判断・独立検算の原本は呼び元が持つ。

## pointer 化退避 (2026-11-27): 掲示板などの現在地 14 節と決定ログ

## 現在地：Codex の書き込みを Claude 側に届ける網

Codex の書き込みは SendMessage で届かないので、 Claude 側の Stop の検査 `board/board-post-reach-check.py` が「見張りを張り直したか」 と「掲示板がこの session の番と言う依頼」 を見る ([契約](board/CONTRACT.md#codex-reach))。
`GET /due` の `waiting_event` で、 拾わない行も番の session に 1 行知らせられる ([契約](board/CONTRACT.md#viewer-handoff-queue))。
次 = 既存の送り忘れの検査 (observe のまま) を block に上げるかを、 observe の記録で決める。

## 現在地：研究の対話係の窓の起動文 (`--dialogue`)

`request` / `launch` の `--dialogue` で、 対話係の窓に渡す起動文から commit・push の行と「この窓で本人に問わない」 の行を外し、
repo の file を書かず置いた場所を依頼元に渡す文にする ([契約](board/CONTRACT.md#dialogue-worker-handoff)、 分担の正本 =
claude-config `multi-session-coordination.md#research-dialogue-and-conductor`)。 題の末尾が同じ model・effort なら二度足さない。
owner の掲示板の request desk が依頼元の写しと組版の係の役 id (`AGENT_BOARD_DIALOGUE_DESK`) を返すと、 渡し先は依頼元でなくその係になる ([契約](board/CONTRACT.md#dialogue-desk))。
次 = 係つきで起こした最初の対話係の窓で、 渡しが係に届いたかを見る (試験は起動文の file・start_session の引数・本物の engine の空回しまで)。

## 現在地：request の完了条件の頁数・overfull の注意

`request` の `--acceptance` に値の無い頁数か overfull があると、 書いた側に 1 行の注意を出す (止めない、 どの掲示板でも。
[契約](board/CONTRACT.md#acceptance-value-check)、 規則 = [組版の関門](conventions/edit-intent-record.md#page-count-not-a-gate))。
次 = 規則そのものを語る request (この注意の話をする依頼) にも出る誤検出が、 実際の依頼で邪魔になるかを見る。 邪魔なら判定 (`board/board_acceptance.py`) を絞る。

## 現在地：掲示板の viewer と引き受けの印

viewer は状態別の一覧 + 詳細の 2 画面 ([考え方](board/DESIGN.md#viewer))。 番が役割に回った依頼を受付へ渡すボタンと `GET /due` は
[契約](board/CONTRACT.md#viewer-handoff-queue)、 作業の前に掲示板へ印を書く `pickup` は [契約](board/CONTRACT.md#pickup)。
次 = 共同研究者の掲示板でボタンを出さないまま動くかを見る (`--handoff-dir` が無ければ書き込みの口は無い)。
worker の起動はカードを押す 2 段のまま。 重ければ [DESIGN](board/DESIGN.md#rejected-alternatives) の deep link を試す。

## 現在地：提出の門と役の受信箱の見張り

提出・検収は競合後の push と手動再送でも既読の ID を照合する。開始時の一覧は依頼ごとに1行とし、検収役は依頼のプレビューで確認できる。次は通常運用で、訂正の追加を通知された担当者が該当 ID から読み直せることを確かめる（[既読確認と再送](board/CONTRACT.md#accept-ack-newer)、[開始時の一覧](board/CONTRACT.md#session-start-surface)）。

`submit` は claim の後に他の人が書いた post を `--ack-newer` で名指させ ([契約](board/CONTRACT.md#submit-ack-newer))、 依頼書と、 その dir の下の link 先の依頼の後の commit を警告して提出に残す ([契約](board/CONTRACT.md#submit-spec-changes))。 役は `watch --session` で受信箱を見張れる ([契約](board/CONTRACT.md#watch-session))。
次 = 断り → 名指しの 1 往復が重すぎないかと、 警告 (過去の提出のおよそ 5 本に 1 本) が読まれるかを、 実際の提出で見る。 `watch --session` の負荷は大きな掲示板では測っていない。

## 現在地：worker の安全停止の案内

起動時の案内を整え、依頼元の検収に進む段階。次の起動時は生成した hand-off を [契約](board/CONTRACT.md#worker-handoff-text) と照合する。停止後の手順の正本は [共通規約](../claude-config/conventions/tool-call-robustness.md#api-safety-filter-on-main-response)。

## 現在地：worker の effort の下限

掲示板の `board.json` に `launch_effort_floor` を置くと、 Claude の役割 id 宛ての request と `launch --request` が
下限より低い effort を 1 行で断り、 本人の発言そのまま (`--effort-quote`) があれば通して起動の記録に残す
([契約](board/CONTRACT.md#launch-effort-floor))。 field の無い掲示板と Codex の役割は今までどおり。
次 = 古い engine は未知の field の `board.json` で止まる (投稿は remote の設定を読むので、 その機械が pull する前から)。
別の機械の heartbeat の head で、 engine がこの変更を含む版に届いたかを見る
(手順 = [claude-config の規約](../claude-config/conventions/multi-machine-state.md#config-field-needs-reader-first))。

## 現在地：役割 id 宛ての依頼と vendor

検収役の誤指定は依頼のプレビューと投稿の両方で書き込み前に検出し、役の受信箱は引受・再引受が必要な状態だけに `claim` を案内する。次は検収役つきの依頼で、提出が届いたときの案内を確認する（[検収の流れ](board/CONTRACT.md#request-and-receipt-workflow-v2)）。

役割 id (`role-…` / `resident-…`) 宛ての依頼は、 依頼に書いた agent に依らず、 その役割で開いた Claude・Codex
どちらの session の inbox にも出て、 claim・submit・受領ができる ([規則](board/CONTRACT.md#role-any-agent)、
`--to any` を採らなかった理由 = [DESIGN](board/DESIGN.md#rejected-alternatives))。 既存の依頼は付け替え不要。
共同研究者の掲示板では、 owner の配線の `AGENT_BOARD_LAUNCH_DEFAULT=1` で役割の worker を起動しない (役割が相手の側
でありうる)。 起動は `--launch` だけ ([規則](board/CONTRACT.md#worker-handoff-text))。
次 = 共同研究者側の session (engine 更新後) で、 既存の役割宛ての依頼が受信箱に出て引き受けられるかを見る。

## 現在地：並列 session の用事の claim

`board/board_items.py` を足した (掲示板の checkout の手元の台帳、 `board.py` は不変更)。 使い方は
[CONTRACT](board/CONTRACT.md#item-claims)、 採らなかった案は [DESIGN](board/DESIGN.md#item-claims)。
別の機械への写しは無い = 掲示板の見直しの結論が出てから決める。

## 現在地：本人への問いの台帳の推定の解き方

`board/board_asks.py` は、 問い返し・聞き直しの頼みを答えに読まず、 推定を確かめの短い肯定で結ぶか「答えではない」 で捨てる
([契約](board/CONTRACT.md#owner-asks) の Settling a guess)。 止めた理由の文が挙げる語は selftest が 1 つずつ試す。
まとめ答えは [実装の確かめ](docs/owner-asks-multiple-answers-proposal.md#implementation-verification) のとおり当てた (claude-config 6b8f97de・本 repo 7e33352)。 次は実際の画面で、 問いが複数開いたときに確認の行を出して短い答えでまとめて閉じる形を見る。
行き止まりの直し (本 repo 7e03b57): 問いの中身の名指しで結ぶ (`content`)、 読むだけの操作は止めない、 まとめの行を作れない範囲は一問ずつ、
肯定は直前の確かめの種類で読む (理由 = [DESIGN](board/DESIGN.md#owner-asks))。 中身で結ぶ条件は過去の発言で締めたので、 新しい発言での誤りの率は未測定。
次 = 実際の推定が 1 往復で解けるかと、 中身で結んだ答え (`content`) が正しい問いに結んだかを、 掲示板の台帳の記録で見る。 解けない言い方・誤った結びが出たら条件を直す。

## 現在地：本人への問いの「何の話か」 と前の記録

`board/board_asks.py` の `ask` は、 全部の問いに何の話かの 1 文 (`--about`、 作業側の語は断る) を求め、 選ぶ問いと送る問いに前の記録の欄 (`--prior-term` / `--prior`) を求める ([契約](board/CONTRACT.md#owner-asks))。
掲示板の設定の `ask_prior_search` が名指す検索を引いた語で回し、 当たりに額・決定の語があるのに「無し」 と書いた問いは問う側に知らせる。
次 = 実際の問いで、 作業側の語の断りが言い換えを強いすぎないか・知らせが当たりすぎないかを、 台帳の問いで見る。

## 現在地：掲示板の engine (board/)

owner 専用の掲示板から engine を移し、 共同研究の repo に層2 の掲示板を置けるようにした。 入口 = [board/README.md](board/README.md)、 運用の契約 = [board/CONTRACT.md](board/CONTRACT.md#boards-and-audiences)、 判断 = [DESIGN](DESIGN.md#board-engine) と [board/DESIGN.md](board/DESIGN.md#one-engine-many-boards)。 次 = 実際の共同研究の掲示板で、 共同研究者側の session が clone して読めるかを確かめる (読む人の gate は名前と path だけを見る = 文章の中身は書き手の判断)。 session の冒頭に要注意 thread を出す hook = `board/board-session-start.py` (配線は各自の settings、 判断 = [board/DESIGN.md](board/DESIGN.md#session-start-surface))。 新しい session から実際に発火したところはまだ見ていない。

未着手 = path の宣言 (`touch`) は宣言した session が終わっていても 🔴 を出す (実測)。 engine の `session_state` を `touch_verdict` と `untouch` の「次の持ち主」 に使い、 ended なら待たない形に (直すなら [board/CONTRACT.md](board/CONTRACT.md#path-touches) と試験も。 今の見方 = claude-config `closing-sweep.md#concurrent` の 2)。

## 現在地：封じた sandbox の回収

`make-review-sandbox.py collect` は規則の外に書かれた file も `outside-rules/` に写し、 sandbox の外の台帳に回収を残す。 未回収と回収の後に書き足された sandbox は `status`、 回収しない sandbox は `close --reason` ([規約](conventions/cold-eyes-isolation.md#collect-everything-written))。 受け取りの `inspect-review-sandbox.py receipt` は Codex アプリの rollout も読む (`--codex-rollout` / `--codex-launch`、 [規約](conventions/cold-eyes-isolation.md#codex-rollout-receipt))。 未確認 = 雛形の規則 4 (一時 file も scratch に) に Claude の reviewer が従うか: 締めの headless の行が worker の記録の scratchpad への書き込みを数えるので、 次の盲検の受領の締めで出る。

## 現在地：Codex の worker に作業 dir の外の書き込み dir を渡す

Codex の役割宛ての request は `--launch-writable-root <dir>` (繰り返し可) で、 作業 dir の外に書く dir を起動の時点で渡す ([契約](board/CONTRACT.md#codex-worker-launch))。 request の details に 1 dir 1 行で載り、 `launch --request` が読み戻して起動の道具の `--writable-root` に足す。
app の turn から名指した dir に書けることは実機で確かめた (Codex の worker が作業 dir の外の共有フォルダに成果物を書けた)。 次 = headless の行の `-c sandbox_workspace_write.writable_roots=[…]` は実機ではまだ走らせていない。

起動文と配送照会の改修は[実装](board/board.py)と[契約](board/CONTRACT.md#posting-rules)に反映した。次の実アプリでの worker 起動時に、起動文と同期照会を確認する。

## 決定ログ

- **2026-09-06: 新設** — 判断は DESIGN.md (分離の理由 / Phase 1 の範囲 / 移し方 = format-patch 履歴 import / stub + forwarder / Phase 2 trigger)
