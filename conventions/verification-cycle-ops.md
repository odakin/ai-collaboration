<!-- doc-meta
when: 検証サイクル (verify-to-learn campaign / 第二の目 / retro) を session を越えて回し続ける仕組みを設計・運用・診断するとき / 「受領・retro・deferred 見直し・次の起票」 が止まっていないか確かめるとき / 無人 routine に検証 campaign を載せるか判断するとき
category: research-domain
summary: physics-verification-cycle.md (何を検査するか) の隣の「どう回し続けるか」 の正本 = 6 原則 (状態は file から導出し記録しない / 人間側 station は毎 session 自動 surface / retro 提案は gate・rule+trigger・rejected の 3 択で台帳化 / 数字は機械から / deferred には時計 / 人間の判断点を名指しで残す) + campaign の導出 state 機械 (spec → running → done=未受領 → received=retro 未記入 → retro'd) + 台帳 3 種 (ledger / carryover / improvements) + 無人層 (queue + kill switch + 人間 gate を越えない tick) + fresh session の手順。 2026-09-05/06 の 2 round (4 campaign、 retro 2 回) から。
-->
# 検証サイクルの運用 (verification-cycle operations) — session が終わっても回り続けるために

> 位置づけ: [`physics-verification-cycle.md`](physics-verification-cycle.md) が「**何を**検査するか」 (kernel 1-17、 campaign 運用 A-K) の正本。 本 doc は「**どう回し続けるか**」 = 起票 session が終わった後も、 受領・retro・改善・次の起票が fresh な session で拾われる構造の正本。 命名と 4 station の図式は日高義将氏の講演 (PPP2026) に負う (credit の線引きは physics-verification-cycle.md 冒頭)。 実 instance (campaign dir・台帳の中身・routine) は owner の private repo に残置 (kernel-up / instance-down)。

---

## <a id="why"></a>0. なぜ「回し続ける」 が別問題か

検証サイクルは 4 station (調べる・生成 → 機械検査 → 独立した第二の目 → 人間の判断) で、 **1 周は数時間で回る** (実測: campaign 1 = 64 分、 round 2 = 3 pass 並走で 17-65 分)。 問題はその後にある:

- 起票 session は fresh instance で、 終われば記憶が消える。 受領 (汚染 grep・独立再実装・efficacy 記入)、 retro、 deferred 提案の見直し、 次の起票は**全部人間側 session の action**で、 carrier が無ければ誰にも拾われない (round 2 で判明: 「受領・retro・deferred に carrier が無い」)
- 改善サイクル (retro → 対策) は「効いたか」 を n を溜めて見るしかないが、 n は campaign ごとに人間が数えないと溜まらない
- 無人で回す部分 (調べる・検査・第二の目) と、 人間が引き受ける部分 (efficacy の判定・著者への報告・SoT への昇格) の境界を**名指し**で固定しないと、 自律化はどちらかに崩れる (全部人間 = 止まる / 全部機械 = 判断が消える)

## <a id="principles"></a>1. 六つの原則

1. **状態は file から導出し、 記録しない。** 「campaign X は受領済」 を SESSION に書くと、 file と SESSION が食い違う drift 源になる。 ledger / results / retro / 台帳の**存在と中身**から state を毎回導出する (§2)。 記録するのは判断 (DESIGN) と数字 (AUTO block) だけ
2. **人間側 station は毎 session 自動 surface する。** 未受領・retro 未記入・deferred の期日・起票のみで止まった campaign・intake 候補を、 dashboard と SessionStart hook の両輪で押す。 該当なしは沈黙、 fail-open。 これは spawn-results / deadline-horizon と同じ「機械が人間の次 session に届ける」 (= [`multi-session-coordination.md#spawn-handoff-token-return`](../../claude-config/conventions/multi-session-coordination.md#spawn-handoff-token-return) の思想)
3. **retro の提案は 3 択の fate を持つ**: gate (機械化 = script / hook / gate) / rule (規約 + 再訪 trigger + review_by) / rejected (理由)。 fate の無い提案は残さない。 台帳 (`improvements.yaml`) に id を切り、 evidence は機械由来の数字だけ書く
4. **数字は機械から。** 所要は git timestamp、 items/commit は diff、 check/foil は runner、 efficacy proxy は受領側記入の field を集計 ([`physics-verification-cycle.md#efficacy-proxy-receiver-side`](physics-verification-cycle.md#efficacy-proxy-receiver-side))。 自己申告の数字を台帳に入れない (round 1: 自己申告 6 時間 vs git 64 分)
5. **deferred には時計。** review_by の無い deferred は拾われない ([`convention-design-principles.md#lapsing-deadline`](../../claude-config/docs/convention-design-principles.md#lapsing-deadline) の同型)。 期日が来たら「trigger は立ったか」 を判断して implemented / rejected / 延長のどれかにする
6. **人間の判断点を名指しで残す。** (a) efficacy proxy の記入 (起票者の事前知識は起票者しか知らない) (b) 他者論文の誤りの著者報告 = **owner 本人が確認するまで AI-refuted** ([`physics-verification-cycle.md#verify-to-learn`](physics-verification-cycle.md#verify-to-learn)) (c) SoT (層1・文献・DESIGN) への昇格 = 受領・突合後に受領側 1 session が直列 (d) deferred の fate 判断。 無人層はこれらを**越えない**

## <a id="state-machine"></a>2. campaign の導出 state

| state | 導出条件 (file のみ) | 次に動くのは |
|---|---|---|
| `spec` | spec.md のみ、 ledger に item なし、 results なし | 起票側: worker を spawn / queue に載せる。 3 日超なら「走っていない」 を surface |
| `running` | ledger に item、 results.md なし | worker (無人でも人間側でも) |
| `done` (= 未受領) | results.md あり、 かつ refuted に `novel_to_requester` 未記入 or AUTO block なし | **受領側**: 汚染 grep → 主要 finding の独立再実装 → `novel_to_requester` / `second_eye` 記入 → `--run --write` → marker consume ([board 経路の場合](#board-receipt-boundary)) |
| `received` (= retro 未記入) | 受領完了、 だが `campaigns/retros/*.md` の front matter `campaigns:` に無い | **受領側**: retro (§3) |
| `retro'd` (= 未昇格) | retro に載った、 だが retro front matter `hoist:` に無い | **受領側**: 昇格 station (§3.5) — 子 session が作った物を捨てず、 知見を上層へ。 記録するまで毎 session 📤 surface |
| `hoisted` | retro front matter `hoist: {<campaign>: "<date> <where>"}` に載った | 終端。 改善は improvements.yaml が引き継ぐ |

導出と surface の実体 = [`scripts/verification-campaign-report.py`](../scripts/verification-campaign-report.py) `--index [--write]` (INDEX.md = efficacy dataset) / `--surface` (finding のみ)。 「起票のみ 3 日」 は git の最初の commit 日から。

## <a id="ledgers"></a>3. 台帳 3 種と retro

| 台帳 | 粒度 | 誰が書く | 生成物か |
|---|---|---|---|
| `campaigns/<c>/ledger.yaml` | 1 item (主張) | worker (status / tier / readings) + **受領側** (`novel_to_requester` / `second_eye`、 field の意味は [`physics-verification-cycle.md#campaign-tooling`](physics-verification-cycle.md#campaign-tooling) A が正本) | 手書き |
| `carryover.yaml` | 👁 で未了の item | 機械 (`--carryover --write`、 同 B) | **生成物**、 手編集しない。 次 campaign の C 群の入口 |
| `improvements.yaml` | retro の提案 1 件 | 受領側 (retro を書く人) | 手書き。 status ∈ {implemented, deferred (+review_by), rejected} |

**retro** = round ごとに `campaigns/retros/<date>-round<N>.md`、 front matter に `campaigns:` (この retro が閉じる campaign) / `contamination:` / `gate_violations:` を機械可読で持つ (INDEX.md に汚染 hit として出る)。 本文は「数字 (AUTO block から写す) / 効いたこと (観測事実で) / 壊れたこと / まだ言えないこと / 提案 → fate 表 / 持ち越す問い」 の 6 節 (雛形 = owner repo の `TEMPLATE-retro.md`)。 **retro を書かないと state が `received` で止まり、 毎 session surface される** = 書く carrier はここ。

### <a id="hoist-station"></a>3.5 昇格 station — 子 session が作った物は捨てない、 知見は上層へ (2026-09-06、 owner 指示「毎度そういうサイクルで回す」)

campaign の worker (別 session / sandbox / 別ベンダー) は、 結果と一緒に **script・導出 note・判断**を産む。 受領で verdict だけ拾って終わると、 それらは campaign dir か sandbox に埋まり、 次の campaign が同じ道具を作り直す。 ∴ retro の後に **昇格 station** を置き、 state 機械の終端を `hoisted` にする (= 記録するまで機械が 📤 で押し続ける)。 5 点を順に:

1. **script は捨てない**: worker の `checks/` `notes/` `scratch/` は campaign dir に commit (sandbox は `make-review-sandbox.py collect` が scratch/ も copy)。 受領側の独立 script は `receipt/`。 削除は improvements に理由を書いた時だけ。 **worker 側の入力 = `HANDOFF.md`** (2026-09-08: sandbox の CLAUDE.md 規則 7 で worker に書かせる。 script 一覧 / 一般則 / 確認済の外部 data・文献箇所 / spec の不足。 受領側はこれを読んで 2–4 を判断する = 受領側が sandbox の scratch を読み解く費用を worker 側に前払いさせる)。
2. **再利用できる関数は層1 library へ** (例: `gpt_measurements.py`)、 campaign 側は shim か alias。 判断基準 = 2 campaign 目で同じ形が要ったら (層1 `#second-example-refine`)。
3. **kernel (定義から独立に導いた一般則・壊れ方) は層1 規約へ** (§ を切るか既存 § に追記)、 instance は private に残す。 汚染を避けるため、 進行中の別 campaign の verdict 方向を漏らす記述は受領後まで待つ (physics-verification-cycle C′)。
4. **文献の verdict は refs の notes へ**、 **判断は DESIGN へ**、 **状態は SESSION へ** (状態は file から導出、 SESSION は resume 用 highlight のみ)。
5. **retro front matter に `hoist: {<campaign>: "<date> <where>"}`** を書く = 機械が読む終端 marker。 どこへ何を上げたかを 1 行で (無ければ「保存のみ、 kernel 無し」 と正直に)。

この station は「知見を極力上層に」 (owner の standing 指示) を cycle の構造にしたもので、 人間の判断点 (著者連絡・公開) は越えない。

## <a id="autonomous-layer"></a>4. 無人層 — 何を無人にし、 何を越えないか (日高氏 #17「完全自律 run」 の部分採用、 2026-09-06)

owner の従来方針は「物理は人間 in-the-loop、 無人 run は事務系のみ」 (導入 plan §1.5 #17 = 意図的未採用)。 2 round の実測で、 4 station のうち**無人で安全に回せる部分と人間 gate が分離できた**ので、 部分採用に切り替える。 判断の軸 = 「不可逆・対外・SoT 書込みを含むか」:

| station | 無人可 | 理由・条件 |
|---|---|---|
| 調べる (intake) | ✅ 既に無人 (日刊 arXiv digest) + 本 doc の intake nudge (文献 SoT に原稿 project で引かれたのに検証読みが無い entry を surface) | 提案まで。 「使う」 判断は人間 |
| 検証読み (campaign 実行) | ✅ **queue に人間が載せた spec のみ**、 kill switch default OFF、 1 tick 1 campaign、 item / 時間 cap、 private repo 内、 対外 action ゼロ | worker と同じ規律 (cadence gate / scope gate / foil 契約 / 3 状態 / 止まる規律)。 結果は marker で人間へ |
| 第二の目 | ✅ queue に「盲検 → 攻撃」 spec を載せれば同じ tick で | sandbox 方式 (repo 外)、 verdict を含む文書を読まない |
| 受領・突合 | ❌ 人間側 | efficacy proxy の記入は起票者の知識、 独立再実装は「別の目」 |
| 著者報告・公開 | ❌ 人間 (owner 本人の確認が gate) | AI-refuted は根拠でない |
| SoT 昇格 (hoist) | ❌ 受領側 1 session が直列 | round 2 の race |
| retro → improvements | ❌ 人間側 (数字の表は機械が用意) | fate 判断は判断 |

**無人 tick の契約** (owner instance = launchd `claude -p` routine、 実装は private layer): (1) kill switch (config yaml) が OFF なら surface + INDEX 更新だけ (2) ON なら `QUEUE.yaml` の先頭 1 件 (人間が spec と `autorun: true` を書いたもの) を campaign dir に展開して verify-to-learn 4 step を実行、 cap に当たったら `--status partial` で marker (3) 完了 marker は必ず落とす (人間の受領 carrier) (4) 層1・文献 SoT・DESIGN・他 repo に書かない (scope gate が機械で保証) (5) heartbeat file を更新 (= 死んだら fleet-heartbeat が拾う)。 **「走り続ける」 より「根拠が無ければ止まる」** ([`physics-verification-cycle.md#stop-when-no-grounds`](physics-verification-cycle.md#stop-when-no-grounds)) が優先。

## <a id="fresh-session"></a>5. fresh な session が最初にやること (= 手順の全部)

1. SessionStart の surface (🔬 行) を読む。 無ければ何も止まっていない
2. 止まっている station へ: `done` → 受領手順 (§2 表) / `received` → retro (§3) / 🕰 deferred → fate 判断 / ⏳ spec のみ → spawn し直すか abandon / 🧾 carryover 閾値超 → 次 campaign を queue に / 🔎 intake 候補 → 使うなら起票、 使わないなら文献 SoT の project tag を外す
3. 動いた後は `--index --write` で INDEX.md を更新して commit (= efficacy dataset の 1 行)
4. **触ってよい file の範囲を守る**: 受領側は path 指定で add、 worker dir は worker のもの、 hoist は最後に 1 session で

## <a id="failure-modes"></a>6. 想定する壊れ方と検出

| 壊れ方 | 検出 |
|---|---|
| 受領されない results | `done` を毎 session surface (state 導出) |
| retro が書かれない | `received` を surface |
| deferred が忘れられる | review_by 超過を surface、 時計なしも surface |
| worker が走らない (chip 未クリック / 死亡) | `spec` が 3 日超で surface |
| 無人 tick が死ぬ | heartbeat stale (fleet-heartbeat) + cron exit status (check-cron-health) |
| 台帳が壊れる (YAML) | 層3 yaml gate (pre-commit) + `--index` の fail-open (壊れた file は読めないと表示) |
| 自己申告の数字が混じる | AUTO block しか INDEX に載らない |
| 隔離漏れ | retro front matter の contamination hit が INDEX に累積 (0 が続くかが R2-01 の evidence) |
| 検査 fleet が共通の不変性を持つ (有効作用の全体符号・全体規格化) — 全部 PASS でもその量は未検証 | 符号を持つ印字量の登録簿 + `check-sign-anchors.py --run` (反転した入力で落ちない anchor は finding) + `--fleet-scan` (どの検査が見分けるかの表)。 規則 = [`paper-audit.md#absolute-sign-external-anchor`](../../claude-config/conventions/paper-audit.md#absolute-sign-external-anchor) |

## <a id="limits"></a>7. 正直な限界

- 全部 2 round・4 campaign からの設計 (n=2)。 「回り続けた」 の evidence は 3 round 目以降にしか無い
- efficacy proxy は主観の事後判定。 対照実験 (手法なしで同じ論文を読む) は cost が高く未実施
- 無人層の安全は「対外 action ゼロ・SoT 書込みゼロ」 の設計に依存。 別ベンダー worker は spec より自分の既定に従った実績があるので、 無人層の worker は同ベンダー (spec を読む) に限る
- 無人 tick は queue (人間が書いた spec) を読む。**board 宛ての依頼を無人で拾う**なら、同じ契約の runner を board 側に置く = 層1 [`multi-session-coordination.md#resident-board-runner`](../../claude-config/conventions/multi-session-coordination.md#resident-board-runner) (poll は決定的、dispatch は kill switch、worker は submit まで、受領は人間側 session)。queue と board の二重起動を作らない = 1 依頼は片方にだけ載せる。
- state 導出は file の**存在**に依存する。 worker が results.md を書かずに死ねば `running` のまま — その検出は marker 経済 (`--status partial`) と heartbeat の側

## <a id="board-receipt-boundary"></a>Session 宛て board との接続

board の主体・遷移・引継ぎは
[`multi-session-coordination.md §13`](../../claude-config/conventions/multi-session-coordination.md#git-immutable-event-board)
が正本。本書の campaign state は研究上の受領・retro の進み具合を表し、board は担当 session と
次の行動を表す。board の accept だけで campaign の独立検証・人間 gate が済んだことにはしない。

既存 campaign の marker 経路はそのまま使う。新たに board-native な依頼を選ぶ場合は、spec に
受領経路を明記し、worker は成果物の所在を submit、指定された確認 session が本書の受領検査を
行ってから accept / revise を記録する。本書の marker 発行・consume 指示を同じ義務に重ねない
([1 義務 1 受領経路](../../claude-config/conventions/multi-session-coordination.md#board-receipt-carrier))。
既存の無人 tick は marker 契約のままで、board 投稿は起動や無人実行を有効化しない。

## 8. 隣接 doc への routing

昇格 station の道具 = `verification-campaign-report.py --surface` (📤 未昇格) + `make-review-sandbox.py collect` (scratch 込み)。

何を検査するか = [`physics-verification-cycle.md`](physics-verification-cycle.md) / 委譲と返送 spine = [`multi-session-coordination.md`](../../claude-config/conventions/multi-session-coordination.md) / 隔離 = [`cold-eyes-isolation.md`](cold-eyes-isolation.md) / 無人 routine の一般則 = [`scheduled-tasks.md`](../../claude-config/conventions/scheduled-tasks.md) + [`multi-machine-state.md`](../../claude-config/conventions/multi-machine-state.md) / worker の死に方 = [`output-cap-death-loop.md`](../../claude-config/conventions/output-cap-death-loop.md) / 道具 = `scripts/verification-campaign-report.py` (`--index` / `--surface` / `--run` / `--carryover`)、 `scripts/ledger-commit-cadence-gate.py`、 `scripts/make-review-sandbox.py`
