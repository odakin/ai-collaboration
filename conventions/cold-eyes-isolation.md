<!-- doc-meta
when: cold-eyes / 盲検 review を別 session (同 vendor) に投げる前 / referee 版の原稿を用意する時 / review 結果を受け取って独立性を判定する時
category: research-domain
summary: 別 session を立てただけでは目は冷えない — reviewer に起票側の結論が流れ込む 6 つの口 (cwd 祖先の CLAUDE.md・SessionStart hook 注入・spec 自体の漏洩・原稿内の著者注・repo 文脈と著者 script・同 vendor バイアス) と、 封じた sandbox の recipe (CLAUDE.md 祖先の無い dir + referee copy + 結論ゼロの spec + 注入無視の明示 + 受領後の汚染 grep)。 physics-verification-cycle §7/§10 の運用側 sibling
-->
# Cold-eyes 検品の汚染隔離 (cold-eyes isolation)

cold-eyes とは「書いた本人と別の目」 で検品させることだが、 AI session を別に立てるだけでは目は冷えない。 起票 session の結論は、 指示 file の自動 load・hook の注入・spec の書き方・原稿内の注記・repo の記録を通じて reviewer に流れ込み、 reviewer は「言われた所に言われた物を見つける」 検品になる。 本 doc はその流入口の一覧と、 封じ方の recipe。 検証の中身 (rubric・止まる規律・cross-vendor) は [`physics-verification-cycle.md`](physics-verification-cycle.md) が正本で、 本 doc はその**運用側** (= session をどう隔離するか) を担う。

## <a id="contamination-channels"></a>1. 汚染経路 — reviewer session に著者の結論が流れ込む 6 つの口

