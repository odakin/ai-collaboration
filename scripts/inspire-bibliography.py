#!/usr/bin/env python3
"""INSPIRE-HEP からの書誌・業績統計の照合 (審査・査読で申請書/論文の自己申告を機械で裏取りする): 引用文献リストの現物確認 (arXiv id → 題・著者順・誌名巻号・被引用)、著者統計 (BAI → 誌上掲載数・総被引用・h 指数・未出版 preprint・所属履歴)、名前 → BAI 解決、null 報告前の positive control。--selftest 内蔵 (network 不要)。

なぜ層1 にあるか
----------------
2026-09-08 の盲検審査 4 本が、独立に同じ形の INSPIRE client を 4 つ書いた
(refs 照合 ×2 / 著者統計 ×1 / arXiv abstract ×1)。 hoist station の
「2 campaign 目で同じ形が要ったら層1 library へ」 (verification-cycle-ops.md#hoist-station 2)
に当たるので 1 本に統合した。

使い方
------
  # 引用文献リストの現物確認 (調書・論文の参考文献が実在し、記載の誌名巻号と一致するか)
  inspire-bibliography.py refs 1904.05699 2010.07867 ...
  inspire-bibliography.py refs -f ids.txt --expect expect.json   # {id: "JCAP 03 (2020) 063"} と照合

  # 著者の業績統計 (「論文 N 編・被引用 M・h 指数 k・直近 3 年で X 編」 の検証)
  inspire-bibliography.py author K.Y.Oda.1 --since 2023

  # 名前 → BAI (上の前提。 ids[schema="INSPIRE BAI"])
  inspire-bibliography.py whois "Oda, Kin-ya"

  # null を報告する前の positive control (検索機構が生きていることの確認)
  inspire-bibliography.py whois "存在しないかもしれない氏名" --control "Oda, Kin-ya"

⚠️ 数え方の罠 (2026-09-08 実測、これを外すと自己申告と 2 件ずれる)
------------------------------------------------------------------
INSPIRE の `publication_info.journal_title` は **会議録 (PoS, Springer Proc.Phys.,
J.Phys.Conf.Ser., AIP Conf.Proc., EPJ Web Conf., Nuovo Cim.C) にも付く**。
「誌上掲載論文 N 編」 型の自己申告は普通これらを含まないので、素朴に
`len([m for m in recs if journal_title])` と比べると申告が過少に見える。
本 script は既定で会議録を除いて数え、`--with-proceedings` で含める。
⚠️ もう 1 つの数え方の罠: 「N 年以降 X 編」 は **掲載年 (publication_info.year) で数えるか
preprint 初出年 (earliest_date) で数えるか**で件数が変わる (実測で 19 対 17)。 どちらも
正当なので、本 script は常に両方の件数を出し、食い違うときは警告する。 申請書の自己申告を
「一致した / していない」 と判定する前に、**申告がどちらの定義か**を確かめること。
片方だけ数えて「✅ 一致」 と書くと、定義違いを検証済みに見せてしまう。

API のこつ
----------
- `fields=` で絞ると 250 件 page でも軽い。 h 指数・総被引用は author page の
  表示値を API では直接取れないので、全 record を引いて自分で集計する。
- 1 query = 1 arXiv id の照合は `q=arxiv:<id>`。 旧式 id (`gr-qc/9403058`) も可。
- 著者の同定は BAI (`K.Y.Oda.1`) が最も確実。 姓名 query は同姓の別人を掴む。
- 経歴 (研究員歴・海外滞在) は `authors.affiliations` を論文の年で並べると
  authors API の positions が空でも復元できる。
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

API = "https://inspirehep.net/api"
UA = {"User-Agent": "inspire-bibliography/1.0 (research bibliography verification)"}

# journal_title に現れるが「誌上掲載論文」 とは普通数えない会議録 series。
PROCEEDINGS_MARKERS = (
    "PoS",
    "Springer Proc",
    "J.Phys.Conf.Ser",
    "AIP Conf.Proc",
    "EPJ Web Conf",
    "Nuovo Cim.C",
    "Conf.Proc.",
    "Proceedings",
)


# ---------------------------------------------------------------- pure helpers
# (network を触らないので selftest が offline で回る)

def is_proceedings(journal_title):
    """会議録 series 名か。"""
    if not journal_title:
        return False
    return any(m.lower() in journal_title.lower() for m in PROCEEDINGS_MARKERS)


def journal_entries(meta, with_proceedings=False):
    """metadata から誌上掲載の publication_info だけを返す。"""
    out = []
    for p in meta.get("publication_info", []) or []:
        jt = p.get("journal_title")
        if not jt:
            continue
        if not with_proceedings and is_proceedings(jt):
            continue
        out.append(p)
    return out


def format_pub(p):
    """publication_info 1 件を 'JCAP 03 (2020) 063' 形式へ。"""
    return " ".join(
        str(x)
        for x in (
            p.get("journal_title", "?"),
            p.get("journal_volume", ""),
            f"({p.get('year', '?')})",
            p.get("artid") or p.get("page_start") or "",
        )
        if str(x).strip()
    )


def format_pubs(meta, with_proceedings=False):
    js = journal_entries(meta, with_proceedings)
    return "; ".join(format_pub(p) for p in js) if js else "(no journal on INSPIRE)"


def is_published(meta, with_proceedings=False):
    return bool(journal_entries(meta, with_proceedings))


def pub_year(meta, with_proceedings=False):
    ys = [p.get("year") for p in journal_entries(meta, with_proceedings) if p.get("year")]
    return max(int(y) for y in ys) if ys else None


def h_index(citations):
    """h 指数 = c_i >= i を満たす最大の i (降順)。"""
    cs = sorted(citations, reverse=True)
    return sum(1 for i, c in enumerate(cs) if c >= i + 1)


def normalize_ref(s):
    """誌名巻号文字列を比較用に正規化 (空白・約物・大小の揺れを吸収)。"""
    if not s:
        return ""
    return "".join(ch.lower() for ch in s if ch.isalnum())


def ref_matches(printed, found):
    """調書の記載 printed が INSPIRE の found と整合するか (緩い包含)。"""
    p, f = normalize_ref(printed), normalize_ref(found)
    return bool(p) and (p in f or f in p)


# ------------------------------------------------------------------- transport

def _get(url, timeout=90):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def literature(query, fields, size=25, page=1, sort=None):
    url = (
        f"{API}/literature?q={urllib.parse.quote(query)}"
        f"&size={size}&page={page}&fields={','.join(fields)}"
    )
    if sort:
        url += f"&sort={sort}"
    return _get(url)


REF_FIELDS = [
    "titles.title",
    "authors.full_name",
    "publication_info",
    "citation_count",
    "arxiv_eprints.value",
    "control_number",
    "earliest_date",
    "document_type",
]

AUTHOR_FIELDS = [
    "citation_count",
    "earliest_date",
    "publication_info",
    "document_type",
    "titles.title",
    "arxiv_eprints.value",
    "authors.full_name",
    "authors.affiliations.value",
    "authors.ids.value",
]


# --------------------------------------------------------------------- actions

def cmd_refs(args):
    ids = args.ids
    if args.file:
        ids = [l.strip() for l in open(args.file) if l.strip() and not l.startswith("#")]
    expect = json.load(open(args.expect)) if args.expect else {}
    out, bad = {}, 0
    for i, arx in enumerate(ids, 1):
        try:
            hits = literature(f"arxiv:{arx}", REF_FIELDS, size=1)["hits"]["hits"]
        except Exception as ex:  # noqa: BLE001 - report, keep going
            print(f"[{i}] {arx}: ERROR {ex}")
            bad += 1
            continue
        if not hits:
            print(f"[{i}] {arx}: NOT FOUND on INSPIRE")
            out[arx] = None
            bad += 1
            time.sleep(args.sleep)
            continue
        m = hits[0]["metadata"]
        authors = [a["full_name"] for a in m.get("authors", []) or []]
        pubs = format_pubs(m, args.with_proceedings)
        rec = {
            "title": m["titles"][0]["title"],
            "authors": authors,
            "journal": pubs,
            "citations": m.get("citation_count"),
            "recid": m.get("control_number"),
            "date": m.get("earliest_date"),
        }
        out[arx] = rec
        print(f"[{i}] {arx}: {rec['title']}")
        print(f"     {', '.join(authors)}  (n={len(authors)})")
        print(f"     {pubs} | cites {rec['citations']} | recid {rec['recid']} | {rec['date']}")
        if arx in expect:
            ok = ref_matches(expect[arx], pubs)
            print(f"     {'OK  ' if ok else 'MISMATCH'} 記載: {expect[arx]}")
            if not ok:
                bad += 1
        time.sleep(args.sleep)
    if args.json:
        json.dump(out, open(args.json, "w"), indent=1, ensure_ascii=False)
        print(f"\nwrote {args.json}")
    print(f"\n{len(ids)} refs checked, {bad} problem(s)")
    return 1 if bad else 0


def fetch_author_records(bai, sleep=0.5):
    recs, page = [], 1
    while True:
        d = literature(f"a {bai}", AUTHOR_FIELDS, size=250, page=page)
        hits = d["hits"]["hits"]
        recs += [h["metadata"] for h in hits]
        if len(hits) < 250:
            return recs
        page += 1
        time.sleep(sleep)


def cmd_author(args):
    bai, since, wp = args.bai, args.since, args.with_proceedings
    recs = fetch_author_records(bai, args.sleep)
    if not recs:
        print(f"{bai}: 0 records — BAI が誤っている可能性。 whois で解決し、")
        print("  --control で検索機構が生きていることを確かめてから null を報告すること。")
        return 1
    cites = [m.get("citation_count", 0) or 0 for m in recs]
    pub = [m for m in recs if is_published(m, wp)]
    proc = [m for m in recs if is_published(m, True) and not is_published(m, False)]
    print(f"{bai}")
    print(f"  records                 {len(recs)}")
    print(f"  誌上掲載 (会議録を除く)  {len(pub)}   [会議録 {len(proc)} 件を除外{' しない設定' if wp else ''}]")
    print(f"  総被引用                {sum(cites)}")
    print(f"  h 指数                  {h_index(cites)}  (誌上のみ {h_index([m.get('citation_count', 0) or 0 for m in pub])})")
    # ⚠️ 「N 年以降 X 編」 は数え方で変わる。 両方出して、どちらの定義かを読み手に渡す。
    by_pub = [m for m in pub if (pub_year(m, wp) or 0) >= since]
    by_first = [m for m in pub if (m.get("earliest_date") or "")[:4] >= str(since)]
    print(f"\n  誌上掲載 {since} 年以降:  掲載年で {len(by_pub)} 編 / preprint 初出年で {len(by_first)} 編")
    if len(by_pub) != len(by_first):
        print("    ⚠️ 定義で数が変わる。 調書の自己申告がどちらの数え方かを確かめてから判定すること")
        print("       (掲載年 = 誌上に載った年、 初出年 = arXiv 等に最初に出た年)。")
    recent = by_pub if args.by == "pubyear" else by_first
    print(f"    [--by {args.by} で採った {len(recent)} 編]")
    for m in sorted(recent, key=lambda m: pub_year(m, wp) or 0):
        print(f"    {pub_year(m, wp)}  ({(m.get('earliest_date') or '?')[:7]})  {m['titles'][0]['title'][:60]}")
    if proc and not wp:
        print(f"\n  (参考) 除外した会議録 {len(proc)} 件:")
        for m in proc:
            print(f"    {pub_year(m, True)}  {format_pubs(m, True)[:60]}  {m['titles'][0]['title'][:50]}")
    unpub = [m for m in recs if not is_published(m, True) and (m.get("earliest_date") or "") >= str(since)]
    print(f"\n  未出版 (誌名なし) {since} 年以降: {len(unpub)} 件")
    for m in sorted(unpub, key=lambda m: m.get("earliest_date") or ""):
        arx = (m.get("arxiv_eprints") or [{}])[0].get("value", "-")
        print(f"    {m.get('earliest_date')}  arXiv:{arx}  cites {m.get('citation_count')}  {m['titles'][0]['title'][:52]}")
    print("\n  上位被引用:")
    for m in sorted(recs, key=lambda m: -(m.get("citation_count") or 0))[:args.top]:
        print(f"    {m.get('citation_count'):5}  {m['titles'][0]['title'][:60]}  {format_pubs(m, True)[:34]}")
    hist = {}
    for m in recs:
        for a in m.get("authors", []) or []:
            if any(i.get("value") == bai for i in a.get("ids", []) or []):
                affs = tuple(x["value"] for x in a.get("affiliations", []) or [])
                if affs:
                    hist.setdefault(affs, []).append(m.get("earliest_date") or "")
    print("\n  所属履歴 (論文の所属から。 authors API の positions が空でも復元できる):")
    for affs, dates in sorted(hist.items(), key=lambda kv: min(kv[1])):
        print(f"    {min(dates)[:7]} … {max(dates)[:7]}  ({len(dates):3} 編)  {', '.join(affs)}")
    return 0


def cmd_whois(args):
    def lookup(name):
        url = f"{API}/authors?q={urllib.parse.quote(name)}&size=8&fields=name,ids,positions"
        return _get(url)["hits"]["hits"]

    hits = lookup(args.name)
    for h in hits:
        m = h["metadata"]
        bai = next((i["value"] for i in m.get("ids", []) if i.get("schema") == "INSPIRE BAI"), "?")
        orcid = next((i["value"] for i in m.get("ids", []) if i.get("schema") == "ORCID"), "")
        cur = [p.get("institution") for p in m.get("positions", []) or [] if p.get("current")]
        print(f"  {bai:24} {m['name'].get('value', '?')}   {('ORCID ' + orcid) if orcid else ''}  {('now: ' + ', '.join(cur)) if cur else ''}")
    if not hits:
        print(f"  (0 hit) {args.name}")
        if args.control:
            ctl = lookup(args.control)
            print(f"  positive control {args.control!r}: {len(ctl)} hit")
            if not ctl:
                print("  ⚠️ control も 0 = 検索機構側の問題。 『該当なし』 と報告してはいけない。")
                return 2
            print("  control は引けたので、機構は生きている = この null は報告してよい。")
        else:
            print("  ⚠️ --control <実在が確実な氏名> を付けて、機構が生きていることを")
            print("     確かめてから null を報告すること (単一 source の null 禁則)。")
            return 2
    return 0


# -------------------------------------------------------------------- selftest

def selftest():
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    # 会議録の判定 (この script の存在理由)
    check("PoS is proceedings", is_proceedings("PoS"), True)
    check("Springer Proc", is_proceedings("Springer Proc.Phys."), True)
    check("J.Phys.Conf.Ser", is_proceedings("J.Phys.Conf.Ser."), True)
    check("JCAP is not", is_proceedings("JCAP"), False)
    check("PRD is not", is_proceedings("Phys.Rev.D"), False)
    check("PLB is not", is_proceedings("Phys.Lett.B"), False)
    check("None is not", is_proceedings(None), False)

    # 実測の型: journal 19 件のうち PoS 1 + Springer Proc 1 を除くと 17 (自己申告と一致)
    recs = (
        [{"publication_info": [{"journal_title": "Phys.Rev.D", "year": 2024}]} for _ in range(17)]
        + [{"publication_info": [{"journal_title": "PoS", "year": 2024}]}]
        + [{"publication_info": [{"journal_title": "Springer Proc.Phys.", "year": 2024}]}]
        + [{"publication_info": []}, {}]
    )
    check("journal excl. proceedings", sum(1 for m in recs if is_published(m)), 17)
    check("journal incl. proceedings", sum(1 for m in recs if is_published(m, True)), 19)

    # h 指数
    check("h of []", h_index([]), 0)
    check("h of [0,0]", h_index([0, 0]), 0)
    check("h of [3,2,1]", h_index([3, 2, 1]), 2)
    check("h of [10,8,5,4,3]", h_index([10, 8, 5, 4, 3]), 4)  # 5 本目の 3 < 5 で止まる
    check("h of [10,8,5,5,5]", h_index([10, 8, 5, 5, 5]), 5)
    check("h of [1]*10", h_index([1] * 10), 1)

    # 誌名の整形と照合
    p = {"journal_title": "JCAP", "journal_volume": "03", "year": 2020, "artid": "063"}
    check("format_pub", format_pub(p), "JCAP 03 (2020) 063")
    check("match exact", ref_matches("JCAP 03 (2020) 063", "JCAP 03 (2020) 063"), True)
    check("match spacing", ref_matches("JCAP03(2020)063", "JCAP 03 (2020) 063"), True)
    check("mismatch volume", ref_matches("JCAP 04 (2020) 063", "JCAP 03 (2020) 063"), False)
    check("empty printed", ref_matches("", "JCAP 03 (2020) 063"), False)

    # pub_year は誌上掲載の年 (preprint の earliest_date ではない)
    m = {"publication_info": [{"journal_title": "Phys.Rev.D", "year": 2025}], "earliest_date": "2024-11-26"}
    check("pub_year", pub_year(m), 2025)
    check("pub_year none", pub_year({"publication_info": []}), None)

    if fails:
        print("SELFTEST FAILED")
        for f in fails:
            print("  -", f)
        return 1
    print("selftest OK (会議録除外 / h 指数 / 誌名照合 / 掲載年、 network 不要)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true", help="offline selftest")
    sub = ap.add_subparsers(dest="cmd")

    r = sub.add_parser("refs", help="引用文献リストを arXiv id で現物確認")
    r.add_argument("ids", nargs="*")
    r.add_argument("-f", "--file", help="1 行 1 id の file")
    r.add_argument("--expect", help='{"<id>": "<記載の誌名巻号>"} の JSON と照合')
    r.add_argument("--json", help="結果を JSON で保存")
    r.add_argument("--with-proceedings", action="store_true")
    r.add_argument("--sleep", type=float, default=0.5)
    r.set_defaults(func=cmd_refs)

    a = sub.add_parser("author", help="BAI から業績統計")
    a.add_argument("bai")
    a.add_argument("--since", type=int, default=2023)
    a.add_argument("--by", choices=("pubyear", "earliest"), default="pubyear",
                   help="「N 年以降」 の数え方: pubyear=誌上掲載年 (既定) / earliest=preprint 初出年。 両方の件数は常に表示する")
    a.add_argument("--top", type=int, default=6)
    a.add_argument("--with-proceedings", action="store_true", help="会議録も誌上掲載に数える")
    a.add_argument("--sleep", type=float, default=0.5)
    a.set_defaults(func=cmd_author)

    w = sub.add_parser("whois", help="氏名 → BAI")
    w.add_argument("name")
    w.add_argument("--control", help="null 報告前の positive control に使う実在が確実な氏名")
    w.set_defaults(func=cmd_whois)

    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not getattr(args, "func", None):
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
