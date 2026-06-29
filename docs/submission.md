# 제출 가이드

## 빌드

```bash
python tools/build_submission.py          # dist/submission.zip 생성 + 검증
# 옵션: --instance data/train/prob_5.json --timelimit 30
```

스크립트가 하는 일:
1. `dist/submission.zip` 생성 — **루트 평면 구조**로 다음 4개 파일:
   - `myalgorithm.py` (진입점, **`solver.solve` 호출** — 자동 생성)
   - `solver.py`, `placement.py` (우리 코드)
   - `utils.py` (**공식 원본 그대로**, baseline/utils.py와 바이트 동일 검증)
2. 규칙 자동 점검: myalgorithm.py 루트 위치 · utils.py 미수정 · ≤15MB ·
   **진입점이 `solver.solve`를 호출**(안전망 우회하는 `solve_greedy` 금지)
3. 각 파일의 **SHA256 해시 출력**(빌드 식별은 바이트 수가 아닌 내용 해시로)
4. **격리 디렉토리에 풀어 실제 실행** → `utils.check_feasibility`로 feasible 확인
   (서버 실행 방식과 동일하게 자식 프로세스 + 해당 폴더만 path)

> ⚠️ **왜 `solve_greedy`가 아니라 `solve`인가**: `solver.solve()`만이 마지막에
> `_ensure_feasible()`(= `utils.check_feasibility` 재검사 후 infeasible이면 항상
> feasible한 순차해로 폴백)를 거친다. 진입점이 `solve_greedy`를 부르면 이 안전망을
> 건너뛰어 infeasible 해가 서버로 나갈 수 있다(P3 −1 사고의 원인).

빌드 산출물(`dist/`)은 git에서 제외됨 — 필요 시 위 명령으로 재생성.

## 제출

- 메일: `submission@optichallenge.com` (등록 메일 주소로 발송)
- 첨부: `dist/submission.zip` 단일 파일
- 쿨다운: 수락 후 **12시간** — 마감 직전 연쇄 제출 불가, 일정 역산

## 현재 제출 후보

`solver.solve` — 단일스레드 순차 멀티스타트 + local search + **`_ensure_feasible` 안전망**.
- **6/6 feasible 보장**: optimizing 경로가 혹시 infeasible을 내도 순차해로 폴백 → −1 원천차단
- 시간제한 준수(여유 margin 확보), 서버 멀티프로세싱 차단 시에도 단일스레드 경로가 주력
- 상세: `docs/p3_solver_baseline.md`

## 체크리스트 (제출 전)

- [ ] `python tools/build_submission.py` 통과(OK 출력 확인)
- [ ] **`dist/submission.zip` 안 `myalgorithm.py`가 `return solver.solve(prob_info, timelimit)`** 인지 확인
      (`solve_greedy` 아님 — 안전망 우회 금지). 빌드 스크립트가 자동 검증하지만 눈으로 한 번 더.
- [ ] **격리 feasibility smoke 통과**(스크립트의 isolated 실행이 `FEASIBLE` 출력)
- [ ] `python tests/test_solver_regression.py` 5/5 통과(엔트리포인트 + 격리 feasibility 포함)
- [ ] zip 구조·SHA256 해시 확인 (스크립트가 출력 — 바이트 수로 식별하지 말 것)
- [ ] 등록 메일 주소로 발송, 12시간 쿨다운 고려
