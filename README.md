# OGC2026 — The Grand Shipyard Puzzle

[Optimization Grand Challenge 2026](https://optichallenge.com) 참가용 리포지토리.
조선소 **공간적 블록 스케줄링** 문제를 다룬다: 각 블록을 어느 베이에, 어떤 위치·방향으로,
언제 넣고 뺄지를 동시에 결정해 공간·시간 제약을 만족시키며 목적함수를 최소화한다.

## 문제 요약

- **베이(Bay)**: 고정 크기 `W×H`의 작업장. 각 베이는 독립 크레인을 가진다.
- **블록(Block)**: 다각형 레이어로 구성된 3D 구조물. 회전(orientation) 가능.
  release/due/processing time, workload, 베이 선호도(preference)를 가진다.
- **결정 변수**: ① 베이 배정 ② 위치(x,y) ③ 방향(orient_idx) ④ ENTRY/EXIT 시각
- **제약**: 베이 경계 포함 · 동일 높이 레이어 충돌 금지 · 크레인 수직 이동 가능 ·
  `ENTRY ≥ release`, `EXIT − ENTRY ≥ processing`
- **목적함수**: `w1·Z1 + w2·Z2 + w3·Z3` 최소화
  - `Z1` 총 지각(tardiness), `Z2` 베이 간 작업부하 불균형, `Z3` 선호도 페널티

자세한 내용은 [`docs/problem_statement_v1.1.pdf`](docs/problem_statement_v1.1.pdf) 참조.

## 디렉토리 구조

```
.
├── baseline/             # 제출 코드 (myalgorithm.py 가 진입점)
│   ├── myalgorithm.py        # algorithm(prob_info, timelimit) — 제출 진입점
│   ├── baseline_greedy.py    # EDD + Best-Fit 그리디 + 사후 보수 알고리즘
│   ├── utils.py              # 실현가능성 검사/채점 (★ 수정 금지)
│   └── README.txt
├── alg_tester/           # PyQt6 GUI 테스터 + 시각화 (간트/베이 배치도)
├── data/train/           # 훈련 인스턴스 40개 (prob_1 ~ prob_40)
├── docs/                 # 문제 설명 PDF, 패키지 README
├── ogc2026_env.yml       # conda 환경 정의 (평가서버와 호환)
├── MILESTONES.md         # 일정/마일스톤
└── README.md
```

## 빠른 시작

```bash
# 1) 환경 구성 (Miniforge 권장)
conda env create -f ogc2026_env.yml
conda activate ogc2026

# 2) baseline 단독 실행 (한 인스턴스)
cd baseline
python baseline_greedy.py ../data/train/prob_1.json --timelimit 60

# 3) GUI 테스터로 시각화
cd ../alg_tester
python alg_tester_app.py
```

## 제출 규칙 (요약)

- 제출물은 `myalgorithm.py`를 **루트**에 둔 단일 zip (≤ 15MB)
- `algorithm(prob_info, timelimit)` 시그니처 유지, dict 솔루션 반환
- `utils.py`는 포함하더라도 **수정 불가** (서버에서 덮어씀)
- 평가서버: Ubuntu 24.04, 최대 4코어/16GB, 인터넷 차단, 시간제한 수분~30분
- 제출 쿨다운 12시간 · infeasible/시간초과/크래시 = −1점

## 데이터셋

`data/train/` 의 40개 인스턴스 — 베이 2~5개, 블록 100~300개 범위.
각 JSON: `name`, `bays`(width/height), `blocks`(release/due/processing/workload/
bay_preferences/shape), `weights`(w1/w2/w3). 좌표는 기준점(첫 레이어 첫 정점=(0,0))
상대값, 소수점 4자리.
