# OGC2026 진척 요약 (PROGRESS)

> 팀 `amuse5516` · 예선 2026-06-15 ~ 07-28 · 최종 갱신 2026-06-30
> 상세 실험 기록: `docs/p3_solver_baseline.md`, `docs/p1_packing_benchmark.md`
> 제출 이력: `docs/submissions_log.md`

> ## 🔴 다음 액션 (NEXT)
> **`_ensure_feasible` 이중검증 교정본 재제출** → **P3 feasible 복구 목표**.
> - 제출 #5(2026-06-30): P1/P2/P4/P5/P6 개선(단일스레드 경로 정상 작동 확인),
>   P3만 여전히 −1. 진단: `_ensure_feasible`이 `solve_sequential` 결과를 검증하지 않고
>   반환하는 갭 + local checker 와 서버 checker 불일치 가능성.
> - **수정 완료(solver.py)**: `_ensure_feasible`이 sequential fallback도 `check_feasibility`로
>   이중 검증 후 반환. 빌드: `python tools/build_submission.py`.
> - 재제출 후 **P3 feasible 복구** 여부 확인 → `docs/submissions_log.md` #6 표에 기록.

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
| `tests/test_solver_regression.py` | P3 AABB 경계버그 회귀 + 안전망 + 단일스레드 feasible + **제출 엔트리포인트(`solver.solve` 호출)·격리 packaged feasibility** 고정 |

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
| (대기) | — | feasible 기대 | **`_ensure_feasible` sequential 이중검증 교정본 재제출** |

## 6. 현재 상태 / 다음
- ✅ 엔트리포인트 교정: `myalgorithm.py` → `solver.solve` (안전망 `_ensure_feasible` 경유) [#4 이후].
- ✅ `_ensure_feasible` 이중검증: sequential fallback도 `check_feasibility`로 검증 후 반환 [지금].
- ✅ 회귀 테스트 고정: `tests/test_solver_regression.py` 5/5
  (AABB 경계버그/안전망/단일스레드/엔트리포인트/packaged feasibility).
- ⚠️ **다음 액션: #6 재제출** → P3 feasible 복구 확인.
- ▶ P3 복구 후 약한 인스턴스 타겟 최적화 (블라인드 튜닝은 측정으로 소진됨).

### 로컬 검증 명령 (제출 전 권장)
```bash
python tests/test_placement.py            # 기하 feasibility 일치
python tests/test_solver_regression.py    # 회귀 5/5 (AABB/안전망/단일스레드/엔트리포인트/packaged)
python tools/build_submission.py          # dist/submission.zip 빌드 + 엔트리포인트·격리 feasibility 검증
```
