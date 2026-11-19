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

빠짐 방지 장치 (이전 데이터가 없어도 동작하는 것 위주):
  - 목록마다 사이트가 알려준 총 개수와 실제 받은 행 수를 비교, 모자라면 그 쪽만 다시 받음
  - a~z 로 시작하지 않는 용어는 숫자·그리스 문자 포함 검색으로 따로 수집
  - 무작위 3글자 '포함 검색'(--audit, 기본 60개)으로 목록 방식이 놓친 게 있는지 교차 확인
  - 이전 데이터(로컬 kma.csv, 없으면 GitHub 의 현재 데이터)와 비교해 사라진 용어 재검색
  - 전처리 후에도 태그 조각이 남은 행 경고
  이상 징후는 마지막에 모아서 보여주고 kma.meta.json 의 problems 에도 남깁니다.

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
            odd = [t for t, _ in pairs if not t.lower().startswith(letter)]
            print(f"  [{method}] '{letter}' 첫 글자 목록: 총 {total}개, 1쪽 {len(pairs)}개 "
                  f"(포함 검색은 총 {contains_total}개)")
            if odd:
                print(f"     '{letter}'로 시작하지 않는 예: {odd[:5]}")
            # 목록 방식이면 포함 검색보다 훨씬 적게 나옴. 첫 글자가 아닌 항목이 섞여도
            # 빠지는 게 아니라 중복이 조금 생길 뿐이고, 마지막에 6판 대비 재검색으로 한 번 더 확인함.
            if pairs and total is not None and contains_total and total < contains_total * 0.5:
                if total > len(pairs):
                    p2 = base.parse_pairs_searchlist(fetch(self.spelling(letter, 2), method))
                    ok2 = bool(p2) and not (set(p2) & set(pairs))
                    print(f"  [{method}] 2쪽 넘김 확인: {ok2}")
                    if not ok2:
                        continue
                self.method = method
                return True
        return False


class Problems:
    """조용히 데이터가 빠지는 일이 없도록 이상 징후를 모아 마지막에 보고"""

    def __init__(self):
        self.items = []

    def add(self, msg):
        self.items.append(msg)
        print(f"  ⚠️  {msg}", flush=True)


def crawl_listing(make_params, method, label, workers, log, problems):
    """1쪽으로 총 개수를 보고 나머지 쪽을 병렬로 받음. 받은 행 수가 총 개수와 다르면 그 쪽만 다시 받음."""
    h1 = fetch(make_params(1), method)
    total = base.extract_total_count(h1)
    p1 = base.parse_pairs_searchlist(h1)
    if not p1:
        if total:
            problems.add(f"{label}: 총 {total}개라는데 1쪽이 비어 있음")
        return []
    size = len(p1)
    pages = max(1, math.ceil(total / size)) if total else 1

    def get(p):
        return base.parse_pairs_searchlist(fetch(make_params(p), method))

    results = {1: p1}
    if pages > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(get, p): p for p in range(2, pages + 1)}
            done = 0
            for f in as_completed(futs):
                p = futs[f]
                try:
                    results[p] = f.result()
                except Exception as e:  # noqa: BLE001
                    results[p] = None
                    log(f"    {label} {p}쪽 실패: {e}")
                done += 1
                if done % 50 == 0:
                    log(f"    {label}: {done + 1}/{pages}쪽")

    # 비었거나 덜 찬 쪽(마지막 쪽 제외)은 순서대로 한 번 더
    for p in range(1, pages + 1):
        expect = size if p < pages else total - size * (pages - 1)
        if results.get(p) is None or len(results[p]) < expect:
            try:
                results[p] = get(p)
            except Exception as e:  # noqa: BLE001
                results[p] = results.get(p) or []
                problems.add(f"{label} {p}쪽 재시도도 실패: {e}")

    out = []
    for p in sorted(results):
        out.extend(results[p] or [])
    msg = f"  {label}: 총 {total}개 예상, {pages}쪽, 받은 행 {len(out)}"
    log(msg)
    if total is not None and len(out) < total:
        problems.add(f"{label}: {total - len(out)}개 덜 받음 (예상 {total}, 받음 {len(out)})")
    return out


