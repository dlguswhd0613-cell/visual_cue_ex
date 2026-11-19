# Photometry와 행동 이벤트 시간 정렬

같은 세션의 `.ppd`와 `events.csv`를 선택하면 TTL을 기준으로 시계를 맞추고,
signal·control·dF/F·lick을 같은 시간축에 표시합니다. 완료된 trial의 dF/F 평균을
계산하며, 간섭이 있었던 trial을 파일마다 따로 제외할 수 있습니다.

## Windows에서 실행

Python 3.10 이상이 필요합니다. 명령 프롬프트에서 다음을 실행하세요.

```cmd
cd /d D:\visual_cue_ex
git pull --ff-only origin main
cd photometry_analysis
py -m pip install -r requirements.txt
run_analysis.bat
```

패키지 설치는 처음 한 번만 하면 됩니다. 이후에는 이 폴더의 `run_analysis.bat`을
더블클릭하거나 `py select_analysis.py`를 실행하세요. 매번 다음을 선택합니다.

1. 분석할 `.ppd` 파일
2. 같은 세션의 `events.csv` 파일
3. 결과를 저장할 폴더
4. 평균에서 제외할 trial 번호: 예를 들어 `3,7,12-15`. 빈칸이면 전체 포함

결과는 선택한 저장 폴더 아래 `PPD이름_aligned_분석시각`이라는 새 폴더에 저장됩니다.
입력 데이터는 직접 지정하며, 다른 세션의 제외 목록을 자동으로 재사용하지 않습니다.
분석이 끝나면 `review.html`이 브라우저에서 열립니다. Linux에서는 아래 명령줄 방식을
사용할 수 있고, 파일 선택창을 쓰려면 데스크톱과 tkinter가 필요합니다.

## 결과 확인과 trial 제외

`review.html`은 Chrome/Edge에서 오프라인으로 열 수 있습니다. 전체 세션과 개별 trial의
signal·control·dF/F·lick을 확인하고, trial 체크를 해제하면 평균과 SEM이 다시 계산됩니다.
**선택한 dF/F 평균 CSV 저장**, **trial별 평균·선택 CSV 저장**, 제외 목록 JSON 저장을
사용해 변경한 결과를 저장하세요. 브라우저에서 변경한 선택은 기존 결과 파일을 덮어쓰지
않으며, HTML을 다시 열면 최초 분석 때의 선택으로 돌아갑니다.

문 열림 등의 간섭 trial은 사용자가 지정합니다. 제외는 trial 평균에 적용되며,
실험 구간으로 추정한 bleaching/motion 보정 계수를 다시 추정하지 않습니다.

## 시간축과 TTL

- 기준 시계는 PPD입니다. 샘플 번호가 `i`, 샘플링 주파수가 `fs`일 때 시각은 `i / fs`초입니다.
  `fs`는 PPD에서 읽으며, 130Hz이면 샘플 간격은 약 7.692ms입니다.
- Digital 1의 상승 에지와 CSV의 `CUE_TRIGGER_ON`·`REWARD_TRIGGER_ON`을 대응시켜
  `ppd_time_s = slope * (Arduino_ms / 1000) + intercept_s`를 추정합니다.
  시작 시각 차이와 시계 속도 차이를 함께 보정합니다. `Host_Timestamp`를 기준으로 쓰지 않습니다.
- TTL이 cue/reward보다 100ms 먼저 나가더라도 **TTL끼리 대응**시킵니다. 실제 `REWARD_ON`,
  `LICK`의 Arduino 시각을 같은 식으로 변환하므로 별도로 100ms를 더하거나 빼지 않습니다.
- `lick_events.csv`에는 샘플 격자로 반올림하지 않은 정렬 시각을 저장합니다.
  `processed_data.csv`의 `lick_count`는 가장 가까운 사용 가능한 PPD 샘플에 집계합니다.
  같은 샘플에 여러 lick이 대응하면 횟수를 더합니다. trial 분류에는 반올림 전 시각을 사용하며,
  TRIAL_END와 같은 시각의 lick도 해당 trial에 포함합니다.
