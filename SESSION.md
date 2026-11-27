# SESSION.md — ai-collaboration

> 📌 SESSION.md = 案件ごとの現在地 + 正本への link (進んだら置き換える、 日付を見出しにした節・commit hash・messageId を置かない = 層1 claude-config/CONVENTIONS.md#session-no-durable-record)。 日付つきの節は SESSION-archive.md へ verbatim MOVE 済 (2026-09-28)。

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

## 現在地：検証の再利用道具 (次に使うときの入口)

どれも整備済み。 次に使うときに読む正本だけを置く (旧全文 = [SESSION-archive.md](SESSION-archive.md) の「pointer 化退避 (2026-11-18)」)。
- Lindblad 観測量 = [作用空間とチャネルの境界](docs/lindblad-observables.md) を確かめてから [生成索引](scripts/README.md) の module。 独立検査の原本は呼び元が持つ。
- 有限積分・外積・式の転記 = [実装の分担](DESIGN.md#finite-vacuum-and-transcription-tools) と [主張の依存関係・物理的な解釈](conventions/physics-verification-cycle.md#claim-dependencies-and-observables)。 module の selftest を通し、 独立検査の原本を共通実装への別名に置き換えない。
- 共変作用・密度 frame = [検証 kernel](conventions/physics-verification-cycle.md#action-equivalence-and-polynomiality)・[DESIGN](DESIGN.md#covariant-action-audit-hoist)。 制限背景の必要条件と一般共変な十分条件、 有限 ambient polynomial と場依存制約を別々に判定する。 個別論文の判定はこの public repo に置かない。
- レビュー成果物の不変性 = [snapshot helper](scripts/review-artifact-snapshot.py)。 baseline の対象と writer の停止を確かめ、 追加物の回収範囲は呼び元で指定する (入口 = [CLAUDE](CLAUDE.md))。
- 事前登録した比較実験の受領 = [共通手順](conventions/physics-verification-cycle.md#preregistered-comparison-receipt)。 登録した版と判定規則・匿名対応表の固定時点・部分確認した指摘の加点単位を仕様で確かめる。 個別の得点・採用判断・独立検算の原本は呼び元が持つ。

## 現在地：掲示板の engine (board/)

owner 専用の掲示板から engine を移し、 共同研究の repo に層2 の掲示板を置けるようにした。 入口 = [board/README.md](board/README.md)、 運用の契約 = [board/CONTRACT.md](board/CONTRACT.md#boards-and-audiences)、 判断 = [DESIGN](DESIGN.md#board-engine) と [board/DESIGN.md](board/DESIGN.md#one-engine-many-boards)。 次 = 実際の共同研究の掲示板で、 共同研究者側の session が clone して読めるかを確かめる (読む人の gate は名前と path だけを見る = 文章の中身は書き手の判断)。 session の冒頭に要注意 thread を出す hook = `board/board-session-start.py` (配線は各自の settings、 判断 = [board/DESIGN.md](board/DESIGN.md#session-start-surface))。 新しい session から実際に発火したところはまだ見ていない。

未着手 = path の宣言 (`touch`) は宣言した session が終わっていても 🔴 を出す (実測)。 engine の `session_state` を `touch_verdict` と `untouch` の「次の持ち主」 に使い、 ended なら待たない形に (直すなら [board/CONTRACT.md](board/CONTRACT.md#path-touches) と試験も。 今の見方 = claude-config `closing-sweep.md#concurrent` の 2)。

## 現在地：封じた sandbox の回収

`make-review-sandbox.py collect` は規則の外に書かれた file も `outside-rules/` に写し、 sandbox の外の台帳に回収を残す。 未回収と回収の後に書き足された sandbox は `status`、 回収しない sandbox は `close --reason` ([規約](conventions/cold-eyes-isolation.md#collect-everything-written))。 受け取りの `inspect-review-sandbox.py receipt` は Codex アプリの rollout も読む (`--codex-rollout` / `--codex-launch`、 [規約](conventions/cold-eyes-isolation.md#codex-rollout-receipt))。 未確認 = 雛形の規則 4 (一時 file も scratch に) に Claude の reviewer が従うか: 締めの headless の行が worker の記録の scratchpad への書き込みを数えるので、 次の盲検の受領の締めで出る。

## 現在地：Codex の worker に作業 dir の外の書き込み dir を渡す

Codex の役割宛ての request は `--launch-writable-root <dir>` (繰り返し可) で、 作業 dir の外に書く dir を起動の時点で渡す ([契約](board/CONTRACT.md#codex-worker-launch))。 request の details に 1 dir 1 行で載り、 `launch --request` が読み戻して起動の道具の `--writable-root` に足す。
app の turn から名指した dir に書けることは実機で確かめた (Codex の worker が作業 dir の外の共有フォルダに成果物を書けた)。 次 = headless の行の `-c sandbox_workspace_write.writable_roots=[…]` は実機ではまだ走らせていない。

起動文と配送照会の改修は[実装](board/board.py)と[契約](board/CONTRACT.md#posting-rules)に反映した。次の実アプリでの worker 起動時に、起動文と同期照会を確認する。

## 残タスク

- 状態識別の数式と道具を追加。入口 = [証明と利用範囲](docs/state-discrimination.md)、[library](scripts/state_discrimination.py)、[検証時の certificate](conventions/physics-verification-cycle.md#state-discrimination-certificates)。reporter は未知の foil crash と marker 後の非ゼロ終了を失敗にし、`--run` の失敗を呼び元へ返す。実装判断 = DESIGN.md。

- Session 宛て board との受領経路の接続は [verification-cycle-ops](conventions/verification-cycle-ops.md#board-receipt-boundary)。一般則の正本は README から既存 home へ参照し、Phase 2 の移設は未実施。

- [ ] Phase 2 の trigger 監視 (= DESIGN の表): Codex runner Pilot A 開始で `multi-session-coordination.md` と `codex/` を移設

- [ ] 掲示板の旧 transport (一時 clone + 全 file の復号 = `board.py` の `snapshot_clone` / `_post_clone`、 `AGENT_BOARD_TRANSPORT=clone`、 test の `*Clone` class) を消す: trigger = 掲示板を使う全機械の engine の checkout が fetch の transport 以降になり、 1 版の間に切り戻しが要らなかったこと。 判断と測定 = [board/DESIGN.md](board/DESIGN.md) の Concurrency and delivery

## 決定ログ

- **2026-09-06: 新設** — 判断は DESIGN.md (分離の理由 / Phase 1 の範囲 / 移し方 = format-patch 履歴 import / stub + forwarder / Phase 2 trigger)