def leftover_markup(rows):
    """전처리 후에도 태그 조각이 남은 행 (사이트가 강조 방식을 바꾸면 여기서 드러남)"""
    bad = []
    for t, k in rows:
        s = t + " " + k
        if "'>" in s or '">' in s or "<font" in s.lower() or "#ff0000" in s.lower():
            bad.append((t, k))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--workers", type=int, default=4, help="동시 요청 수 (기본 4, 너무 올리지 마세요)")
    ap.add_argument("--edition", default=None)
    ap.add_argument("--audit", type=int, default=60,
                    help="교차 확인용 무작위 3글자 포함 검색 개수 (기본 60, 0이면 생략)")
    ap.add_argument("--reference", default=None,
                    help="비교 기준 CSV (기본: data/sources/kma.csv, 없으면 GitHub 의 현재 데이터)")
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
    problems = Problems()
    seen, rows = set(), []

    def add(pairs):
        n = 0
        for k in pairs:
            if k not in seen:
                seen.add(k)
                rows.append(k)
                n += 1
        return n

    # 1) a~z 목록
    for letter in string.ascii_lowercase:
        pairs = crawl_listing(lambda p, L=letter: mode.spelling(L, p), mode.method,
                              f"'{letter}'", args.workers, log, problems)
        log(f"  → 새로 {add(pairs)}개, 누적 {len(seen):,}  ({time.time() - started:.0f}초)")

    # 2) a~z 로 시작하지 않는 용어: 숫자 + 그리스 문자 포함 검색
    extra = base.DIGITS + list("αβγδεζηθικλμνξοπρστυφχψω")
    for q in extra:
        pairs = crawl_listing(lambda p, q=q: mode.contains(q, p), "GET", f"포함 '{q}'",
                              args.workers, lambda m: None, problems)
        n = add(pairs)
        if pairs:
            log(f"  포함 '{q}': {len(pairs)}행 → 새로 {n}개")
    odd_start = [t for t, _ in rows if not (t[:1].isascii() and t[:1].isalpha())]
    log(f"  a~z 로 시작하지 않는 용어 {len(odd_start)}개: {odd_start[:10]}")

    # 3) 교차 확인: 받은 용어에서 무작위 3글자 조각을 뽑아 '포함 검색' → 목록 방식이 놓친 게 있는지
    if args.audit:
        import random
        rng = random.Random(len(rows))
        grams = set()
        terms_list = [t for t, _ in rows]
        while len(grams) < args.audit and terms_list:
            t = rng.choice(terms_list).lower()
            if len(t) >= 3:
                i = rng.randrange(0, len(t) - 2)
                g = t[i:i + 3]
                if g.isalpha() and g.isascii():
                    grams.add(g)
        log(f"\n교차 확인: 무작위 3글자 포함 검색 {len(grams)}개…")
        audit_missed = []
        for g in sorted(grams):
            pairs = crawl_listing(lambda p, q=g: mode.contains(q, p), "GET", f"검증 '{g}'",
                                  args.workers, lambda m: None, problems)
            for k in pairs:
                if k not in seen:
                    audit_missed.append((g, k))
            add(pairs)
        if audit_missed:
            problems.add(f"교차 확인에서 목록 방식이 놓친 행 {len(audit_missed)}개 발견 (추가함): "
                         f"{audit_missed[:10]}")
        else:
            log("  ✅ 교차 확인 결과 놓친 행 없음")

    # 4) 이전 데이터와 비교: 이전에 있었는데 안 잡힌 용어는 그 용어로 다시 검색
    ref_path = args.reference or base.OUT_CSV
    old_rows, _ = base.load_csv(ref_path)
    if not old_rows:
        try:
            url = "https://raw.githubusercontent.com/decaf-cpu/medical-terms/main/data/sources/kma.csv"
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            import csv as _csv
            import io
            rd = _csv.reader(io.StringIO(r.content.decode("utf-8-sig")))
            next(rd, None)
            old_rows = [(a, b) for a, b, *_ in rd]
            ref_path = url
        except Exception as e:  # noqa: BLE001
            problems.add(f"비교 기준 데이터를 못 구함 ({e}) — 이전 대비 확인 생략")
    if old_rows:
        missing = sorted({t for t, _ in old_rows} - {t for t, _ in rows})
        log(f"\n이전 데이터({os.path.basename(ref_path)})에 있었는데 안 잡힌 용어 {len(missing)}개 재검색…")
        rescued = []
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(lambda q: base.parse_pairs_searchlist(fetch(mode.contains(q, 1))), t): t
                    for t in missing}
            for f in as_completed(futs):
                try:
                    for k in f.result():
                        if k not in seen:
                            rescued.append(k)
                    add(f.result())
                except Exception as e:  # noqa: BLE001
                    problems.add(f"재검색 실패 '{futs[f]}': {e}")
        if rescued:
            problems.add(f"재검색으로 목록 방식이 놓친 행 {len(rescued)}개 발견 (추가함): {rescued[:10]}")
        still = sorted({t for t, _ in old_rows} - {t for t, _ in rows})
        log(f"  이번 판에서 없어진 것으로 보이는 용어 {len(still)}개: {still[:20]}")
    else:
        still = []

    bad = leftover_markup(rows)
    if bad:
        problems.add(f"전처리 후에도 태그 조각이 남은 행 {len(bad)}개: {bad[:5]}")

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
        "count": len(rows), "method": f"spelling a-z ({mode.method}) + digits/greek + audit + recheck",
        "not_found_from_previous": len(still),
        "problems": problems.items,
    }
    with open(base.META_JSON, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log(f"\n완료: {len(rows):,}개 → data/sources/kma.csv  ({(time.time() - started) / 60:.1f}분)")
    if problems.items:
        log(f"\n⚠️  확인이 필요한 항목 {len(problems.items)}개 (kma.meta.json 의 problems 에도 저장됨):")
        for m in problems.items:
            log(f"   - {m[:300]}")
    else:
        log("✅ 이상 징후 없음 (모든 목록 개수 일치, 교차 확인 통과, 태그 찌꺼기 없음)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
