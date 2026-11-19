"""
대한의사협회 의학용어 검색(term.kma.org) 전체 크롤러

- 기존 v2 크롤러(kma_terms_6th_v2)의 쿼리 구성·전처리를 그대로 사용합니다.
  * 쿼리: 숫자 10 + 영문 2-gram 676 + 한글 대표 음절 14
  * dl.searchList 의 dt/dd 만 파싱
  * text_preserve_no_forced_spaces: 하이라이트 태그 경계에 공백을 강제로 넣지 않음,
    HTML 주석 제외, HTML 엔티티 디코딩, <br> → 개행
  * clean_text: 엔티티 2차 디코딩 + 연속 공백 1칸 + trim
  * (term, korean) 완전 일치 기준 중복 제거, 중단 후 이어받기(progress)

- 판(edition) 선택: 검색 화면의 sch_type1/sch_type2 선택지를 읽어
  "6.1" 이 들어간 항목을 우선, 없으면 번호가 가장 큰 항목을 자동으로 고릅니다.
  먼저 `python scripts/crawl_kma.py --probe` 로 선택지를 확인할 수 있습니다.
  자동 선택이 틀리면 --type1 / --type2 로 직접 지정하세요.

사용법 (레포 루트에서):
    pip install -r scripts/requirements.txt
    python scripts/crawl_kma.py --probe        # 판 선택지 확인만
    python scripts/crawl_kma.py                # 전체 크롤링 → data/sources/kma.csv
    python scripts/build_data.py               # → data/terms.json
"""
import argparse
import csv
import datetime
import html
import json
import math
import os
import re
import string
import sys
import time

import requests
from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString, Tag
from requests.exceptions import RequestException

BASE = "https://term.kma.org"
LIST_URL = BASE + "/search/list.asp"

DELAY = 0.10
TIMEOUT = 20
PAGE_LOG_EVERY = 20

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "data", "sources")
CACHE_DIR = os.path.join(ROOT, "scripts", ".cache")
OUT_CSV = os.path.join(SRC_DIR, "kma.csv")
META_JSON = os.path.join(SRC_DIR, "kma.meta.json")
PARTIAL_CSV = os.path.join(CACHE_DIR, "kma_partial.csv")
PROGRESS_JSON = os.path.join(CACHE_DIR, "progress.json")
DEBUG_HTML = os.path.join(CACHE_DIR, "debug.html")

# 이전(6판) 크롤링에서 쓰던 값 — 자동 감지 실패 시 fallback
LEGACY_TYPE1 = "twdContent7"
LEGACY_TYPE2 = "twdDong7"

# ✅ 기존과 동일: 숫자 + 영문 2글자 + 한글 대표 음절
EN_2GRAM = [a + b for a in string.ascii_lowercase for b in string.ascii_lowercase]
DIGITS = list("0123456789")
HANGUL = ["가", "나", "다", "라", "마", "바", "사", "아", "자", "차", "카", "타", "파", "하"]
QUERIES = DIGITS + EN_2GRAM + HANGUL

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Referer": LIST_URL,
})


# ---------------------------------------------------------------- 전처리 (v2 그대로)

def clean_text(x: str) -> str:
    # HTML 엔티티 디코딩 (혹시 모를 2차 처리)
    x = html.unescape(x)
    # 연속 whitespace를 1칸으로 + trim
    return re.sub(r"\s+", " ", x).strip()


def fix_highlight_artifacts(x: str) -> str:
    """
    의협 사이트는 검색어를 <font color='#FF0000'>…</font> 로 강조하는데, 검색어가 'f' 나 '0' 이면
    자기 태그의 색상값(#FF0000) 안 글자까지 다시 치환해 태그가 깨짐 → 본문에 찌꺼기가 남음.
      'f' 검색:  "FF0000'>fever"      → "fever"
      '0' 검색:  "10000'>00000'>0 °F" → "100 °F",  "ED50000'>0" → "ED50"
    (1월 데이터의 clean2→clean3 정리에서 제거됐던 오류 행들과 같은 원인)
    """
    return x.replace("FF0000'>", "").replace("0000'>0", "0")