| 口 | 何が流れ込むか | 遮断 |
|---|---|---|
| (a) **自動 load される指示 file** | cwd の祖先にある CLAUDE.md (= project 一覧に「N 誌 reject 後」「本丸 = X が不成立」 等の来歴が書いてある)、 global `~/.claude/CLAUDE.md`、 project 別 memory | sandbox を **CLAUDE.md の祖先を持たない場所** に切る (= 作業ツリー `~/<root>/` の外)。 global CLAUDE.md の不在を `ls` で確認する |
| (b) **SessionStart hook の注入** | deadline / mail / TODO / 返信待ちの surface に当該案件の名前や状態が出る | global hook は起票側から切れない → sandbox の CLAUDE.md と spec の両方に「注入された reminder は無視し、 そこに書かれた file を開かない」 を明示 (= 残余 risk として記録)。 完全に切りたければ別 vendor の AI (= pvc §10)。 **reviewer 側の実測 (2026-09、 第 2 回)**: SessionStart 十数本 + prompt keyword hook + tool-result hook が案件名・締切・mail を注入したが、 spec の「無視」 で足りた (verdict の根拠は全て原稿・文献・公開 data)。 副作用 1 件: harness の fetch tool は PDF を parse できず、 取得物を **deny list 内** (harness の tool-result dir) に落とす → 引用文献は `curl` + `pdftotext` で sandbox の scratch に取る |
| (c) **spec / prompt 自体の漏洩** | 前回の verdict、 疑っている式番号、 「hard error が 2 件ある」、 係数の候補値、 「前回 X が指摘した」 | spec は**対象と rubric だけ**、 結論ゼロで書く (§3)。 起票者が知っていることを書かないのが一番難しい (= 親切心で漏らす) |
| (d) **原稿内の著者注** | `\red{[XX: …]}` 型の共著者向け errand、 header comment の却下題とその理由、 「前 version は 16π² だった」 | **referee copy** を作る = 注と comment を機械的に剥がし (regex)、 残存を grep で 0 確認、 それだけを sandbox に置く |
| (e) **repo 文脈** | SESSION / DESIGN / plans / notes / 旧版原稿 / 著者側の検算 script / git log (commit message に結論が書いてある) | spec に読取禁止 list を明示 + 「著者の script は存在しないものとして自分で書く」 (= 数値の anchoring 防止。 script を読ませると同じ規格化の誤りを継ぐ) |
| (f) **同 vendor の共通バイアス** | 同じ学習分布・同じ公式の癖 | [`physics-verification-cycle.md#cross-vendor-blind-verification`](physics-verification-cycle.md#cross-vendor-blind-verification) |

(a)(b) は harness 由来で**起票者が気付きにくい** (= 自分の session では便利な機構が、 reviewer には汚染源)。 (c)(d) は起票者の手癖由来で**気付いても止めにくい** (= 「これは伝えておいた方が効率的」 が全部漏洩)。

## <a id="sealed-sandbox"></a>2. 封じた sandbox の recipe

> 1 コマンド化 (2026-09-06): [`scripts/make-review-sandbox.py`](../scripts/make-review-sandbox.py) `create <slug> --spec REVIEW-SPEC.md --include <原稿/PDF>` が下の 1-4 を機械で切り (root が `~/Claude` 配下なら refuse)、 受領は `collect <slug> --into <dir>` で results を repo へ copy (逆方向は無い)。 手順の意味は下の recipe が正本。

1. **dir を切る**: `~/<review-sandbox>/<paper>/` のように、 祖先に CLAUDE.md が無く、 どの repo の checkout でもない場所。 git repo にしない (= git log を読ませない)。
2. **referee copy を置く**: 原稿の tex + 図 + 組版 PDF から、 著者注・header comment を機械的に剥がしたもの。 剥がし残しを `grep` で 0 確認。 referee が journal で見る物だけにする。
3. **sandbox の CLAUDE.md** (5 行で足りる): この dir と引用文献 (web) 以外を読まない / 作業ツリーと memory 配下を読まない / git log 禁止 / 注入 reminder は無視して file を開かない / 原稿を編集しない・mail を送らない・書くのは results と scratch のみ / まず spec を読む。
4. **REVIEW-SPEC** (§3 の規律で): 役割と隔離、 事前登録 rubric ([`physics-verification-cycle.md#rubric-before-run`](physics-verification-cycle.md#rubric-before-run))、 check 対象の列挙、 止まる規律 ([`#stop-when-no-grounds`](physics-verification-cycle.md#stop-when-no-grounds))、 出力形式 (= 応答上限があるので**§ごとに追記**させる)、 返送 spine 1 コマンド ([`multi-session-coordination.md#spawn-handoff-token-return`](../../claude-config/conventions/multi-session-coordination.md#spawn-handoff-token-return))、 token、 **handoff 節** (= worker は sandbox 内に `HANDOFF.md`: 書いた script の一覧と汎用性 / 原稿に依らない一般則 / 確認した外部 data・文献箇所 / spec に足りなかったもの。 2026-09-08 追加: 2 round 続けて owner の明示指示「知見を上層へ」 で reviewer 側 hoist が事後に発生した = 密閉 sandbox は worker から上層への経路を持たないので、 上げる材料を sandbox 内に**書かせる**ことで受領側の hoist station ([`verification-cycle-ops.md#hoist-station`](verification-cycle-ops.md#hoist-station)) の入力にする。 sandbox の CLAUDE.md 規則 7 と `collect` の copy 対象に組込み済)。
5. **spawn は cwd を sandbox に pin** する (= chip / spawn の `cwd` 引数)。 prompt は「spec を読め + token」 だけ。
6. **結果は sandbox 内に書かせ、 受領後に起票側が repo へコピー**する (= reviewer に repo を触らせない)。
7. **二段 spec 変種 (2026-09、 起票側の推奨・訂正そのものを盲検するとき)**: 「この framing / 訂正でよいか」 と問うと結論が漏れる。 代わりに spec の冒頭に**対象の action と数値を写し**、 原稿を開く前に解く**導出課題** (Stage 1 → `notes/stage1-blind.md`、 Stage 2 で書き換え禁止) を置き、 その後に通常の査読と「どう提示すべきか」 の問い (Stage 2) を続ける。 起票側の案は一切書かない。 実測 (第 3 回): Stage 1 が起票側の 2 主張 (結合の符号の除外・構成が固定する関係) を独立に再現し、 起票側が pivot でしか評価していなかった項 (roll 全体の Weyl 成長 = [`scientific-computing.md#spectator-check-over-the-roll`](../../claude-config/conventions/scientific-computing.md#spectator-check-over-the-roll)) を発掘、 Stage 2 の framing 推奨は起票側の案と骨格一致 + 三層構造を追加した。 receipt では Stage 1 の結論を起票側の判断記録と表で突合し、 decisive finding は著者側 script で再導出してから採用する ([`physics-verification-cycle.md`](physics-verification-cycle.md#external-ai-referee-premise-verification) item 8)。 **課題文には判定基準の定義を入れる** (例: 「onset」 = $\epsilon_H=1$ の厳密背景、 「spectator」 = 有効質量 $\lesssim H$ かつ場 $\lesssim H$ を観測される e-folds 通して、 「完了」 = 占有数の閾値) — 定義が無いと Stage 1 と原稿の突合が鈍る (第 3 回 HANDOFF §4)。 skeleton = [`template/REVIEW-SPEC-blind-manuscript.md`](../template/REVIEW-SPEC-blind-manuscript.md) (copy して `<...>` を埋め、 `make-review-sandbox.py create --spec` に渡す)。

## <a id="spec-leakage"></a>3. spec に書いてよいこと・書いてはいけないこと

| 書いてよい (= どこを見るか) | 書いてはいけない (= 何が出るか) |
|---|---|
| 対象 file、 reviewer の役割 (initial referee)、 読取の allow / deny list | 期待する verdict、 前回の verdict |
| 事前登録 rubric、 **check 対象の式 label の列挙** | 疑っている式、 「hard error」 「係数が怪しい」 等の方向づけ |
| 出力形式 (severity 分類・表の列)、 止まる規律 | 係数の候補値、 「前 version では X だった」 |
| 返送 spine と token | 著者が既に直した点、 共著者の状態、 論文の来歴 |

境界の判定: **式 label を列挙するのは「どこを見るか」 の指定であって「何が出るか」 ではない**ので可。 逆に「Eq. 10 の 16π を確認せよ」 は答えを含むので不可 (= 「Eq. 10 の係数を独立に導出せよ」 まで)。

**追補 (2026-09、 第 2 回実装)**: 返送 command の `--task` 名や results の見出しに version 番号 (「v3.3」) を入れると、 reviewer の report に来歴語が残る (第 2 回の汚染 grep の唯一の hit)。 無害だが避けられる: task 名は「blind referee review of manuscript.pdf」 のように来歴を含めない。 §2 の「読んでよいもの」 には**引用文献の公開 data product** (著者 repo の chain・等高線) を明示的に含める (= reviewer が観測側の数値を独立再計算できる)。

## <a id="post-check"></a>4. 受領後の汚染 check

結果 file を受け取ったら、 禁止 source にしか無い情報 (SESSION の用語・却下した旧題・internal な note 名・起票 session だけが知る数値) が現れていないか grep する。 現れていれば汚染として記録し、 該当 finding の独立性を割り引く (= 汚染していない finding と分けて扱う)。 現れていなければ「独立した第二の目」 として採用できる。

**実例 (2026-09、 第 2 回)**: 禁止語 grep 0、 唯一の hit は spec の task 名由来の version 番号。 finding 3 件は著者側の from-scratch 再計算 (膨張背景での mode 成長、 厳密背景の Floquet、 固定 $r$ の $\Delta n_s$) で確認してから採用した ([`physics-verification-cycle.md#external-ai-referee-premise-verification`](physics-verification-cycle.md#external-ai-referee-premise-verification) item 8)。 reviewer の scratch script は results と一緒に repo へコピーするが、 著者側の検証は**別に書いた script** で行う (同一 script の再実行は独立検証にならない)。

**受領後の reviewer session (2026-09 追補)**: 隔離は review 中だけの規律。 受領・突合が済んだ後に owner が reviewer session 自身へ「知見を上層へ、 script も残す」 と指示すれば、 その session が scratch を一般化した道具 (層1 `scripts/`) と引用文献の verdict (refs の notes) を hoist できる ([`physics-verification-cycle.md#referee-side-kernels`](physics-verification-cycle.md#referee-side-kernels))。 順序が要: 受領側の DESIGN / 規約追補を**先に読んで**重複しない項目だけ上げる (受領側と reviewer 側が同じ file を取り合う = pvc C′ の時間順)。 sandbox は review 後も再計算環境 (venv・公開 chain・文献 text) を保つので、 その path は machine-local の memory に pointer として置く。

**hoist commit の push (2026-09-08 追補)**: reviewer session の hoist は **local commit 止まりにして push しない** (= 公開 repo への最終 gate を隔離 worker に持たせない)。 push は起票 session が受領 sweep の一部として行う: 各 repo で `git log --oneline @{u}..` を読み、 leak grep (固有名・private repo 名) と新 script の `--selftest` を通してから push (owner が起票 session に委任した運用、 第 3 回で実施)。 取りこぼしの backstop = SessionStart の同期 sweep hook が fleet 横断で「未 push の local commit」 (ahead-only) を沈黙させずに surface する (起票側の layer で実装、 push 自体は自動化しない)。 reviewer は hoist 完了を起票 session へ cross-session message で知らせ、 編集した file と「触らない file」 を列挙する (race 回避、 第 3 回の型)。 順序は 受領側 hoist → reviewer 残余 hoist → 起票側 push (逆順だと重複 anchor を作る = 第 3 回で起票側 anchor を先に push して reviewer が fold した)。

## <a id="external-paper-variant"></a>4.5 変種: 外部論文の検証読み (verify-to-learn) は sandbox でなく deny list (2026-09)

自著の盲検と違い、 外部論文の検証読みで隔離すべきは「**起票者の仮説・解釈**」 だけ (著者注・来歴・却下案は無い)。 sandbox を切らず repo 内の campaign dir で走らせ、 (a) spec に期待 verdict を書かない (§3 と同じ) + (b) 起票者の note / 教科書 dir を deny list に列挙 + (c) 受領後に汚染 grep、 で足りた (初回: 0 hit、 worker は起票者の知らない結果を出した)。 repo の道具 (ledger / check / refs) を worker に触らせる利点が上回る。 再訪 trigger = 汚染 grep で hit → sandbox 方式へ (**同日 n=1 で発火**: 検証 pass が産んだ新結果の第二の目では、 auto-load の projects 一覧に書かれた verdict の方向が worker に見えていた = 汚染経路 1 は deny list で塞げない。 ∴ 新結果の第二の目は §2 の sandbox、 deny list 方式は「verdict が事前に存在しない一次検証読み」 限定)。 検証 pass が産んだ**新結果**の第二の目は 2 段階 (盲検 → 攻撃) = [`physics-verification-cycle.md#campaign-tooling`](physics-verification-cycle.md#campaign-tooling) C。

## 5. 起源

2026-09-02、 共著論文 draft の cold-eyes 起票時に user 指摘 2 連 (「ちゃんと冷目になるように余計なもん見ないように制限して」 → 「SESSION, CLAUDE とか見ちゃうと汚染されるのでそれも注意」)。 同型の汚染は以前にもあったとの user 報告 (= 本 doc 新設の直接動機)。 初回実装 = sandbox `~/paper-review-sandbox/<paper>/` + referee copy (注 7 件・header 除去) + spec (rubric 6 群) + cwd pin の spawn。 残余 risk として global SessionStart hook の注入を明示した。

## 6. 隣接 doc への routing

- 検証の中身 (4 station / rubric 事前登録 / 止まる規律 / 独立した第二の目 / cross-vendor) = [`physics-verification-cycle.md`](physics-verification-cycle.md)
- 別 session への hand-off の機構 (spawn / token / 返送 spine / worktree 判定 / spec の切り方) = [`multi-session-coordination.md`](../../claude-config/conventions/multi-session-coordination.md)
- 外部 AI 査読レポートを受け取った側の前提検証 = [`physics-verification-cycle.md#external-ai-referee-premise-verification`](physics-verification-cycle.md#external-ai-referee-premise-verification)