- `time_ppd_s`는 PPD 시작=0, `time_session_s`는 정렬된 SESSION_START=0,
  `time_from_trial_start_s`는 각 trial 시작=0입니다. 모두 PPD 시계의 초 단위입니다.
- `CUE_ON`은 Arduino가 화면 표시 확인 메시지를 받은 시각입니다. 실제 모니터 발광이나
  보상액 도착 시각을 측정한 값은 아닙니다. Arduino_ms가 없는 host 이벤트는 정렬 시각을 비워 둡니다.

자동 대응은 양쪽 TTL 개수가 같고 최소 3개이며 순서가 증가할 때만 시도합니다.
시계 속도 차이가 1% 이내이고 최대 정렬 잔차가 PPD 샘플 간격의 2배 이내여야 결과를 만듭니다.
`ttl_matches.csv`와 `alignment_qc.json`에서 대응과 잔차를 확인하세요. 이는 시계 정렬의
검사이며 물리적 자극/보상 시각의 정확도를 보장하는 값은 아닙니다.

TTL 개수가 다르면 자동 정렬을 중지합니다. 대응을 직접 확인한 경우
`arduino_ms,ppd_time_s` 열을 가진 CSV를 `--sync-pairs`로 지정할 수 있습니다.
Arduino reset/rollover 또는 여러 SESSION_START가 섞인 기록은 먼저 분리/보정해야 합니다.

## 전처리, 세션 자르기, 평균

`data_import.py`의 필터링·bleaching·motion 보정을 사용하며, 반환된 보정 신호를 세션 공통 F₀로 나눕니다. 기본 signal은 `analog_2`,
control은 `analog_1`이며, 20Hz 저역통과 → 이중 지수 bleaching 보정 → control 선형회귀 motion
보정 → dF/F 계산 순서입니다. **dF/F 단위는 %**이며 이미 100을 곱한 값입니다.
원본 전처리 함수가 `analog_*_filt`를 사용하지 않으므로 추가 0.01Hz high-pass를 적용하지 않습니다.

TTL로 SESSION_START와 마지막 완료 TRIAL_END를 찾고 **그 구간으로 먼저 자른 뒤** 필터링, bleaching fitting, motion 회귀 및 dF/F 계산을 수행합니다. fitting용 시간은 잘라낸 첫 샘플에서 0초로 다시 시작합니다. 실험 전후의 기록은 계수 추정에 사용하지 않습니다.
초기 ITI와 trial 사이 ITI는 세션 파일에 남습니다. PPD에 없는 시작 구간은 0으로 채우지 않으며,
photometry가 trial 전체를 포함하지 못하면 해당 trial은 평균에서 제외합니다.

각 TRIAL_START를 0으로 맞추고 PPD의 샘플링 주파수로 선형 보간한 뒤, 같은 상대 시각의
dF/F를 trial 간 동일 가중치로 평균합니다. trial 길이를 늘이거나 압축하지 않습니다.
기본 평균은 **선택한 모든 trial이 겹치는 구간**을 사용합니다. Operant처럼 trial 길이가
다르면 긴 trial의 뒷부분은 기본 평균에서 빠집니다. 별도 available-support CSV에는 각
시각에 남아 있는 trial로 계산한 평균과 N을 제공합니다.

SEM은 trial 간 표본 표준편차 / sqrt(N)입니다. N=1이면 SEM을 비우며 N=0이면 평균도
비웁니다. `trial_summary.csv`의 `mean_dff_percent`는 각 trial 안에 실제 기록된 샘플의
시간 평균입니다. 별도 trial baseline 차감은 하지 않습니다.

## 생성 파일