def text_preserve_no_forced_spaces(node) -> str:
    """
    BeautifulSoup.get_text(" ")는 노드 경계마다 공백을 강제 삽입함 → 하이라이트(font/b) 때문에
    글자 중간 공백이 생김. 여기서는 텍스트 노드만 순서대로 '그대로' 이어붙임.
    HTML 엔티티 디코딩, 주석 제외, <br> → 개행.
    """
    parts = []

    def walk(n):
        if isinstance(n, Comment):
            return
        if isinstance(n, NavigableString):
            parts.append(html.unescape(str(n)))
            return
        if isinstance(n, Tag):
            if n.name == "br":
                parts.append("\n")
                return
            for c in n.children:
                walk(c)

    walk(node)
    return "".join(parts)


def parse_pairs_searchlist(page_html: str):
    """<dl class="searchList"> 내부 dt/dd 만 파싱"""
    soup = BeautifulSoup(page_html, "html.parser")
    dl = soup.select_one("dl.searchList")
    if not dl:
        return []
    pairs = []
    for dt in dl.select("dt"):
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        term = fix_highlight_artifacts(clean_text(text_preserve_no_forced_spaces(dt)))
        kor = fix_highlight_artifacts(clean_text(text_preserve_no_forced_spaces(dd)))
        if term and kor:
            pairs.append((term, kor))
    return pairs


def extract_total_count(page_html: str):
    m = re.search(r"총\s*([0-9,]+)\s*개", page_html)
    return int(m.group(1).replace(",", "")) if m else None


# ---------------------------------------------------------------- HTTP

def request_get_with_retry(params=None, max_tries: int = 6) -> str:
    backoff = 0.5
    last_err = None
    for _ in range(max_tries):
        try:
            r = session.get(LIST_URL, params=params, timeout=TIMEOUT)
            if not r.encoding or r.encoding.lower() == "iso-8859-1":
                r.encoding = r.apparent_encoding
            if r.status_code == 429 or 500 <= r.status_code < 600:
                last_err = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(backoff)
                backoff = min(backoff * 2, 10)
                continue
            r.raise_for_status()
            return r.text
        except RequestException as e:
            last_err = e
            time.sleep(backoff)
            backoff = min(backoff * 2, 10)
    raise RuntimeError(f"GET failed after retries: {last_err}")


# ---------------------------------------------------------------- 판(edition) 감지

def _label_for(el, soup):
    if el.name == "option":
        return clean_text(el.get_text())
    el_id = el.get("id")
    if el_id:
        lab = soup.find("label", attrs={"for": el_id})
        if lab:
            return clean_text(lab.get_text())
    if el.parent is not None and el.parent.name == "label":
        return clean_text(el.parent.get_text())
    sib = el.next_sibling
    while sib is not None and isinstance(sib, NavigableString) and not str(sib).strip():
        sib = sib.next_sibling
    if isinstance(sib, NavigableString):
        return clean_text(str(sib))
    if isinstance(sib, Tag) and sib.name in ("label", "span"):
        return clean_text(sib.get_text())
    return ""


