"""
빠른 전체 크롤링 (crawl_kma.py 와 같은 전처리, 다른 쿼리 전략)

느린 이유: 기존 방식은 영문 2-gram 676개로 '포함 검색'을 하므로 한 용어를 평균 10번 이상
중복으로 받아옵니다. 여기서는
  1) 사이트의 a~z 알파벳 목록(첫 글자 검색)으로 각 용어를 한 번씩만 받고
     (6판 기준 영문 용어는 4개 빼고 전부 a~z 로 시작)
  2) 숫자 0~9 포함 검색으로 나머지를 채우고
  3) 6판(data/sources/kma.csv)에 있었는데 이번에 안 잡힌 용어는 그 용어로 한 번 더 검색해
     빠진 게 없게 확인합니다.
  4) 요청은 동시에 몇 개씩(--workers, 기본 4) 보냅니다.

사용법 (레포 루트에서):
    py scripts\\crawl_kma_fast.py --probe   # 알파벳 목록 방식이 되는지 확인만 (몇 초)
    py scripts\\crawl_kma_fast.py           # 전체 크롤링 → data/sources/kma.csv
"""
import argparse
import datetime
import json
import math
import os
import string
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crawl_kma as base  # noqa: E402  (전처리·파서·판 감지 재사용)

_local = threading.local()


def sess():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": base.LIST_URL})
        _local.s = s
    return s


def fetch(params, method="GET", tries=6):
    backoff, last = 0.5, None
    for _ in range(tries):
        try:
            if method == "GET":
                r = sess().get(base.LIST_URL, params=params, timeout=base.TIMEOUT)
            else:
                r = sess().post(base.LIST_URL, data=params, timeout=base.TIMEOUT)
            if not r.encoding or r.encoding.lower() == "iso-8859-1":
                r.encoding = r.apparent_encoding
            if r.status_code == 429 or 500 <= r.status_code < 600:
                last = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(backoff)
                backoff = min(backoff * 2, 10)
                continue
            r.raise_for_status()
            time.sleep(base.DELAY)
            return r.text
        except requests.RequestException as e:
            last = e
            time.sleep(backoff)
            backoff = min(backoff * 2, 10)
    raise RuntimeError(f"요청 실패: {last}")


class Mode:
    """알파벳 목록 요청 방식 (GET/POST 중 사이트가 받아주는 쪽)"""

    def __init__(self, t1, t2):
        self.t1, self.t2 = t1, t2
        self.method = None
        self.n = t1.replace("twdContent", "")

    def contains(self, q, page):
        return {"pageno": page, "sch_txt": q, "sch_type1": self.t1, "sch_type2": self.t2}

    def spelling(self, letter, page):
        return {"pageno": page, "sch_txt": letter, "sch_type1": self.t1, "sch_type2": self.t2,
                "sch_type": f"{self.t1}/{self.t2}", "sch_type_chk": self.n, "spelling_chk": "1"}

    def probe(self):
        letter = "x"
        h = fetch(self.contains(letter, 1))
        contains_total = base.extract_total_count(h)
        for method in ("GET", "POST"):
            h = fetch(self.spelling(letter, 1), method)
            total = base.extract_total_count(h)
            pairs = base.parse_pairs_searchlist(h)
            starts = pairs and all(t.lower().startswith(letter) for t, _ in pairs)
            print(f"  [{method}] '{letter}' 첫 글자 목록: 총 {total}개, 1쪽 {len(pairs)}개, "
                  f"모두 '{letter}'로 시작: {bool(starts)}  (포함 검색은 총 {contains_total}개)")
            if starts and total is not None and (contains_total is None or total < contains_total):
                # 2쪽도 같은 방식으로 넘어가는지 확인
                if total > len(pairs):
                    p2 = base.parse_pairs_searchlist(fetch(self.spelling(letter, 2), method))
                    ok2 = p2 and all(t.lower().startswith(letter) for t, _ in p2) and p2 != pairs
                    print(f"  [{method}] 2쪽 확인: {bool(ok2)}")
                    if not ok2:
                        continue
                self.method = method
                return True
        return False


