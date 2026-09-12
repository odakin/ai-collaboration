# DESIGN.md — ai-collaboration

現在採用している設計判断の snapshot。超越されたら `claude-config/docs/convention-design-principles.md#design-snapshot-operation` の lifecycle で処理。

## claude-config から分離した理由と、何を持ってきたか (2026-09-06)

**判断**: 検証サイクルの platform (規約 3 本 + script 4 本) を新 repo `ai-collaboration` (layer 1、public) に移す。`claude-config` は Claude Code の harness (setup / hooks / gitignore / domain 規約 / 生成 tool) として残す。
**Why**: `claude-config` の中身は conventions 106 本 + scripts 71 本 + Codex 統合で、名前 (Claude の設定) が実態 (AI 協働の運用基盤) と合わなくなった (user「ありえん、新しいリポを作ろう」)。rename は literal path 496 件 / 参照 file 803 件の移行で hook・routine が一斉に壊れる窓を作るので不採用。「説明で誤魔化す (rebrand)」は user が却下。∴ **中身の方を、名前が正しい新しい箱へ段階的に移す**。
**なぜこの 7 file が Phase 1 か**: 2026-08-31〜09-06 に生まれた検証サイクルの kernel と道具で、(a) 互いに閉じている (相互参照が repo 内で完結) (b) 呼び元が owner の private layer 4 箇所だけで path 更新が小さい (c) vendor 中立 (Claude / Codex の pass を同じ規律で扱う) = 新 repo の名の実体そのもの。
**移し方**: clone でなく一から骨格を書き、移す file の git 履歴だけ `git format-patch --root -- <paths>` → `git am` で持ち込む。clone は 106 規約の二重化 = drift 源 (今日一番痛かった型) なので棄却。
**claude-config 側**: 移した規約は **anchor id を保った stub** (旧 `<a id>` を全部列挙し「移設先はこちら」)、script は **forwarder** (同名で新 path を exec)。∴ 496 件の literal path も `#anchor` link も壊れない。呼び元は順次新 path へ。
**限界**: 規約 corpus が 2 repo に割れる → routing cost。生成 tool (`generate-tree.py` 等) は claude-config 側にあり、本 repo の index は当面手書き (file が 7 本なので足りる)。

## 状態識別の certificate の正本 (2026-09-06)

状態識別の一般数式・certificate は `docs/state-discrimination.md`、実装は `scripts/state_discrimination.py` に置く (2026-09-06)。`gpt_measurements.py` の joint-measurement / solver 系に混ぜず、NumPy だけで使える小さな module とする。private caller は shim から呼び、特定の論文の行列・番号・verdict は caller に残す。実行・集計は既存 campaign reporter が正本で、別の汎用 runner は増やさない。受領後の再実行は受領 metadata を保存する。

## Phase 2 (trigger 付き、speculative 実行禁止)

| 移設候補 | trigger |
|---|---|
| `multi-session-coordination.md` (委譲・返送 spine・worktree 判定・sizing) | Codex runner の Pilot A が始まった時 (= AI–AI 協働の中核規約が vendor 中立の箱に要る) |
| `codex/` (AGENTS / HOME-AGENTS / PARITY / skills / hooks / setup-codex.sh) | 同上 (Codex が co-equal な runner になる時)。setup-codex.sh の path は移設時に一括更新 |
| `output-cap-death-loop.md` / `tool-call-robustness.md` (worker の死に方) | multi-session-coordination と同時 |
| agent-board の一般則 (`#git-immutable-event-board`) | multi-session-coordination と同時 |

**移さないもの**: setup.sh / hooks (Claude Code 固有の harness)、LaTeX・Office・mail 等の domain 規約、generate-tree 等の生成 tool。= claude-config の名前で true な範囲。

## <a id="script-index-generation"></a>Script index は docstring から生成 (2026-09-06 → 2026-09-11)

**初期判断**: file 7 本では README / CLAUDE.md の一覧を手書きし、15 本を超えたら生成へ移る。**trigger 到達**: 2026-09-11 に scripts が19本を超え、同日の3本昇格で手書き一覧が再び二重化した。**現判断**: 各 module の docstring 1行目を説明の正本とし、`generate-script-index.py` が全 `scripts/*.py` を [`scripts/README.md`](scripts/README.md) に生成する。main README と CLAUDE.md はその索引への pointer だけを持つ。CI は `--check` と全 script の `--selftest` を別 gate として実行する。これにより script の存在・説明・実行検査を混同せず、追加漏れだけを機械で止める。

## <a id="unbounded-moment-hoist"></a>非有界 moment-operator campaign からの層1昇格 (2026-09-11)

