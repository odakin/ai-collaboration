# SESSION.md — ai-collaboration

> 📌 SESSION.md = 案件ごとの現在地 + 正本への link (進んだら置き換える、 日付を見出しにした節・commit hash・messageId を置かない = 層1 claude-config/CONVENTIONS.md#session-no-durable-record)。 日付つきの節は SESSION-archive.md へ verbatim MOVE 済 (2026-09-28)。

## 現在地：掲示板 (board/)

経緯の旧全文 = [SESSION-archive.md](SESSION-archive.md) の「pointer 化退避 (2026-11-27)」。

- **engine** — 入口 = [board/README.md](board/README.md)・[契約](board/CONTRACT.md#boards-and-audiences)、 判断 = [DESIGN](DESIGN.md#board-engine)・[board/DESIGN.md](board/DESIGN.md#one-engine-many-boards)。 ⚠️ 読む人の gate は名前と path だけを見る = 文章の中身は書き手の判断。 次 = 実際の共同研究の掲示板で、 共同研究者側の session が clone して読めるかを確かめる。 session の冒頭の hook `board/board-session-start.py` ([判断](board/DESIGN.md#session-start-surface)) が新しい session から実際に発火したところはまだ見ていない。
  未着手 = path の宣言 (`touch`) は宣言した session が終わっていても 🔴 を出す。 engine の `session_state` で ended なら待たない形に ([契約](board/CONTRACT.md#path-touches) と試験も。 今の見方 = claude-config `closing-sweep.md#concurrent` の 2)。
- **Codex の書き込みを Claude 側に届ける網** — [Stop の検査](board/CONTRACT.md#codex-reach)・[`GET /due` の `waiting_event`](board/CONTRACT.md#viewer-handoff-queue)。 次 = 既存の送り忘れの検査 (observe のまま) を block に上げるかを、 observe の記録で決める。
- **研究の対話係の窓の起動文 (`--dialogue`)** — [契約](board/CONTRACT.md#dialogue-worker-handoff)・[係への渡し](board/CONTRACT.md#dialogue-desk)、 分担の正本 = claude-config `multi-session-coordination.md#research-dialogue-and-conductor`。 次 = 係つきで起こした最初の対話係の窓で、 渡しが係に届いたかを見る。
- **request の完了条件の頁数・overfull の注意** — [契約](board/CONTRACT.md#acceptance-value-check)、 規則 = [組版の関門](conventions/edit-intent-record.md#page-count-not-a-gate)。 次 = 規則そのものを語る request にも出る誤検出が、 実際の依頼で邪魔になるかを見る。 邪魔なら判定 (`board/board_acceptance.py`) を絞る。
- **viewer と引き受けの印** — [考え方](board/DESIGN.md#viewer)・[ボタンと `GET /due`](board/CONTRACT.md#viewer-handoff-queue)・[`pickup`](board/CONTRACT.md#pickup)。 次 = 共同研究者の掲示板でボタンを出さないまま動くかを見る。 worker の起動はカードを押す 2 段のまま、 重ければ [deep link](board/DESIGN.md#rejected-alternatives) を試す。
- **提出の門と役の受信箱の見張り** — [既読確認と再送](board/CONTRACT.md#accept-ack-newer)・[開始時の一覧](board/CONTRACT.md#session-start-surface)・[`--ack-newer`](board/CONTRACT.md#submit-ack-newer)・[依頼の後の commit の警告](board/CONTRACT.md#submit-spec-changes)・[`watch --session`](board/CONTRACT.md#watch-session)。 次 = 訂正の追加を通知された担当者が該当 ID から読み直せるか、 断り → 名指しの 1 往復が重すぎないか、 警告が読まれるかを、 実際の提出で見る。 `watch --session` の負荷は大きな掲示板では測っていない。
- **worker の安全停止の案内** — 依頼元の検収に進む段階、 停止後の手順の正本 = [共通規約](../claude-config/conventions/tool-call-robustness.md#api-safety-filter-on-main-response)。 次 = 次の起動時に、 生成した hand-off を [契約](board/CONTRACT.md#worker-handoff-text) と照合する。
- **worker の effort の下限** — [`launch_effort_floor`](board/CONTRACT.md#launch-effort-floor)。 ⚠️ 古い engine は未知の field の `board.json` で止まる (投稿は remote の設定を読むので、 その機械が pull する前から)。 次 = 別の機械の heartbeat の head で、 engine がこの変更を含む版に届いたかを見る ([手順](../claude-config/conventions/multi-machine-state.md#config-field-needs-reader-first))。
- **役割 id 宛ての依頼と vendor** — [規則](board/CONTRACT.md#role-any-agent)・[検収の流れ](board/CONTRACT.md#request-and-receipt-workflow-v2)。 ⚠️ 共同研究者の掲示板では、 owner の配線の `AGENT_BOARD_LAUNCH_DEFAULT=1` で役割の worker を起動しない。 起動は `--launch` だけ ([規則](board/CONTRACT.md#worker-handoff-text))。 次 = 検収役つきの依頼で、 提出が届いたときの案内を確認する。 共同研究者側の session (engine 更新後) で、 既存の役割宛ての依頼が受信箱に出て引き受けられるかを見る。
- **並列 session の用事の claim** — `board/board_items.py` ([CONTRACT](board/CONTRACT.md#item-claims)・[DESIGN](board/DESIGN.md#item-claims))。 別の機械への写しは無い = 掲示板の見直しの結論が出てから決める。
- **本人への問いの台帳の推定の解き方** — `board/board_asks.py` ([契約](board/CONTRACT.md#owner-asks) の Settling a guess・[DESIGN](board/DESIGN.md#owner-asks)・[まとめ答えの実装の確かめ](docs/owner-asks-multiple-answers-proposal.md#implementation-verification))。 中身で結ぶ条件 (`content`) の、 新しい発言での誤りの率は未測定。 次 = 実際の画面で、 問いが複数開いたときに確認の行を出して短い答えでまとめて閉じる形を見る。 実際の推定が 1 往復で解けるかと、 中身で結んだ答え (`content`) が正しい問いに結んだかを、 掲示板の台帳の記録で見る。 解けない言い方・誤った結びが出たら条件を直す。
- **本人への問いの言い直し** — key の無い問いは `ask --label <印> --reword '<何を変えたか>'` で同じ印のまま言い直し、 名指す相手の無い言い直しは断る ([契約](board/CONTRACT.md#owner-asks))。 次 = 実際の窓で、 言い直した問いへの「送って」 が 1 回で結ばれるかを見る (試験では確かめた)。
- **本人への問いの「何の話か」 と前の記録** — `ask` の `--about`・`--prior-term` / `--prior`・設定の `ask_prior_search` ([契約](board/CONTRACT.md#owner-asks))。 次 = 実際の問いで、 作業側の語の断りが言い換えを強いすぎないか・知らせが当たりすぎないかを、 台帳の問いで見る。
- **Codex の worker に作業 dir の外の書き込み dir を渡す** — `--launch-writable-root <dir>` ([契約](board/CONTRACT.md#codex-worker-launch))、 app の turn からは実機で確かめた。 次 = headless の行の `-c sandbox_workspace_write.writable_roots=[…]` は実機ではまだ走らせていない。 次の実アプリでの worker 起動時に、 起動文と同期照会 ([契約](board/CONTRACT.md#posting-rules)) を確認する。

## 現在地：検証の再利用道具 (次に使うときの入口)

どれも整備済み。 次に使うときに読む正本だけを置く (旧全文 = [SESSION-archive.md](SESSION-archive.md) の「pointer 化退避 (2026-11-18)」)。
- Lindblad 観測量 = [作用空間とチャネルの境界](docs/lindblad-observables.md) を確かめてから [生成索引](scripts/README.md) の module。 独立検査の原本は呼び元が持つ。
- 有限積分・外積・式の転記 = [実装の分担](DESIGN.md#finite-vacuum-and-transcription-tools) と [主張の依存関係・物理的な解釈](conventions/physics-verification-cycle.md#claim-dependencies-and-observables)。 module の selftest を通し、 独立検査の原本を共通実装への別名に置き換えない。
- 共変作用・密度 frame = [検証 kernel](conventions/physics-verification-cycle.md#action-equivalence-and-polynomiality)・[DESIGN](DESIGN.md#covariant-action-audit-hoist)。 制限背景の必要条件と一般共変な十分条件、 有限 ambient polynomial と場依存制約を別々に判定する。 個別論文の判定はこの public repo に置かない。
- レビュー成果物の不変性 = [snapshot helper](scripts/review-artifact-snapshot.py)。 baseline の対象と writer の停止を確かめ、 追加物の回収範囲は呼び元で指定する (入口 = [CLAUDE](CLAUDE.md))。
- 事前登録した比較実験の受領 = [共通手順](conventions/physics-verification-cycle.md#preregistered-comparison-receipt)。 登録した版と判定規則・匿名対応表の固定時点・部分確認した指摘の加点単位を仕様で確かめる。 個別の得点・採用判断・独立検算の原本は呼び元が持つ。

## 現在地：封じた sandbox の回収

`make-review-sandbox.py collect` / `status` / `close --reason` ([規約](conventions/cold-eyes-isolation.md#collect-everything-written))、 受け取り `inspect-review-sandbox.py receipt` ([規約](conventions/cold-eyes-isolation.md#codex-rollout-receipt))。 未確認 = 雛形の規則 4 (一時 file も scratch に) に Claude の reviewer が従うか: 締めの headless の行が worker の記録の scratchpad への書き込みを数えるので、 次の盲検の受領の締めで出る。

## 残タスク

- 状態識別の数式と道具を追加。入口 = [証明と利用範囲](docs/state-discrimination.md)、[library](scripts/state_discrimination.py)、[検証時の certificate](conventions/physics-verification-cycle.md#state-discrimination-certificates)。reporter は未知の foil crash と marker 後の非ゼロ終了を失敗にし、`--run` の失敗を呼び元へ返す。実装判断 = DESIGN.md。

- Session 宛て board との受領経路の接続は [verification-cycle-ops](conventions/verification-cycle-ops.md#board-receipt-boundary)。一般則の正本は README から既存 home へ参照し、Phase 2 の移設は未実施。

- [ ] Phase 2 の trigger 監視 (= DESIGN の表): Codex runner Pilot A 開始で `multi-session-coordination.md` と `codex/` を移設

- [ ] 掲示板の旧 transport (一時 clone + 全 file の復号 = `board.py` の `snapshot_clone` / `_post_clone`、 `AGENT_BOARD_TRANSPORT=clone`、 test の `*Clone` class) を消す: trigger = 掲示板を使う全機械の engine の checkout が fetch の transport 以降になり、 1 版の間に切り戻しが要らなかったこと。 判断と測定 = [board/DESIGN.md](board/DESIGN.md) の Concurrency and delivery
