# OpenFoam-log-monitor
플루언트가 잔차를 그래프로 보여주는게 부러워서 만든 모니터입니다
Python terminal tool for monitoring OpenFOAM solver progress and residuals in real time from existing log files.

# OpenFOAM Log Monitor

OpenFOAM 계산을 돌려 놓고 진행 상황을 확인할 때마다 긴 로그를 훑는 게 귀찮아서 만들었습니다. 
이미 실행 중인 계산의 로그 파일을 지정하면, 터미널 한 화면에서 현재 반복 또는 물리시간, 잔차 변화, 최근 오류 메시지를 확인할 수 있습니다.

Python과 `curses`가 있는 환경에서 바로 실행할 수 있습니다. SSH나 클러스터 터미널에서도 사용하기 쉽도록 별도의 그래프 프로그램이나 딴거 없어도 됩니당

## 주요 기능

- `simpleFoam`의 반복 진행률과 `pimpleFoam`의 물리시간 진행률 표시
- 압력·속도·난류 변수 등 로그에 기록된 초기 잔차를 로그 스케일 그래프로 표시
- `snappyHexMesh`의 현재 격자 생성 단계와 마지막으로 보고된 셀 수 표시
- 로그에 추가되는 내용을 읽기 전용으로 확인. `q`로 모니터를 닫아도 계산은 계속 진행됩니다.

## 빠른 시작

```bash
python3 foam_monitor.py /path/to/case/log.simpleFoam
```

경로 없이 실행하면 로그 파일의 절대경로를 입력할 수 있습니다. 화면의 진행률은 설정한 반복 횟수 또는 물리시간 범위를 기준으로 합니다. 수렴 여부는 잔차와 차압·유량 등 관심 결과의 안정성을 함께 확인하면 좋습니다.

눈아플때 짱이야!

TIP: 터미널에 py 파일을 끌어서 모니터를 실행시킨후 로그 절대경로를 입력하지 않고 바로 로그를 터미널에 넣어도 작동됨니당~

ENG

# OpenFOAM Log Monitor

I was jealous of Fluent’s residual plots, so I made my own monitor.

A Python terminal tool for monitoring OpenFOAM solver progress and residuals in real time from existing log files.

I got tired of scrolling through long OpenFOAM logs every time I wanted to check on a run. Point this tool at the log of a running case to see the current iteration or simulation time, residual trends, and recent error messages, all on one screen.

All you need is Python and `curses`. It works over SSH and in cluster terminals, with no extra plotting software to set up.

## Features

- Track iteration progress for `simpleFoam` and simulation-time progress for `pimpleFoam`.
- Plot initial residuals for pressure, velocity, turbulence variables, and other logged fields on a logarithmic scale.
- See the current `snappyHexMesh` meshing stage and the last reported cell count.
- Follow new log entries in read-only mode. Press `q` to close the monitor while your simulation keeps running.

## Quick start

```bash
python3 foam_monitor.py /path/to/case/log.simpleFoam
```

Run the script without a log path to enter one interactively. The progress bar tracks the configured iteration or simulation-time range. To assess convergence, check the residual trends alongside quantities such as pressure drop and flow rate.

Your eyes will thank you!

**Tip:** If your terminal supports drag and drop, type `python3 `, drag `foam_monitor.py` into the terminal, and press Enter. When the monitor asks for the log path, drag the log file into the terminal and press Enter again. No need to type out the whole path!