def find_choices(page_html: str):
    """sch_type1 / sch_type2 의 (value, label) 선택지 수집"""
    soup = BeautifulSoup(page_html, "html.parser")
    out = {"sch_type1": [], "sch_type2": []}
    for name in out:
        for sel in soup.find_all("select", attrs={"name": name}):
            for opt in sel.find_all("option"):
                if opt.get("value"):
                    out[name].append((opt["value"], _label_for(opt, soup)))
        for inp in soup.find_all("input", attrs={"name": name}):
            if inp.get("value"):
                out[name].append((inp["value"], _label_for(inp, soup)))
    # 실제 사이트: 왼쪽 메뉴 <a href="javascript:$.sch_type(7);">6.1판</a>
    #             → JS 에서 "twdContent7/twdDong7" 로 매핑
    for a in soup.find_all("a", href=re.compile(r"sch_type\(\s*\d+\s*\)")):
        n = re.search(r"sch_type\(\s*(\d+)", a["href"]).group(1)
        lab = clean_text(a.get_text())
        out["sch_type1"].append((f"twdContent{n}", lab))
        out["sch_type2"].append((f"twdDong{n}", lab))
    # 판 이름 후보 (페이지 텍스트에서)
    editions = sorted({re.sub(r"\s+", "", e) for e in
                       re.findall(r"제?\s*\d+(?:\.\d+)?\s*판", soup.get_text(" "))})
    return out, editions


def _num_suffix(v):
    m = re.search(r"(\d+)$", v)
    return int(m.group(1)) if m else -1


def pick(choices, prefix):
    cands = [(v, lab) for v, lab in choices if v.startswith(prefix)] or list(choices)
    if not cands:
        return None
    for v, lab in cands:
        if "6.1" in lab:
            return v
    return max(cands, key=lambda c: _num_suffix(c[0]))[0]


def detect_types(verbose=True):
    page = request_get_with_retry()
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(os.path.join(CACHE_DIR, "landing.html"), "w", encoding="utf-8") as f:
        f.write(page)
    choices, editions = find_choices(page)
    if verbose:
        print("페이지에 보이는 판 표기:", ", ".join(editions) or "(없음)")
        for name, lst in choices.items():
            print(f"{name} 선택지:")
            for v, lab in lst:
                print(f"   {v:<20} {lab}")
            if not lst:
                print("   (못 찾음)")
    t1 = pick(choices["sch_type1"], "twdContent") or LEGACY_TYPE1
    t2 = pick(choices["sch_type2"], "twdDong") or LEGACY_TYPE2
    label = ""
    for v, lab in choices["sch_type1"]:
        if v == t1:
            label = lab
    return t1, t2, label, editions


# ---------------------------------------------------------------- 크롤링

def crawl_query(q: str, t1: str, t2: str):
    params1 = {"pageno": 1, "sch_txt": q, "sch_type1": t1, "sch_type2": t2}
    html1 = request_get_with_retry(params1)
    with open(DEBUG_HTML, "w", encoding="utf-8") as f:
        f.write(html1)

    total = extract_total_count(html1)
    pairs1 = parse_pairs_searchlist(html1)
    page_size = len(pairs1)
    if total is not None:
        print(f"  expected_total≈{total}", flush=True)
    if page_size == 0:
        return []

    max_pages = math.ceil(total / page_size) if (total is not None and page_size > 0) else 1
    max_pages = max(1, max_pages)

    all_pairs = list(pairs1)
    for page in range(2, max_pages + 1):
        params = {"pageno": page, "sch_txt": q, "sch_type1": t1, "sch_type2": t2}
        page_html = request_get_with_retry(params)
        with open(DEBUG_HTML, "w", encoding="utf-8") as f:
            f.write(page_html)
        pairs = parse_pairs_searchlist(page_html)
        if not pairs:
            break
        all_pairs.extend(pairs)
        if page % PAGE_LOG_EVERY == 0:
            print(f"  page {page}/{max_pages} (+{len(pairs)}) so_far={len(all_pairs)}", flush=True)
        time.sleep(DELAY)
    return all_pairs


def load_csv(path):
    rows, seen = [], set()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            r = csv.reader(f)
            next(r, None)
            for row in r:
                if len(row) >= 2 and (row[0], row[1]) not in seen:
                    seen.add((row[0], row[1]))
                    rows.append((row[0], row[1]))
    return rows, seen