**判断**: private paper campaign で得た検証器のうち、論文・検出器・次元に依らない三つの核を独立 script として層1へ上げる。`covariant_moment_algebra.py` は共変 moment の full-line ladder と finite-window endpoint 項、`povm_moment_variance.py` は $M_2$ と $M_1^2$ の差・noise・結合次数、`unbounded_operator_domains.py` は domain membership だけでは強微分を保証しない陽な反例と weak identity の最大実現の罠を所有する。Gaussian tail、三次元の角度積分、特定原稿の係数・判定・レビューは project instance に残す。

**規約の正本**: [`physics-verification-cycle.md#unbounded-moment-domain-audit`](conventions/physics-verification-cycle.md#unbounded-moment-domain-audit)。そこで scalar moment、form、operator action、product domain、finite window、full line、statewise probability、operator positivity、support、inverse domain を分離し、証明の非循環な依存順を定める。script はその符号・有限次元代数・反例の anchor で、無限次元 theorem の代替ではない。

**受領器の修正**: multi-stage review が top-level `STAGE2-RESULTS.md` を書いた campaign で `make-review-sandbox.py collect` が回収せず、手動 copy が必要だった。collect は `STAGE*-RESULTS.md` も列挙して、既存 file の非上書き規則を同じように適用する。これは受領 path の欠落修正で、stage 名や数を固定しない。

## 盲検 reviewer 側の数値道具を層1 に置く (2026-09-07)

**判断**: 自著の blind review を書いた session が作った scratch のうち、 論文に依らない 3 つ (公開 chain の HPD 信用水準 / 図の等高線の自己較正復元 / 厳密周期背景の Floquet 指数) を一般化して `scripts/` に置く。 campaign 由来の `gpt_measurements.py` と同じ扱い (kernel-up / instance-down、 ops `#hoist-station`)。 **Why**: 次の blind review・verify-to-learn が同じ道具を作り直すのを防ぐ。 chain・PDF・図の実 data は本 repo に入れない (公開物でも scope 外、 selftest は合成 data で閉じる)。 **代替案**: private paper repo に置く → 他 campaign から見えない / claude-config に置く → 数値道具は vendor 中立なので本 repo。 **境界**: 論文固有の再現 script (表 1・軌跡・図) は private repo の scratch copy に残し、 ここへは上げない。

**追記 (2026-09-11)**: 第 4 回の reviewer hoist で `one_loop_pole.py` / `dirac_algebra.py` / `heat_kernel_a4.py` を足した。 `one_loop_pole.py` は極を厳密有理数で出すために sympy を使うので、 CI の install に sympy を加えた (09-07 の 3 本が NumPy/SciPy だけで書けたのは道具の性質で、 repo の制約ではない)。 境界は同じで、 模型固有の双線形形式・Ward 恒等式の構造数え・原稿の Feynman 則と印字式は private repo に残す。 全体符号の外部 anchor は、 規則が claude-config `paper-audit.md#absolute-sign-external-anchor`、 検査 engine が同日の `check-sign-anchors.py`、 registry が各 project にある。 ここの 3 本は selftest の較正に同じ量 (真空エネルギー・QED) を使うだけで、 project の anchor registry には載せない。

## 相手側の AI への作業委譲を層1 に置く (2026-09-12)

**判断**: 共同研究者 (人間 + その AI) に数か月の解析を実行してもらうときの文書形式を `conventions/delegated-work-packages.md` として本 repo に置く。中身 = 判断と実行の分離、常設 3 層 (入口 / 手順 / 定義) + 1 セッション 1 WP、WP の 7 要素、**受入基準を依頼側の独立実装の出力で埋める**、全部書いて ready だけ着手、書き込み zone、結果ノートの様式、作業者に書かせないもの。

**Why**: 本 repo の趣旨 (what to hand to the machine, what a human must still check) の一例そのもので、vendor 中立 — 相手の AI が Claude でも Codex でも、あるいは人間だけでも形式は同じ。既存 3 本が「自分の書いたものを検証する」側なのに対し、これは「他人に実行してもらう」側で、station として隣り合う。

**代替案**: (a) `claude-config` に置く → あちらは Claude Code harness の規約で、相手のツールを規定しない本形式とは層が違う。(b) `dropbox-refs.md#counterpart-ai-parallel-work` を拡張する → あれは Pattern B (Dropbox 共有) 固有の運用で、委譲形式は同期手段に依らない。(c) project 内に留める → 次の project が同じ形式を作り直す (kernel-up / instance-down の原則に反する)。

**境界**: 分野固有の中身 (観測データの QC、統計モデル、判定閾値) は project の SPEC に残す。本 doc が持つのは形式だけ。受入基準の数値そのもの・参照実装も project 側。

**evidence base は 1 プロジェクト** (2026-09-12、卒論 → 国際誌フルペーパーの解析、WP 15 本)。doc 末尾に「2〜3 本が accepted になったら基準の本数を減らす方向で見直す」と書いた。形式が重いと結果ノートが儀式化するのが最も起こりやすい失敗なので、そこを再訪 trigger にする。
