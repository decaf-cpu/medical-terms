"""
data/sources/*.csv → data/terms.json

- kma.csv      : 의협 의학용어 (crawl_kma.py 결과), 판 정보는 kma.meta.json
- prevmed.csv  : 대한예방의학회 의학용어집 (뜻풀이 끝에 [예방] 태그 포함)
- 그 밖의 *.csv: 수동 추가분 등 (term,korean 2열)

(term, korean) 완전 일치 기준으로 중복 제거하고, 직전 terms.json 대비
추가/삭제 목록을 reports/changes_YYYY-MM-DD.csv 로 남깁니다.

사용법 (레포 루트에서):  python scripts/build_data.py [--updated YYYY-MM-DD]
"""
import argparse
import csv
import datetime
import glob
import html
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "data", "sources")
OUT_JSON = os.path.join(ROOT, "data", "terms.json")
REPORT_DIR = os.path.join(ROOT, "reports")

ORDER = ["kma.csv", "prevmed.csv"]  # 이 순서로 먼저, 나머지는 이름순


def clean_text(x: str) -> str:
    x = html.unescape(x)
    return re.sub(r"\s+", " ", x).strip()


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f)
        header = next(r, None)
        for row in r:
            if len(row) >= 2:
                t, k = clean_text(row[0]), clean_text(row[1])
                if t and k:
                    yield t, k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--updated", help="업데이트 날짜 (기본: kma.meta.json 의 크롤링 날짜)")
    args = ap.parse_args()

    files = [os.path.join(SRC_DIR, n) for n in ORDER if os.path.exists(os.path.join(SRC_DIR, n))]
    files += sorted(p for p in glob.glob(os.path.join(SRC_DIR, "*.csv")) if p not in files)

    seen, terms, per_source = set(), [], {}
    for p in files:
        name = os.path.splitext(os.path.basename(p))[0]
        n = 0
        for key in read_csv(p):
            if key not in seen:
                seen.add(key)
                terms.append(list(key))
                n += 1
        per_source[name] = n
        print(f"{os.path.basename(p):<16} {n:>7,}개")

    meta_path = os.path.join(SRC_DIR, "kma.meta.json")
    kma_meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            kma_meta = json.load(f)

    old = set()
    if os.path.exists(OUT_JSON):
        with open(OUT_JSON, encoding="utf-8") as f:
            old = {tuple(x) for x in json.load(f).get("terms", [])}

    meta = {
        "edition": kma_meta.get("edition", ""),
        "updated": args.updated or kma_meta.get("crawled") or datetime.date.today().isoformat(),
        "count": len(terms),
        "sources": per_source,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "terms": terms}, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    print(f"\n→ data/terms.json  총 {len(terms):,}개  ({meta['edition'] or '판 정보 없음'}, {meta['updated']})")

    if old:
        added = [k for k in (tuple(t) for t in terms) if k not in old]
        removed = sorted(old - seen)
        print(f"직전 대비: +{len(added):,} / -{len(removed):,}")
        if added or removed:
            os.makedirs(REPORT_DIR, exist_ok=True)
            rp = os.path.join(REPORT_DIR, f"changes_{meta['updated']}.csv")
            with open(rp, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["change", "term", "korean"])
                w.writerows(["추가", t, k] for t, k in added)
                w.writerows(["삭제", t, k] for t, k in removed)
            print(f"변경 목록 → {os.path.relpath(rp, ROOT)}")


if __name__ == "__main__":
    main()