| 파일 | 내용 |
|---|---|
| `review.html` | 공통 시간축, 개별 trial, 제외 선택, 평균 CSV 다운로드 |
| `processed_data.csv` | 잘라낸 세션의 signal/control/dF/F/F₀/lick, 시간, trial 번호 |
| `trials_only.csv` | trial 안 샘플만 선택. 원래 시간축 유지, ITI 미포함 |
| `processed_data.npz` | 실험 구간의 배열만 저장. `f0_v`는 모든 샘플에서 같은 공통 분모, `bleaching_fit_v`는 시간에 따라 변하는 bleaching 보정 곡선 |
| `events_aligned.csv`, `events_session.csv` | 전체 이벤트 및 세션 구간 이벤트의 정렬 시각 |
| `lick_events.csv` | 정확한 lick 정렬 시각, trial 번호, PPD 포함 여부 |
| `trial_summary.csv` | trial별 시작/끝, 평균 dF/F, lick 수, 평균 포함 여부 |
| `trial_dff_matrix.csv`, `trial_data.npz` | trial 상대 시간의 dF/F 행렬 및 signal/control 배열 |
| `dff_average.csv` | 포함 trial의 공통 구간 평균, SEM, N |
| `dff_average_available_support.csv` | 각 시각에 데이터가 남은 trial의 평균, SEM, N |
| `ttl_matches.csv`, `alignment_qc.json` | TTL 대응과 잔차, 정렬 계수, 입력 해시, 처리 조건 |
| `trial_selection.json` | 이 입력 파일 쌍에 대한 제외 목록과 해시 |
| `aligned_session.png`, `dff_average.png`, `dff_average.svg`, `ttl_alignment_qc.png` | 전체 세션, 평균·lick raster, TTL 잔차 그림 |

`trial_id=0`은 trial 밖입니다. HTML의 전체 세션 곡선만 표시 속도를 위해 줄여 그립니다.
CSV/NPZ와 개별 trial 배열은 전체 샘플 해상도를 유지합니다.

## 명령줄에서 경로 지정

`photometry_analysis` 폴더에서 실행합니다. Linux에서는 `py` 대신 `python3`를 사용하세요.

```cmd
py align_photometry.py --ppd "D:\recordings\mouse01.ppd" --events "D:\behavior\events.csv" --out "D:\analysis\mouse01" --exclude-trials "3,7,12-15"
```

`--exclude-trials`를 생략하면 모든 완전한 trial을 포함합니다. GUI와 달리 CLI의 `--out`은
지정한 폴더에 바로 저장하므로 재분석 결과를 보존하려면 다른 폴더를 지정하세요.
다른 채널을 썼다면 `--digital 2`, `--signal analog_1 --control analog_2` 등으로 바꿀 수 있습니다.

같은 파일에 저장한 제외 목록을 다시 적용하려면 `--exclude-trials` 대신 `--selection-json`을
사용하세요. PPD와 CSV의 SHA-256이 모두 맞아야 적용됩니다.

```cmd
py align_photometry.py --ppd "D:\recordings\mouse01.ppd" --events "D:\behavior\events.csv" --out "D:\analysis\mouse01_revised" --selection-json "D:\analysis\mouse01\trial_selection.json"
```

검사 명령은 `py -m unittest discover -p "test_*.py" -v`입니다. 합성 데이터로 시계 정렬, lick의 trial
분류와 샘플 배정, 세션 자르기, 제외 평균, 파일별 선택 목록을 확인합니다.
라이선스와 원본 기여자는 [NOTICE.md](NOTICE.md)를 참고하세요.

## 세션 구간 평균과 early / middle / late 비교

새 코드로 분석을 다시 실행하면 `review.html`에 아래 기능이 표시됩니다. 기존 HTML은 다시 생성해야 합니다.

