# 제출 가이드

## 빌드

```bash
python tools/build_submission.py          # dist/submission.zip 생성 + 검증
# 옵션: --instance data/train/prob_5.json --timelimit 30
```

스크립트가 하는 일:
1. `dist/submission.zip` 생성 — **루트 평면 구조**로 다음 4개 파일:
   - `myalgorithm.py` (진입점, `solver.solve_greedy` 호출 — 자동 생성)
   - `solver.py`, `placement.py` (우리 코드)
   - `utils.py` (**공식 원본 그대로**, baseline/utils.py와 바이트 동일 검증)
2. 규칙 자동 점검: myalgorithm.py 루트 위치 · utils.py 미수정 · ≤15MB
3. **격리 디렉토리에 풀어 실제 실행** → `utils.check_feasibility`로 feasible 확인
   (서버 실행 방식과 동일하게 자식 프로세스 + 해당 폴더만 path)

빌드 산출물(`dist/`)은 git에서 제외됨 — 필요 시 위 명령으로 재생성.

## 제출

- 메일: `submission@optichallenge.com` (등록 메일 주소로 발송)
- 첨부: `dist/submission.zip` 단일 파일
- 쿨다운: 수락 후 **12시간** — 마감 직전 연쇄 제출 불가, 일정 역산

## 현재 제출 후보

`solver.solve_greedy` — 공존 그리디.
- **40/40 feasible**, 시간제한 준수(~28s/30s), feasible-by-construction
- 총 목적값 5.35e9 (순차 floor 대비 4.8× 개선)
- 상세: `docs/p3_solver_baseline.md`

## 체크리스트 (제출 전)

- [ ] `python tools/build_submission.py` 통과(OK 출력 확인)
- [ ] 여러 인스턴스로 `--instance` 바꿔 추가 스모크 테스트
- [ ] zip 크기·구조 확인 (스크립트가 출력)
- [ ] 등록 메일 주소로 발송, 12시간 쿨다운 고려
