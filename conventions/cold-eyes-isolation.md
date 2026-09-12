<!-- doc-meta
when: cold-eyes / 盲検 review を別 session (同 vendor) に投げる前 / referee 版の原稿を用意する時 / review 結果を受け取って独立性を判定する時
category: research-domain
summary: 別 session を立てただけでは目は冷えない — reviewer に起票側の結論が流れ込む 7 つの口 (cwd 祖先の CLAUDE.md・SessionStart hook 注入・spec 自体の漏洩・原稿内の著者注・repo 文脈と著者 script・同 vendor バイアス・依頼者の同定) と、 封じた sandbox の recipe (CLAUDE.md 祖先の無い dir + referee copy + 結論ゼロの spec + 注入無視の明示 + 受領後の汚染 grep)。 physics-verification-cycle §7/§10 の運用側 sibling
-->
# Cold-eyes 検品の汚染隔離 (cold-eyes isolation)

cold-eyes とは「書いた本人と別の目」 で検品させることだが、 AI session を別に立てるだけでは目は冷えない。 起票 session の結論は、 指示 file の自動 load・hook の注入・spec の書き方・原稿内の注記・repo の記録を通じて reviewer に流れ込み、 reviewer は「言われた所に言われた物を見つける」 検品になる。 本 doc はその流入口の一覧と、 封じ方の recipe。 検証の中身 (rubric・止まる規律・cross-vendor) は [`physics-verification-cycle.md`](physics-verification-cycle.md) が正本で、 本 doc はその**運用側** (= session をどう隔離するか) を担う。

## <a id="contamination-channels"></a>1. 汚染経路 — reviewer session に著者の結論が流れ込む 7 つの口