- **01 구간 보기:** SESSION_START 기준 시작·끝 초를 지정하면 해당 구간의 실제 샘플 평균 dF/F, F₀, Signal을 표시하고 CSV로 저장합니다. ITI가 포함되며 trial 제외 목록은 이 시간 평균에 적용하지 않습니다. 데이터가 없는 구간을 0으로 채우지 않습니다.
- **05 선택 평균:** trial 번호 범위와 trial 시작 기준 시간 범위(예: 0–6초)를 지정하면 선택한 trial들의 평균 파형과 SEM을 표시합니다. 03의 제외 목록도 반영합니다.
- **Early / middle / late:** 완료 trial을 시간순으로 나열한 뒤 `floor(N/3)`, `floor(2N/3)` 위치에서 나눕니다. 100회는 1–33 / 34–66 / 67–100이며 나머지는 뒤 그룹에 포함합니다. 제외된 trial 때문에 경계가 바뀌지는 않습니다. 실제 trial 번호가 연속되지 않으면 순서로 나눕니다.
- **세 곡선 비교:** dF/F (%)가 기본이며 F₀ (V) 또는 Signal (V)도 선택할 수 있습니다. 각 trial의 같은 상대 시각을 동일 가중치로 평균합니다. 세 그룹 모두 포함 trial 전체의 공통 시간 구간을 사용합니다. N=0은 빈 곡선, N=1은 SEM 없음으로 표시합니다.
- **Trial별 변화:** 지정한 trial 내 시간 구간의 평균을 trial마다 점으로 표시합니다. 그 시간 범위를 끝까지 기록하지 못한 trial은 점에서 제외합니다. 동일한 관찰 구간으로 진행에 따른 반응을 비교할 수 있습니다.

trial 번호 범위는 선택 평균에만 적용되며, 세 그룹 비교는 전체 trial과 제외 목록을 사용합니다. 기본 trial 내 시간 범위는 전체 완전한 trial이 겹치는 구간입니다. 범위를 더 늘리면 세 그룹 평균은 공통 데이터 구간에서만 표시됩니다. F₀는 잘라낸 세션 전체의 exponential 추정값을 평균한 단일 상수이며, 모든 시점·trial·그룹에서 동일합니다. ITI도 평균 범위에 포함되며 trial 제외나 선택 구간 변경으로 재계산하지 않습니다.

`early_middle_late.csv`, `.png`, `.svg`에는 최초 제외 목록으로 계산한 세 그룹 비교가 저장됩니다. PNG/SVG는 dF/F·F₀·Signal을 각각 별도 축에 표시하며, 각 축 안에 세 그룹 곡선이 겹쳐집니다. HTML에서 변경한 선택은 비교 평균·trial별 구간 평균 CSV로 별도 저장하세요.

`trial_comparison.py`는 그룹 지정과 정적 결과 저장을, `trial_comparison.js`는 HTML의 범위 선택·비교·다운로드를 담당합니다. `trial_summary.csv`에는 고정 그룹 `stage`, `mean_f0_v`, `mean_signal_v`도 포함됩니다. 전처리 범위와 그룹 규칙은 `alignment_qc.json`에 기록됩니다.

## 세션 내 공통 분모

한 세션에서는 다음과 같이 하나의 F₀를 고정합니다.

```python
session_f0 = np.mean(signal_expfit)  # 잘라낸 실험 구간 전체, ITI 포함
processed = 100 * signal_mc / session_f0
```

`signal_mc`는 시간에 따라 변하는 exponential 곡선을 차감하고 motion을 보정한 신호입니다. 그 차감 곡선은 `bleaching_fit_v`에 저장하며, 분모 `f0_v`와 구별합니다. 세 그룹을 별도로 정규화하지 않으므로 같은 크기의 보정 신호는 early/middle/late 어디서나 같은 dF/F 값으로 표현됩니다. `alignment_qc.json`의 `session_f0_v`와 HTML의 처리 기준에 실제 공통 분모를 표시합니다.

이 정규화는 원본의 시간별 `signal_expfit(t)`로 나누는 방식에서 변경된 것입니다. `data_import.py`를 단독으로 기본 옵션으로 호출하면 원본 방식이 유지되며, 이 분석 프로그램은 `normalisation=None`으로 보정 신호를 얻어 위 공통 분모를 적용합니다. 이전 결과를 사용하려면 새 코드로 재분석해야 합니다.