def append_rows(path, rows):
    exists = os.path.exists(path)
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["term", "korean"])
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description="term.kma.org 전체 크롤링")
    ap.add_argument("--probe", action="store_true", help="판 선택지만 출력하고 종료")
    ap.add_argument("--type1", help="sch_type1 값 직접 지정 (예: twdContent8)")
    ap.add_argument("--type2", help="sch_type2 값 직접 지정 (예: twdDong8)")
    ap.add_argument("--edition", help="페이지에 표시할 판 이름 (기본: 자동, 예: 6.1판)")
    ap.add_argument("--restart", action="store_true", help="이어받기 기록을 지우고 처음부터")
    args = ap.parse_args()

    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(SRC_DIR, exist_ok=True)

    t1, t2, label, editions = detect_types(verbose=True)
    t1 = args.type1 or t1
    t2 = args.type2 or t2
    print(f"\n사용할 값: sch_type1={t1}  sch_type2={t2}  ({label or '라벨 없음'})")
    if args.probe:
        print("\n--probe 모드라 여기서 종료합니다. 값이 맞으면 옵션 없이 다시 실행하세요.")
        return

    if args.restart:
        for p in (PARTIAL_CSV, PROGRESS_JSON):
            if os.path.exists(p):
                os.remove(p)

    prog = {}
    if os.path.exists(PROGRESS_JSON):
        with open(PROGRESS_JSON, encoding="utf-8") as f:
            prog = json.load(f)
        if prog.get("type1") != t1 or prog.get("type2") != t2:
            print("⚠️  이전 진행 기록의 판 설정이 달라 처음부터 다시 시작합니다.")
            prog = {}
            if os.path.exists(PARTIAL_CSV):
                os.remove(PARTIAL_CSV)
    start_idx = int(prog.get("next_index", 0))

    _, seen = load_csv(PARTIAL_CSV)
    print(f"loaded existing unique: {len(seen)}  resume from query {start_idx}/{len(QUERIES)}\n", flush=True)

    errors = []
    for i in range(start_idx, len(QUERIES)):
        q = QUERIES[i]
        print(f"START q='{q}' ({i + 1}/{len(QUERIES)})", flush=True)
        try:
            pairs = crawl_query(q, t1, t2)
        except Exception as e:  # noqa: BLE001
            print(f"ERROR q='{q}': {e}", flush=True)
            errors.append(q)
            time.sleep(1.0)
            continue
        new_rows = []
        for key in pairs:
            if key not in seen:
                seen.add(key)
                new_rows.append(key)
        if new_rows:
            append_rows(PARTIAL_CSV, new_rows)
        with open(PROGRESS_JSON, "w", encoding="utf-8") as f:
            json.dump({"type1": t1, "type2": t2, "next_index": i + 1}, f)
        print(f"DONE  q='{q}' added={len(new_rows)} total_unique={len(seen)}", flush=True)
        time.sleep(DELAY)

    if errors:
        print(f"\n⚠️  실패한 쿼리 {len(errors)}개: {errors}")
        print("   --restart 없이 다시 실행해도 이 쿼리들은 건너뛰어진 상태이니, "
              "필요하면 --restart 로 전체를 다시 돌리세요.")

    rows, _ = load_csv(PARTIAL_CSV)
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["term", "korean"])
        w.writerows(rows)

    edition = args.edition
    if not edition:
        m = re.search(r"\d+(?:\.\d+)?\s*판", label or "")
        edition = m.group(0).replace(" ", "") if m else "6.1판"
    meta = {
        "edition": edition,
        "crawled": datetime.date.today().isoformat(),
        "sch_type1": t1,
        "sch_type2": t2,
        "type1_label": label,
        "count": len(rows),
        "failed_queries": errors,
    }
    with open(META_JSON, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"\n완료: {len(rows):,}개 → {os.path.relpath(OUT_CSV, ROOT)}")
    print("다음: python scripts/build_data.py")


if __name__ == "__main__":
    sys.exit(main())
