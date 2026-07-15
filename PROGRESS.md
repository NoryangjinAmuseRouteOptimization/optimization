# OGC2026 진척 요약 (PROGRESS)

> 팀 `amuse5516` · 예선 2026-06-15 ~ 07-28 · 최종 갱신 2026-06-24
> 상세 실험 기록: `docs/p3_solver_baseline.md`, `docs/p1_packing_benchmark.md`
> 제출 이력: `docs/submissions_log.md`

> ## 🔴 다음 액션 (NEXT)
> **full-solver entrypoint 수정본 재제출** → **P1~P6 서버 점수 확보**.
> - 옛 버그본 `solver.py`(37,169 bytes) 재사용 금지. 현재는 파일 크기 대신 git
>   commit/hash와 격리 ZIP 테스트 결과를 기록.
>   빌드: `python tools/build_submission.py`
> - 재제출 후 P3 feasible 복구 + 5개 objective 개선 여부 확인 → `docs/submissions_log.md`
>   #4 표에 기록.
> - 그 데이터 확보 전까지 새 알고리즘 추가 금지(블라인드 튜닝은 측정으로 소진됨).

## 1. 한 줄 요약
"제출 불가 baseline"에서 시작해 **항상 feasible·시간안전·다단계 최적화 솔버**를 구축.
2026-07-15에 제출 빌더가 이 솔버를 호출하지 않고 `solve_greedy`를 직접 호출하던 핵심
entrypoint 버그를 수정했다. 이제 단일스레드 멀티스타트·local search·P3 안전망이 실제
ZIP에서 실행되며, 10초 대표 3문제에서 legacy greedy 대비 **−27.8%**를 확인했다.

## 2. 구축한 파이프라인 (전부 main)
| 파일 | 역할 |
|---|---|
| `placement.py` | 공간/기하 코어 (후보생성·`can_place`, 평가서버와 일치 검증) |
| `solver.py` | 솔버: 순차floor → 공존greedy → 멀티스타트 → local search → 안전망 |
| `tools/bench_solver.py` | 40개 인스턴스 실제 목적값 측정 하니스 |
| `tools/bench_packing.py` | 후보 생성기 패킹밀도 벤치마크 |
| `tools/build_submission.py` | 제출 zip 빌드 + **격리 feasibility 검증** |
| `tests/test_placement.py` | `can_place`가 평가서버와 일치하는지 검증 |
| `tests/test_solver_regression.py` | P3 AABB 경계버그 회귀 + 안전망 + 단일스레드 feasible 고정 |

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
| **+ 단일스레드 순차 멀티스타트** | **1.55e9 (서버 시뮬레이션)** | 멀티프로세싱 없이 다양성 회복 |

## 4. 결정적 발견 (Lessons)
- **기존 멀티프로세싱 차단 진단은 미확정**: 제출 빌더가 2026-06-17부터 계속
  `solve_greedy`를 호출해 `solve()` 자체가 실행되지 않았다. 동일 서버 목적값은 이
  entrypoint 버그만으로 설명된다. 단일스레드 경로는 계속 주력으로 유지하되, 병렬 가능
  여부는 수정 ZIP의 실제 서버 결과로 다시 판단한다.
- **P3 −1 원인 = AABB fast-path가 베이 경계검사 누락** → 수정 + **check_feasibility
  안전망**(혹시 infeasible이면 순차해 폴백, −1 원천차단).
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
| (대기) | — | feasible 예상 | **full-solver entrypoint 수정 ZIP 재제출 필요** |

## 6. 현재 상태 / 다음
- ✅ 제출 entrypoint 수정: ZIP의 `myalgorithm.py`가 `solver.algorithm` 호출.
- ✅ 회귀 테스트 5/5: AABB 경계·안전망·패키지 entrypoint·Z2 local search·단일스레드.
- ✅ 최신 격리 ZIP prob_23(10초) feasible, objective 13,097,178.
- ⚠️ **다음 액션: 수정 ZIP 재제출** → 실제 P1~P6 숫자와 multiprocessing 여부 확보.
- ▶ 그 데이터로 약한 인스턴스 타겟 최적화 (블라인드 튜닝은 측정으로 소진됨).

### 로컬 검증 명령 (제출 전 권장)
```bash
python tests/test_placement.py            # 기하 feasibility 일치
python tests/test_solver_regression.py    # 회귀(AABB/안전망/entrypoint/Z2/단일스레드) 5/5
python tools/build_submission.py          # dist/submission.zip 빌드 + 격리 feasibility
```
