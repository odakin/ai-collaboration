# SESSION.md — ai-collaboration

> 📌 SESSION.md = 案件ごとの現在地 + 正本への link (進んだら置き換える、 日付を見出しにした節・commit hash・messageId を置かない = 層1 claude-config/CONVENTIONS.md#session-no-durable-record)。 日付つきの節は SESSION-archive.md へ verbatim MOVE 済 (2026-09-28)。

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

## 残タスク

- 状態識別の数式と道具を追加。入口 = [証明と利用範囲](docs/state-discrimination.md)、[library](scripts/state_discrimination.py)、[検証時の certificate](conventions/physics-verification-cycle.md#state-discrimination-certificates)。reporter は未知の foil crash と marker 後の非ゼロ終了を失敗にし、`--run` の失敗を呼び元へ返す。実装判断 = DESIGN.md。

- Session 宛て board との受領経路の接続は [verification-cycle-ops](conventions/verification-cycle-ops.md#board-receipt-boundary)。一般則の正本は README から既存 home へ参照し、Phase 2 の移設は未実施。

- [ ] Phase 2 の trigger 監視 (= DESIGN の表): Codex runner Pilot A 開始で `multi-session-coordination.md` と `codex/` を移設

## 決定ログ

- **2026-09-06: 新設** — 判断は DESIGN.md (分離の理由 / Phase 1 の範囲 / 移し方 = format-patch 履歴 import / stub + forwarder / Phase 2 trigger)