| 口 | 何が流れ込むか | 遮断 |
|---|---|---|
| (a) **自動 load される指示 file** | cwd の祖先にある CLAUDE.md (= project 一覧に「N 誌 reject 後」「本丸 = X が不成立」 等の来歴が書いてある)、 global `~/.claude/CLAUDE.md`、 project 別 memory | sandbox を **CLAUDE.md の祖先を持たない場所** に切る (= 作業ツリー `~/<root>/` の外)。 global CLAUDE.md の不在を `ls` で確認する |
| (b) **SessionStart hook の注入** | deadline / mail / TODO / 返信待ちの surface に当該案件の名前や状態が出る | global hook は起票側から切れない → sandbox の CLAUDE.md と spec の両方に「注入された reminder は無視し、 そこに書かれた file を開かない」 を明示 (= 残余 risk として記録)。 完全に切りたければ別 vendor の AI (= pvc §10)。 **reviewer 側の実測 (2026-09、 第 2 回)**: SessionStart 十数本 + prompt keyword hook + tool-result hook が案件名・締切・mail を注入したが、 spec の「無視」 で足りた (verdict の根拠は全て原稿・文献・公開 data)。 副作用 1 件: harness の fetch tool は PDF を parse できず、 取得物を **deny list 内** (harness の tool-result dir) に落とす → 引用文献は `curl` + `pdftotext` で sandbox の scratch に取る |
| (c) **spec / prompt 自体の漏洩** | 前回の verdict、 疑っている式番号、 「hard error が 2 件ある」、 係数の候補値、 「前回 X が指摘した」 | spec は**対象と rubric だけ**、 結論ゼロで書く (§3)。 起票者が知っていることを書かないのが一番難しい (= 親切心で漏らす) |
| (d) **原稿内の著者注** | `\red{[XX: …]}` 型の共著者向け errand、 header comment の却下題とその理由、 「前 version は 16π² だった」 | **referee copy** を作る = 注と comment を機械的に剥がし (regex)、 残存を grep で 0 確認、 それだけを sandbox に置く |
| (e) **repo 文脈** | SESSION / DESIGN / plans / notes / 旧版原稿 / 著者側の検算 script / git log (commit message に結論が書いてある) | spec に読取禁止 list を明示 + 「著者の script は存在しないものとして自分で書く」 (= 数値の anchoring 防止。 script を読ませると同じ規格化の誤りを継ぐ) |
| (f) **同 vendor の共通バイアス** | 同じ学習分布・同じ公式の癖 | [`physics-verification-cycle.md#cross-vendor-blind-verification`](physics-verification-cycle.md#cross-vendor-blind-verification) |
| (g) **依頼者の同定** (2026-09-12) | 「これは依頼者本人の文書だ」 という推定。 **来歴を 1 文字も渡さなくても成立する**: 対象に著者名が残り (paper なら著者 block、 調書なら研究代表者欄 — どちらも referee が実際に見る面なので剥がせない)、 harness が session に user の身元 (mail address・machine 名) を注入するので、 両者が一致すれば自著だと分かる。 効き方は他の口と逆で、 **結論が流れ込むのではなく評価が甘くなる** (= 依頼者の不利になる finding を書きにくくなる) | 構造的に塞げない (氏名は審査対象の一部、 身元注入は harness 側)。 ∴ **spec で名指しして打ち消す**: 「応募者との関係も来歴も知らない」 だけでなく、 **評点は分布目安つきの相対評価で付けろ / 「2」 以下には理由の選択を要求する** のように、 **甘くすると形式が埋まらない出力形式**を課す。 受領側は post-check (§4) で「短所が具体的な場所を指しているか」 を見る (一般論の短所しか無い report は甘さの兆候)。 残余 risk として記録し、 決定的な finding は別 vendor か著者側の独立再計算で裏を取る |

(a)(b) は harness 由来で**起票者が気付きにくい** (= 自分の session では便利な機構が、 reviewer には汚染源)。 (c)(d) は起票者の手癖由来で**気付いても止めにくい** (= 「これは伝えておいた方が効率的」 が全部漏洩)。

## <a id="sealed-sandbox"></a>2. 封じた sandbox の recipe

> 1 コマンド化 (2026-09-06): [`scripts/make-review-sandbox.py`](../scripts/make-review-sandbox.py) `create <slug> --spec REVIEW-SPEC.md --include <原稿/PDF>` が下の 1-4 を機械で切り (root が `~/Claude` 配下なら refuse)、 受領は `collect <slug> --into <dir>` で `REVIEW-RESULTS.md`、`STAGE*-RESULTS.md`、`HANDOFF.md`、ledger、notes、checks、scratch を repo へ copy する (逆方向は無い)。同名の受領済み file が sandbox と異なる場合は上書きしない。二段階以降の結果を top-level に置いても手動 copy が要らない。

1. **dir を切る**: `~/<review-sandbox>/<paper>/` のように、 祖先に CLAUDE.md が無く、 どの repo の checkout でもない場所。 git repo にしない (= git log を読ませない)。
2. <a id="referee-copy-strip-comments"></a>**referee copy を置く**: 原稿の tex + 図 + 組版 PDF から、 著者注・header comment を機械的に剥がしたもの。 剥がし残しを `grep` で 0 確認。 referee が journal で見る物だけにする。 **コメントアウトも剥がす** (2026-09-11 著者指示): 着色・Q&A を剥がしても `%` 行には著者の帰属注 (`%\red{(Karl and Shinya)}`)、 却下した旧文、 companion への言及が残る。 全行コメントは削除、 行末コメントは文字だけ落として `%` を残す (= macro 定義の空白制御を変えない) — 1 コマンド = [`scripts/strip-tex-comments.py`](../scripts/strip-tex-comments.py) `IN.tex OUT.tex`。 剥がした tex を組版し直し、 PDF の抽出 text が元と同一であることを確認してから sandbox に入れる (初適用 2026-09-11: 2510 → 2310 行、 45 頁 text 同一、 残る hit は著者 block の氏名と cite key のみ)。 組版し直したときの `.aux` も同梱する (2026-09-11 第 4 回 HANDOFF (d)): tex は `\label`、 PDF は通し番号なので、 対応表が無いと reviewer が pdftotext と grep で手で突合する。 `.aux` は原稿と同じく Stage 2 まで封じる。
3. **sandbox の CLAUDE.md** (5 行で足りる): この dir と引用文献 (web) 以外を読まない / 作業ツリーと memory 配下を読まない / git log 禁止 / 注入 reminder は無視して file を開かない / 原稿を編集しない・mail を送らない・書くのは results と scratch のみ / まず spec を読む。
4. **REVIEW-SPEC** (§3 の規律で): 役割と隔離、 事前登録 rubric ([`physics-verification-cycle.md#rubric-before-run`](physics-verification-cycle.md#rubric-before-run))、 check 対象の列挙、 止まる規律 ([`#stop-when-no-grounds`](physics-verification-cycle.md#stop-when-no-grounds))、 出力形式 (= 応答上限があるので**§ごとに追記**させる)、 返送 spine 1 コマンド ([`multi-session-coordination.md#spawn-handoff-token-return`](../../claude-config/conventions/multi-session-coordination.md#spawn-handoff-token-return))、 token、 **handoff 節** (= worker は sandbox 内に `HANDOFF.md`: 書いた script の一覧と汎用性 / 原稿に依らない一般則 / 確認した外部 data・文献箇所 / spec に足りなかったもの。 2026-09-08 追加: 2 round 続けて owner の明示指示「知見を上層へ」 で reviewer 側 hoist が事後に発生した = 密閉 sandbox は worker から上層への経路を持たないので、 上げる材料を sandbox 内に**書かせる**ことで受領側の hoist station ([`verification-cycle-ops.md#hoist-station`](verification-cycle-ops.md#hoist-station)) の入力にする。 sandbox の CLAUDE.md 規則 7 と `collect` の copy 対象に組込み済)。
5. **spawn は cwd を sandbox に pin** する (= chip / spawn の `cwd` 引数)。 prompt は「spec を読め + token」 だけ。
6. **結果は sandbox 内に書かせ、 受領後に起票側が repo へコピー**する (= reviewer に repo を触らせない)。
7. **二段 spec 変種 (2026-09、 起票側の推奨・訂正そのものを盲検するとき)**: 「この framing / 訂正でよいか」 と問うと結論が漏れる。 代わりに spec の冒頭に**対象の action と数値を写し**、 原稿を開く前に解く**導出課題** (Stage 1 → `notes/stage1-blind.md`、 Stage 2 で書き換え禁止) を置き、 その後に通常の査読と「どう提示すべきか」 の問い (Stage 2) を続ける。 起票側の案は一切書かない。 実測 (第 3 回): Stage 1 が起票側の 2 主張 (結合の符号の除外・構成が固定する関係) を独立に再現し、 起票側が pivot でしか評価していなかった項 (roll 全体の Weyl 成長 = [`scientific-computing.md#spectator-check-over-the-roll`](../../claude-config/conventions/scientific-computing.md#spectator-check-over-the-roll)) を発掘、 Stage 2 の framing 推奨は起票側の案と骨格一致 + 三層構造を追加した。 receipt では Stage 1 の結論を起票側の判断記録と表で突合し、 decisive finding は著者側 script で再導出してから採用する ([`physics-verification-cycle.md`](physics-verification-cycle.md#external-ai-referee-premise-verification) item 8)。 **課題文には判定基準の定義を入れる** (例: 「onset」 = $\epsilon_H=1$ の厳密背景、 「spectator」 = 有効質量 $\lesssim H$ かつ場 $\lesssim H$ を観測される e-folds 通して、 「完了」 = 占有数の閾値、 「tadpole」 = 1 点関数か seagull か) — 定義が無いと Stage 1 と原稿の突合が鈍る (第 3 回 HANDOFF §4、 第 4 回 HANDOFF (d))。 skeleton = [`template/REVIEW-SPEC-blind-manuscript.md`](../template/REVIEW-SPEC-blind-manuscript.md) (copy して `<...>` を埋め、 `make-review-sandbox.py create --spec` に渡す)。
8. <a id="misrouted-task-into-sandbox"></a>**逆向きの誤着 — sandbox を root にして無関係な task が届いたとき (2026-09-11)**: 起票元が別 repo の task を `cwd` 省略の chip で投げる等で、 sandbox を root に「sandbox 外の repo を直せ」 という session が起動しうる (実例 1 件、 起動経路は未確認)。 受け手は (a) 最初の返信で sandbox の CLAUDE.md と task の矛盾を表に出し、 chat の明示指示に従うならその旨を書く、 (b) sandbox に何も書かない — results / HANDOFF / ledger に加えて **harness の自動 memory** も (memory は起動時の root の project に紐づくので、 書けば次にこの sandbox で起動する reviewer に §1 (a) の口から自動 load される)、 (c) 同じ sandbox を使う reviewer session に message を送らない、 (d) 後続の chip は `cwd` を対象 repo にする。 起票側・受け手側の一般則 = [`multi-session-coordination.md#receiver-premise-snapshot`](../../claude-config/conventions/multi-session-coordination.md#receiver-premise-snapshot)。

## <a id="spec-leakage"></a>3. spec に書いてよいこと・書いてはいけないこと

| 書いてよい (= どこを見るか) | 書いてはいけない (= 何が出るか) |
|---|---|
| 対象 file、 reviewer の役割 (initial referee)、 読取の allow / deny list | 期待する verdict、 前回の verdict |
| 事前登録 rubric、 **check 対象の式 label の列挙** | 疑っている式、 「hard error」 「係数が怪しい」 等の方向づけ |
| 出力形式 (severity 分類・表の列)、 止まる規律 | 係数の候補値、 「前 version では X だった」 |
| 返送 spine と token | 著者が既に直した点、 共著者の状態、 論文の来歴 |
| 組版の検査を頼むなら「overfull / underfull は数と行番号の報告のみ、 severity なし」 と明記 (= 層1 [`edit-intent-record.md#overfull-not-a-gate`](edit-intent-record.md#overfull-not-a-gate)、 2026-09-12 に should-fix で返って受領側が語順変更を提案した再発) | overfull を直す提案 (改稿 pass でも triage でも採らない) |

境界の判定: **式 label を列挙するのは「どこを見るか」 の指定であって「何が出るか」 ではない**ので可。 逆に「Eq. 10 の 16π を確認せよ」 は答えを含むので不可 (= 「Eq. 10 の係数を独立に導出せよ」 まで)。

**追補 (2026-09、 第 2 回実装)**: 返送 command の `--task` 名や results の見出しに version 番号 (「v3.3」) を入れると、 reviewer の report に来歴語が残る (第 2 回の汚染 grep の唯一の hit)。 無害だが避けられる: task 名は「blind referee review of manuscript.pdf」 のように来歴を含めない。 §2 の「読んでよいもの」 には**引用文献の公開 data product** (著者 repo の chain・等高線) を明示的に含める (= reviewer が観測側の数値を独立再計算できる)。

**追補 (2026-09-12、 第 6 回 = 一括改稿の純粋性を検査させた回)**。 reviewer 側の `HANDOFF.md` (§4 の worker 入力) が spec の不足として挙げた 3 点。 いずれも「どこを見るか」 側なので**渡してよい**:

- **規約の定義は「答え」 ではない** — 記号の規約・添字の型・運動量の向き (どの脚が $+q$ を運ぶか)・signature は、 verdict でも疑っている箇所でもないので spec に書いてよく、 **書かないと reviewer は原稿から逆算する 1 pass を燃やす** (第 6 回の実測: 恒等式を再導出するのに向きが必要で、 印字済みの兄弟結果を control にして固定した = [`physics-verification-cycle.md#pin-convention-by-sibling`](physics-verification-cycle.md#pin-convention-by-sibling))。 境界は §3 本表のまま: 「Eq. 10 の係数を独立に導出せよ」 は可、 「Eq. 10 の 16π を確認せよ」 は不可。 規約は前者の側。
- **label 一覧は手書きせず生成物 (`.aux`) をそのまま渡す** — 手で作った「label → 式番号」 表は節・付録の label が落ちやすく (第 6 回の実測)、 何より**版間の label→頁 比較ができない** ([`#page-count-is-not-pagination`](physics-verification-cycle.md#page-count-is-not-pagination) の検査が spec 側の不足で塞がる)。 組版済みの成果物を渡す変種 (§4.7) でも、 `.aux` は「受け手が見る面」 ではないが **reviewer の機械検査の入力**なので allow list に入れる。 併せて、 配布 PDF を渡すなら reviewer が自分の build で再現できる材料 (assets・bst・bib) を揃える ([`#reproduce-before-attributing`](physics-verification-cycle.md#reproduce-before-attributing))。
- **射程を 1 行で宣言する** — 「変更の外側にある既存の不整合を finding にしてよいか」 を spec が言わないと、 reviewer は推測で padding するか黙るかのどちらかになる。 第 6 回の reviewer は `should-fix (pre-existing)` という severity を自作して逃がした。 spec 側で「変更が触っていない箇所の不整合も報告してよい / 報告不要」 を明示する (rubric 事前登録 = [`#rubric-before-run`](physics-verification-cycle.md#rubric-before-run) の一部)。

## <a id="typeset-artifact-variant"></a>4.7 変種: 組版された配布物の盲検は「受け手が見る面」 だけ渡す (2026-09-12)

対象が原稿ではなく**組版されて配られる物** (= 読み手は組版結果しか見ない物) のとき、 sandbox に入れるのは **組版 PDF だけ**にする。 source (tex 等) を渡した時点で盲検は壊れる — source には ①版の変遷 comment (却下した案とその理由) ②検算メモ ③設計意図と流儀の注記 ④コメントアウトした旧版 が同居しており、 reviewer は「作成側がどこを気にしているか」 を先に読んでしまう。 §2-2 の referee copy (= 注を剥がした tex を渡す) は**原稿**の話で、 組版物では**そもそも source を渡さない**方が安くて確実。

- **併せて渡すと効くもの**: 同系列の既出物 (= 前の版・前年の物)。 分量・体裁・水準の基準になる。 **査読対象ではない**と spec で明示する
- **渡してはいけないもの**: 作成側だけが持つ資料 (設計メモ・検討記録・内部の確認用資料)
- **実測 (2026-09-12)**: 組版 PDF 2 点 + 同系列の既出物 1 点だけを渡した盲検で、 受領物 3 file の汚染 grep は 0 hit。 指摘は組版・体裁・文言に及び、 source を見ないと出ない指摘 (= 設計意図への言及) は皆無だった。 併せて §2-7 の二段 spec (= 批評の前に自分で解く/使ってみる) を課すと、 「詰まった場所」 が体裁の指摘より強い証拠になる

## <a id="post-check"></a>4. 受領後の汚染 check

結果 file を受け取ったら、 禁止 source にしか無い情報 (SESSION の用語・却下した旧題・internal な note 名・起票 session だけが知る数値) が現れていないか grep する。 現れていれば汚染として記録し、 該当 finding の独立性を割り引く (= 汚染していない finding と分けて扱う)。 現れていなければ「独立した第二の目」 として採用できる。

**実例 (2026-09、 第 2 回)**: 禁止語 grep 0、 唯一の hit は spec の task 名由来の version 番号。 finding 3 件は著者側の from-scratch 再計算 (膨張背景での mode 成長、 厳密背景の Floquet、 固定 $r$ の $\Delta n_s$) で確認してから採用した ([`physics-verification-cycle.md#external-ai-referee-premise-verification`](physics-verification-cycle.md#external-ai-referee-premise-verification) item 8)。 reviewer の scratch script は results と一緒に repo へコピーするが、 著者側の検証は**別に書いた script** で行う (同一 script の再実行は独立検証にならない)。

**受領後の reviewer session (2026-09 追補)**: 隔離は review 中だけの規律。 受領・突合が済んだ後に owner が reviewer session 自身へ「知見を上層へ、 script も残す」 と指示すれば、 その session が scratch を一般化した道具 (層1 `scripts/`) と引用文献の verdict (refs の notes) を hoist できる ([`physics-verification-cycle.md#referee-side-kernels`](physics-verification-cycle.md#referee-side-kernels))。 順序が要: 受領側の DESIGN / 規約追補を**先に読んで**重複しない項目だけ上げる (受領側と reviewer 側が同じ file を取り合う = pvc C′ の時間順)。 sandbox は review 後も再計算環境 (venv・公開 chain・文献 text) を保つので、 その path は machine-local の memory に pointer として置く。 ⚠️ **その memory は sandbox の project に紐づく** ので、 書いてよいのは**その sandbox を二度と reviewer に使わせない**と決めたときだけ (= §8 (b) と同じ理由で、 次に同じ dir で起動した reviewer に §1 (a) の口から auto-load される)。 二段 spec の sandbox は stage 間で再起動するので**特に書かない** — stage 1 の結論が stage 2 に流れ込む。 pointer の行き先は受領側 repo (git 同期される側) にする。

**hoist commit の push (2026-09-08 追補)**: reviewer session の hoist は **local commit 止まりにして push しない** (= 公開 repo への最終 gate を隔離 worker に持たせない)。 push は起票 session が受領 sweep の一部として行う: 各 repo で `git log --oneline @{u}..` を読み、 leak grep (固有名・private repo 名) と新 script の `--selftest` を通してから push (owner が起票 session に委任した運用、 第 3 回で実施)。 取りこぼしの backstop = SessionStart の同期 sweep hook が fleet 横断で「未 push の local commit」 (ahead-only) を沈黙させずに surface する (起票側の layer で実装、 push 自体は自動化しない)。 reviewer は hoist 完了を起票 session へ cross-session message で知らせ、 編集した file と「触らない file」 を列挙する (race 回避、 第 3 回の型)。 順序は 受領側 hoist → reviewer 残余 hoist → 起票側 push (逆順だと重複 anchor を作る = 第 3 回で起票側 anchor を先に push して reviewer が fold した)。

## <a id="external-paper-variant"></a>4.5 変種: 外部論文の検証読み (verify-to-learn) は sandbox でなく deny list (2026-09)

自著の盲検と違い、 外部論文の検証読みで隔離すべきは「**起票者の仮説・解釈**」 だけ (著者注・来歴・却下案は無い)。 sandbox を切らず repo 内の campaign dir で走らせ、 (a) spec に期待 verdict を書かない (§3 と同じ) + (b) 起票者の note / 教科書 dir を deny list に列挙 + (c) 受領後に汚染 grep、 で足りた (初回: 0 hit、 worker は起票者の知らない結果を出した)。 repo の道具 (ledger / check / refs) を worker に触らせる利点が上回る。 再訪 trigger = 汚染 grep で hit → sandbox 方式へ (**同日 n=1 で発火**: 検証 pass が産んだ新結果の第二の目では、 auto-load の projects 一覧に書かれた verdict の方向が worker に見えていた = 汚染経路 1 は deny list で塞げない。 ∴ 新結果の第二の目は §2 の sandbox、 deny list 方式は「verdict が事前に存在しない一次検証読み」 限定)。 検証 pass が産んだ**新結果**の第二の目は 2 段階 (盲検 → 攻撃) = [`physics-verification-cycle.md#campaign-tooling`](physics-verification-cycle.md#campaign-tooling) C。

## <a id="proposal-variant"></a>4.6 変種: 審査を受ける文書 (研究費の計画調書・応募書類) の盲検 (2026-09-12)

論文でなく**審査を受ける文書**を盲検にするときの差分。2 件の文書をそれぞれ独立した 2 名の
reviewer sandbox に渡し、計 4 本を並行に回した実測。

- **同梱する物 = 審査委員が実際に受け取る面**: 添付 PDF は**モノクロ**版 (図の判読は評価対象)、
  Web 入力項目と経費明細は**別 file** (審査 UI で別画面に出るため)、そして**公開されている審査基準の全文**。
  逆に、規程が「評点に考慮しない」 と定めた欄は渡さない (渡すと reviewer がそれを根拠に書く)。
- <a id="staged-blind"></a>**段数は「審査 process の段数」 に合わせる** — §2 7 の二段 spec は
  「起票側の推奨・訂正そのもの」 を盲検する装置で、調書には起票側の対案が無いから**その意味では単段で足りる**。
  代わりに **rubric を審査基準の literal な写し**にし、評定要素の各小項目に対応段落を同定させる
  (対応が無い項目が機械的に出る)。⚠️ ただし**審査そのものが多段の種目** (= 応募多数だと概要版で
  事前の選考が入る) は別で、**概要版だけを読ませる pass を先に完了・凍結してから本体を渡す**。
  同時に渡すと reviewer は本体の情報で概要版を補ってしまい、実務でいちばん効く出力
  (「概要版だけで落ちる要因」) が出ない。段を分ける基準は「何を盲検するか」 ではなく
  **「審査委員が実際に何を、どの順で見るか」**。
  凍結の実装 = Stage 1 の評点と所見を**専用 file に書き切らせ、Stage 2 では書き換えを禁じ、
  訂正・比較は別 file に置かせる** (§2 7 と同じ規律)。「凍結した」 と書かせるだけでは、
  後知恵で Stage 1 の判断理由が書き換わっても検出できない。
  実測 (2026-09): 二段で回すと**段階で評点が割れた** — 前段は上位帯、後段は中位帯。割れ幅そのものが
  出力で、「短い方は書き方の良さで通るが、長い方は文献照合で落ちる」という構造は単段では両者が
  混ざって見えない。∴ **段が割れなかったときも情報** (= 両方の紙の質が揃っている) なので、
  両段の評点を並べて出させる。
- **評点は相対評価であることを spec に書く**。分布目安つきの総合評点は、母集団を宣言させないと
  数字が意味を持たない。絶対評価 (評定要素) と相対評価 (総合評点) を分けて出させる。
- **論文より強く検証できる面がある**: 経歴・業績・受賞・採択は**公開 DB で照合できる**
  (文献 DB・研究者 DB・課題 DB・助成事業の採択課題一覧)。∴ spec の「読んでよいもの」 に
  これらを明示的に含める。⚠️ 逆に、調書には**未公開物を根拠にした主張**が構造的に混じる
  (投稿前の論文・準備中の共著・進行中の事業の成果) — これは反証でも確認でもなく
  `unverified` で、理由を「公開物に存在しない」 と書き分ける。
- **汚染源が repo でなく案件 dir に集中する**: 前年の赤入れ・事務とのやりとり・採否・
  差し戻しの経緯は論文 repo の SESSION 相当で、しかも**同じ dir に referee copy を置きがち**。
  sandbox は案件 dir の外に切る (§2 1 と同じだが、案件 dir は `~/Claude` 配下とは限らない)。
- **(g) の口が最も強く出る**: 応募者名は様式の一部なので剥がせない。上表 (g) の打ち消しを spec に入れる。
- 受領側の一般則 (何を直すか) は
  [`kakenhi-proposal.md#referee-simulation-kernels`](../../claude-config/conventions/kakenhi-proposal.md#referee-simulation-kernels)。

## 5. 起源

2026-09-02、 共著論文 draft の cold-eyes 起票時に user 指摘 2 連 (「ちゃんと冷目になるように余計なもん見ないように制限して」 → 「SESSION, CLAUDE とか見ちゃうと汚染されるのでそれも注意」)。 同型の汚染は以前にもあったとの user 報告 (= 本 doc 新設の直接動機)。 初回実装 = sandbox `~/paper-review-sandbox/<paper>/` + referee copy (注 7 件・header 除去) + spec (rubric 6 群) + cwd pin の spawn。 残余 risk として global SessionStart hook の注入を明示した。

## 6. 隣接 doc への routing

- 検証の中身 (4 station / rubric 事前登録 / 止まる規律 / 独立した第二の目 / cross-vendor) = [`physics-verification-cycle.md`](physics-verification-cycle.md)
- 別 session への hand-off の機構 (spawn / token / 返送 spine / worktree 判定 / spec の切り方) = [`multi-session-coordination.md`](../../claude-config/conventions/multi-session-coordination.md)
- 外部 AI 査読レポートを受け取った側の前提検証 = [`physics-verification-cycle.md#external-ai-referee-premise-verification`](physics-verification-cycle.md#external-ai-referee-premise-verification)