def crawl_listing(make_params, method, label, workers, log):
    """1쪽으로 총 개수를 보고 나머지 쪽을 병렬로 받음"""
    h1 = fetch(make_params(1), method)
    total = base.extract_total_count(h1)
    p1 = base.parse_pairs_searchlist(h1)
    if not p1:
        return []
    pages = max(1, math.ceil(total / len(p1))) if total else 1
    results = {1: p1}
    if pages > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(lambda p: base.parse_pairs_searchlist(fetch(make_params(p), method)), p): p
                    for p in range(2, pages + 1)}
            done = 0
            for f in as_completed(futs):
                results[futs[f]] = f.result()
                done += 1
                if done % 50 == 0:
                    log(f"    {label}: {done + 1}/{pages}쪽")
    out = []
    for p in sorted(results):
        out.extend(results[p])
    log(f"  {label}: 총 {total}개 예상, {pages}쪽, 받은 행 {len(out)}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--workers", type=int, default=4, help="동시 요청 수 (기본 4, 너무 올리지 마세요)")
    ap.add_argument("--edition", default=None)
    args = ap.parse_args()

    os.makedirs(base.SRC_DIR, exist_ok=True)
    os.makedirs(base.CACHE_DIR, exist_ok=True)

    def log(msg):
        print(msg, flush=True)

    t1, t2, label, _ = base.detect_types(verbose=False)
    log(f"판: {label or '?'}  (sch_type1={t1}, sch_type2={t2})")
    mode = Mode(t1, t2)
    log("알파벳 목록 방식 확인 중…")
    if not mode.probe():
        log("\n❌ 알파벳 목록 방식이 이 사이트에서 확인되지 않았습니다. "
            "기존 crawl_kma.py 를 계속 쓰세요.")
        return 1
    log(f"✅ 사용 가능 ({mode.method})")
    if args.probe:
        log("\n--probe 라 여기서 끝납니다. 옵션 없이 다시 실행하면 전체 크롤링을 시작합니다.")
        return 0

    started = time.time()
    seen, rows = set(), []

    def add(pairs):
        n = 0
        for k in pairs:
            if k not in seen:
                seen.add(k)
                rows.append(k)
                n += 1
        return n

    # 1) a~z 첫 글자 목록
    for letter in string.ascii_lowercase:
        pairs = crawl_listing(lambda p, L=letter: mode.spelling(L, p), mode.method,
                              f"'{letter}'", args.workers, log)
        log(f"  → 새로 {add(pairs)}개, 누적 {len(seen):,}  ({time.time() - started:.0f}초)")

    # 2) 숫자 포함 검색
    for d in base.DIGITS:
        pairs = crawl_listing(lambda p, q=d: mode.contains(q, p), "GET", f"숫자 '{d}'", args.workers, log)
        log(f"  → 새로 {add(pairs)}개, 누적 {len(seen):,}")

    # 3) 6판에 있었는데 안 잡힌 용어 재확인
    old_rows, _ = base.load_csv(base.OUT_CSV)
    got_terms = {t for t, _ in rows}
    missing = sorted({t for t, _ in old_rows} - got_terms)
    log(f"\n6판에 있었는데 아직 안 잡힌 용어 {len(missing)}개 재검색…")
    rescued = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(lambda q: base.parse_pairs_searchlist(fetch(mode.contains(q, 1))), t): t
                for t in missing[:5000]}
        for f in as_completed(futs):
            try:
                rescued += add(f.result())
            except Exception as e:  # noqa: BLE001
                log(f"  재검색 실패 '{futs[f]}': {e}")
    still = sorted({t for t, _ in old_rows} - {t for t, _ in rows})
    log(f"  재검색으로 {rescued}개 추가. 6.1판에서 없어진 것으로 보이는 용어 {len(still)}개")

    # 저장 (crawl_kma.py 와 같은 형식)
    with open(base.OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        import csv
        w = csv.writer(f)
        w.writerow(["term", "korean"])
        w.writerows(rows)
    meta = {
        "edition": args.edition or "6.1판",
        "crawled": datetime.date.today().isoformat(),
        "sch_type1": t1, "sch_type2": t2, "type1_label": label,
        "count": len(rows), "method": f"spelling a-z ({mode.method}) + digits + recheck",
        "not_found_from_previous": len(still),
    }
    with open(base.META_JSON, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log(f"\n완료: {len(rows):,}개 → data/sources/kma.csv  ({(time.time() - started) / 60:.1f}분)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
