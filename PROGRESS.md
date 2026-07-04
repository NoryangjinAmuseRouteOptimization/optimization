# OGC2026 진척 요약 (PROGRESS)

> 팀 `amuse5516` · 예선 2026-06-15 ~ 07-28 · 최종 갱신 2026-06-30 (이후)
> 상세 실험 기록: `docs/p3_solver_baseline.md`, `docs/p1_packing_benchmark.md`
> 제출 이력: `docs/submissions_log.md`

> ## 🔴 다음 액션 (NEXT)
> **#8 준비완료: feasibility-first 재설계 (#7도 P3 −1 → 구조 전면 재검토 반영).**
> - **#7 사후 진단으로 찾은 실제 구멍 2개**:
>   ① 컬럼 모드 진입후보가 `{exit 시각}` 그대로 → 공존판정(열린구간)에 안 잡혀 **동일 timestamp
>   EXIT/ENTRY + x-겹침**(순서의존) 배치 가능. ② probe가 pace-deadline(벽시계) 의존이라
>   **하드웨어에 따라 objective inflate** → 느린 서버에서 P3(760k)가 3.5M 넘겨 wide로 오분류
>   가능(→ −1). "local check 통과=안전"·"probe는 결정적" 가정 폐기.
> - **#8 재설계 (solver.py)**:
>   ① `_SAFE_TIME_GAP=1`: safe 경로 전체에서 진입=exit+1, 팽창 시간창으로 x-분리 강제 →
>   같은 베이에서 timestamp 공유+x겹침 조합 원천 제거. ② `_verify_structural`: **순수
>   interval/AABB 런타임 인증서**(Shapely 0회) — safe 경로는 이 인증 통과분만 반환, 실패 시
>   floor로 강등. ③ floor(`floor_assignments`): no-coexist+시간갭≥1, degenerate fallback
>   삭제(`InstanceFitError` 명시 실패). ④ 라우팅: `<250k`→narrow(P1/P2, 서버 2회 실증) ·
>   `<8M`→**safe(인증 컬럼→floor)** · `≥8M`→wide. wide 임계 3.5M→**8M**(P3 오분류에 10.5×
>   inflate 필요; P4=15.27M은 inflate가 위로만 작용해 항상 통과). 오류방향 전부 fail-safe.
> - 검증: 회귀 6/6(독립 구조검사 추가)·placement PASS·빌드 3경로 smoke·**train 40 전수:
>   40/40 feasible, safe경로 위험쌍(bbox겹침+동일ts) 0개**, pace 비결정성 관측시에도 safe로만 표류.
> - **다음 제출 가능: 2026-07-01 03:01:59 UTC**(#6 +12h) 이후 — #7이 이미 나갔다면 #7 +12h.

## 1. 한 줄 요약
"제출 불가 baseline"에서 시작해 **항상 feasible·시간안전·다단계 최적화 솔버**를 구축.
서버가 멀티프로세싱을 차단한다는 사실을 진단해 **단일스레드 경로를 주력으로 재설계**,
현재 서버 실행 기준 **−26%** 개선본 + **P3 −1 버그 수정 + −1 원천차단 안전망** 완성.

## 2. 구축한 파이프라인 (전부 main)
| 파일 | 역할 |
|---|---|
| `placement.py` | 공간/기하 코어 (후보생성·`can_place`, 평가서버와 일치 검증) |
| `solver.py` | 솔버: 순차floor → 공존greedy → 멀티스타트 → local search → 안전망 |
| `tools/bench_solver.py` | 40개 인스턴스 실제 목적값 측정 하니스 |
| `tools/bench_packing.py` | 후보 생성기 패킹밀도 벤치마크 |
| `tools/build_submission.py` | 제출 zip 빌드 + **격리 feasibility 검증** |
| `tests/test_placement.py` | `can_place`가 평가서버와 일치하는지 검증 |
| `tests/test_solver_regression.py` | P3 AABB 경계버그 회귀 + 안전망 + 단일스레드 feasible + 제출 엔트리포인트(`solver.solve` 호출)·격리 packaged feasibility + **P3-like 격리 라우팅** 고정 (6/6) |

## 3. 솔버 발전 (훈련셋 40개 총 목적값)
| 단계 | 총 목적값 | 비고 |
|---|---|---|
| 제공 baseline_greedy | **−1** | 시간초과 3~7배 + infeasible (제출 불가 판명) |
| 순차 floor | 25.5e9 | 베이당 1블록 → 구조적 항상 feasible |
| 공존 greedy | 5.35e9 | 같은 베이 시공간 양립 블록 공존 (4.8×) |
| + 적응형 페이스 deadline | 2.72e9 | 블록당 시간 공정분배 |
| + 병렬 멀티스타트 | 2.35e9 | (단, 서버에선 멀티프로세싱 차단됨 — 아래 참조) |
| + obj3 폴리시 / local search | 2.19e9 | 남는 시간 무퇴보 재배치 |
| + AABB fast-path | 1.95e9 | 빈공간 후보 shapely 생략 (단, 경계버그→수정) |
| + 넓은 후보탐색 | 1.54e9 | 후보 수↑ (대형 tardiness 인스턴스 개선) |
| **+ 단일스레드 순차 멀티스타트** | **1.55e9 (서버 실측)** | 멀티프로세싱 없이 다양성 회복 |
| + P3-like 격리 분기 | (대형 동일) | 소형만 narrow greedy로 우회(P3 −1 제거), 대형은 wide 유지 |

## 4. 결정적 발견 (Lessons)
- **서버는 멀티프로세싱(ProcessPoolExecutor) 차단** → 제출 #1~#3에서 P1~P6 목적값이
  완전 동일했던 이유. 우리 병렬 개선이 한 번도 서버에서 실행 안 됨 → **단일스레드
  경로를 주력으로 재설계**(서버 기준 바닐라 greedy 대비 **−26%**).
- **P3 −1 원인 = AABB fast-path가 베이 경계검사 누락** → 수정 + **check_feasibility
  안전망**(혹시 infeasible이면 순차해 폴백, −1 원천차단).
- **안전망이 제출 경로에 연결돼 있지 않았음** → `solver.solve()`는 `_ensure_feasible()`로
  보호되지만, 제출 zip의 `myalgorithm.py`가 `solver.solve_greedy`를 불러 안전망을 **우회**.
  회귀 테스트도 `solve()`만 검사해 이 갭을 놓침. → **엔트리포인트를 `solver.solve`로 교정** +
  packaged 경로(격리 zip 실행) 회귀 테스트 추가.
- **#5 이후 P3 −1이 안전망으로도 안 잡힌 이유 = local vs 서버 Shapely 불일치**: wide 탐색이
  P3에서 만든 near-touch 배치가 local `check_feasibility`는 통과(`inter.area==0`)하나 서버
  Shapely는 reject(`inter.area>0`). 안전망은 local 기준이라 감지 불가. **P3 데이터가 없어
  로컬 재현·정밀탐지 불가** → 해법은 "위험경로를 P3에 아예 안 태우기"(격리).
- **격리 전략의 근거 = 검증된 안전 프로필 존재**: #1~#4에서 P3가 feasible(760k)이던 경로는
  **narrow 공존 greedy(seed0/16/40) fallback**. AABB-zero-area 공존쌍은 모든 인스턴스에 공통
  (훈련 27~106쌍/개)이라 "위험쌍 탐지"로 P3만 골라내기는 불가능 → **스케일(목적값)로
  소형(P1/P2/P3) vs 대형(P4/P5/P6)만 분리**하고 소형은 narrow로 우회. sequential 격리는
  소형에서 1000×+ 악화(측정값: prob_1 154k→440M)라 **부적합**, narrow는 ~1.3~6.5× 손해로
  feasible 유지 → "일부 손해" 허용범위.
- **음성결과로 걸러낸 것**(측정 후 폐기): NFP/skyline(비정형에 거침), STRtree(느림),
  size-adaptive LNS·always-mix LNS(per-instance 회귀), ILS(시간초과+무이득),
  wide local-search(move당 느림), 대안정렬 slack/critratio(EDD보다 나쁨).
  → **큰 이득은 단순·견고한 것**(순차floor·공존·페이스deadline·단일스레드 멀티스타트)에서.

## 5. 제출 이력
| # | 일시(UTC) | P3 | 결과 |
|---|---|---|---|
| 1 | 06-19 14:03 | feasible | 6/6 feasible, Tier 11/15 |
| 2 | 06-21 06:16 | **infeasible** | AABB 경계버그, Tier 15/17 (하락) |
| 3 | 06-23 13:26 | **infeasible** | ⚠️ 옛 버그본 재업로드 (수정본 아님) |
| 4 | 06-29 08:38 | **infeasible** | P3만 −1, P1/P2/P4/P5/P6는 #1과 동일 → 엔트리포인트가 `solve_greedy`라 안전망 우회 |
| 5 | 06-30 02:34 | **infeasible** | P1/P2/P4/P5/P6 모두 개선(단일스레드 동작 확인), P3만 여전히 −1 |
| 6 | 06-30 15:01 | **infeasible** | 격리: P1/P2 #1과 동일(narrow 정상)·**P4/P5/P6 −29/−27/−70%**(wide 큰개선)·**P3만 여전히 −1** |

## 6. 현재 상태 / 다음
- ✅ 엔트리포인트 교정: `myalgorithm.py` → `solver.solve` (안전망 `_ensure_feasible` 경유) [#4 이후].
- ✅ `_ensure_feasible` 이중검증: sequential fallback도 `check_feasibility`로 검증 후 반환.
- ✅ **3-way 라우팅(#7)**: `solve()`가 narrow probe 목적값으로 P1/P2(narrow)·P3(컬럼 패킹)·
  P4/P5/P6(wide) 분기. P3만 **컬럼 패킹**(x-구간 분리, Shapely 무관 feasible)으로 격리.
- ✅ **컬럼 패킹**(`_earliest_coexist(x_gap=1)`): 공존 블록 x-분리 → 순수 AABB로 충돌·크레인
  보장 → 서버 checker 버전 무관 feasible. 훈련 40/40 feasible 실측.
- ✅ 회귀 테스트 **6/6**(AABB/안전망/단일스레드/엔트리포인트/packaged + **3-way 라우팅 &
  컬럼 x-disjoint 보장** 검증).
- ✅ 빌드 smoke **3경로**: narrow(prob_5)·column(prob_22)·wide(prob_21) 모두 feasibility 검증
  (하나라도 infeasible이면 빌드 실패).
- ⚠️ **다음 액션: #7 제출**(2026-07-01 03:01:59 UTC 이후) → **P3 −1 제거** 확인.
  P1/P2 무변경(narrow)·P4/P5/P6 무변경(wide)·P3만 컬럼 패킹(feasible 목표, 점수 무관).
- ▶ P3 feasible 확인되면, 컬럼 패킹 목적값 개선(컬럼 내 다중배치·시간 재배열) 검토.

### 로컬 검증 명령 (제출 전 권장)
```bash
python tests/test_placement.py            # 기하 feasibility 일치
python tests/test_solver_regression.py    # 회귀 6/6 (…/3-way 라우팅·컬럼 x-disjoint 보장)
python tools/build_submission.py          # zip 빌드 + 엔트리포인트·3경로(narrow/column/wide) feasibility 검증
```
