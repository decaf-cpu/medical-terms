# 🏥 의학용어 검색

대한의사협회 의학용어 6.1판 및 대한예방의학회 의학용어집 기반 의학용어 실시간 검색 도구입니다.

## 🔗 바로 사용하기

👉 **[의학용어 검색 시작하기](https://decaf-cpu.github.io/medical-terms/)**

## 📊 데이터 정보

- 용어 수·판·업데이트 날짜는 페이지 상단에 표시됩니다 (`data/terms.json`의 `meta`)
- 영문 용어 ↔ 한글 뜻풀이 양방향 검색
- 대한의사협회 의학용어집 + 대한예방의학회 의학용어집([예방] 태그)

## ✨ 주요 기능

### 🔍 실시간 검색
- 타이핑할 때마다 즉시 결과 표시
- 300ms 디바운싱으로 부드러운 검색 경험

### 🔄 양방향 검색
- **영문 → 한글**: "fever" 입력 → "열" 검색
- **한글 → 영문**: "복부" 입력 → "abdominal" 관련 용어 검색

### 💡 스마트 검색
- 대소문자 구분 없음 (FEVER = fever = Fever)
- 부분 일치 검색 (abd → abdominal, abdomen 등)
- 검색어 하이라이트 표시

### 📱 반응형 디자인
- 모바일, 태블릿, 데스크톱 모두 지원
- 직관적인 UI/UX

## 🚀 사용 방법

GitHub Pages 링크로 바로 접속하여 사용합니다. 예전 주소(`medical_terms_search_standalone.html`)로 들어오면 새 페이지로 자동 이동합니다.

## 🔄 데이터 업데이트 (의협 사이트 재크롤링)

의협 사이트는 해외 IP에서 접속이 안 되므로 **국내 PC에서** 실행합니다.

```bash
pip install -r scripts/requirements.txt
python scripts/crawl_kma.py --probe   # 판 선택지 확인 (6.1판이 자동 선택되는지)
python scripts/crawl_kma.py           # 전체 크롤링 → data/sources/kma.csv (중단 시 다시 실행하면 이어받기)
python scripts/build_data.py          # → data/terms.json, reports/changes_날짜.csv
```

더 빠른 방법: `python scripts/crawl_kma_fast.py` (a~z 첫 글자 목록으로 용어당 한 번만 받고, 6판 대비 빠진 용어는 재검색). 먼저 `--probe`로 사이트에서 되는지 확인합니다.

자동 선택이 틀리면 `--type1 twdContent8 --type2 twdDong8`처럼 직접 지정합니다.

## 📁 구조

```
index.html                 페이지
assets/style.css, app.js   디자인·검색 로직
data/terms.json            검색 데이터 (빌드 결과)
data/sources/kma.csv       의협 크롤링 원본 (+ kma.meta.json)
data/sources/prevmed.csv   예방의학회 용어집
scripts/crawl_kma.py       크롤러 (v2 전처리 유지)
scripts/build_data.py      소스 병합·중복 제거·변경 목록
```

## 💻 기술 스택

- **순수 HTML/CSS/JavaScript** (프레임워크 없음)
- 데이터는 별도 JSON으로 분리 → 인라인 스크립트가 없어 CSP 해시 관리 불필요


## 📈 성능

- 데이터 약 2.4 MB (전송 시 gzip 약 0.8 MB)
- 검색 속도: 실시간 (< 100ms)
- 최대 표시 결과: 200개

## 🎯 데이터 출처

대한의사협회 의학용어위원회에서 발행한 의학용어집(현재 6.1판)을 기반으로 크롤링하여 구축했습니다.

- 출처: [대한의사협회 의학용어검색](https://term.kma.org), [대한예방의학회 의학용어집](https://prevmed.or.kr/prevmed/dictionary.html)
- 크롤링 일자: `data/sources/kma.meta.json` 참고

## ⚖️ 라이선스 및 주의사항

이 프로젝트는 **교육 및 연구 목적**으로 제작되었습니다.

- 의학용어 데이터의 저작권은 대한의사협회에 있습니다
- 상업적 사용 전 반드시 대한의사협회의 허가를 받으시기 바랍니다
- 의학적 결정은 반드시 전문가와 상담하시기 바랍니다

## 🤝 기여

버그 리포트나 개선 제안은 Issues 탭에서 환영합니다!

## 📧 문의

프로젝트 관련 문의사항이 있으시면 Issues를 통해 연락해주세요.

---

**Made with ❤️ for medical students and professionals**
