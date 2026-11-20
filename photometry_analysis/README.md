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
5. dF/F 계산 방법. **3번 Tukey bisquare 강건 회귀**가 기본값입니다. 1번은 세션 공통 F₀, 2번은 control 일반 선형회귀(OLS)입니다.

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

반투명 청록색은 `CUE_ON`부터 `CUE_OFF`까지의 구간입니다. 전체 세션·개별 trial·lick raster는
각 trial의 기록 시각을 사용합니다. 평균과 early/middle/late 비교는 해당 그래프에 포함된
trial들의 cue 시작·끝 시각 중앙값을 표시합니다. 유효한 시작·끝 쌍이 있는 trial로 계산합니다.
저장되는 PNG/SVG에도 같은 기준을 적용합니다. 기존 분석 결과에 표시하려면 새 코드로 다시 실행하세요.

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

TTL로 SESSION_START와 마지막 완료 TRIAL_END를 찾고 **그 구간으로 먼저 자른 뒤** signal(`analog_2`)과 control(`analog_1`)에 2차 Butterworth 저역통과 필터를 정방향·역방향으로 적용합니다. 기본 차단 주파수는 **3 Hz**이며 원래 샘플링 주파수를 유지합니다.
기본 분석은 필터링한 두 채널에 Tukey bisquare IRLS를 적용하고 dF/F를 **%**로 저장합니다.
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
| `processed_data.npz` | 실험 구간의 샘플별 배열. `f0_v`는 실제 dF/F 분모. 2·3번은 `control_fit_v`에 회귀값을, 1번은 `bleaching_fit_v`에 bleaching 보정 곡선을 저장 |
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

trial 번호 범위는 선택 평균에만 적용되며, 세 그룹 비교는 전체 trial과 제외 목록을 사용합니다. 기본 trial 내 시간 범위는 전체 완전한 trial이 겹치는 구간입니다. 범위를 더 늘리면 세 그룹 평균은 공통 데이터 구간에서만 표시됩니다. ITI를 포함한 세션 전체에서 한 번 추정한 계수를 세 그룹이 공유합니다. 1번의 분모는 고정된 값이며 2·3번의 분모는 각 시점의 control 회귀값입니다. Trial 제외와 구간 선택은 평균에만 적용됩니다.

`early_middle_late.csv`, `.png`, `.svg`에는 최초 제외 목록으로 계산한 세 그룹 비교가 저장됩니다. PNG/SVG는 dF/F·F₀·Signal을 각각 별도 축에 표시하며, 각 축 안에 세 그룹 곡선이 겹쳐집니다. HTML에서 변경한 선택은 비교 평균·trial별 구간 평균 CSV로 별도 저장하세요.

`trial_comparison.py`는 그룹 지정과 정적 결과 저장을, `trial_comparison.js`는 HTML의 범위 선택·비교·다운로드를 담당합니다. `trial_summary.csv`에는 고정 그룹 `stage`, `mean_f0_v`, `mean_signal_v`도 포함됩니다. 전처리 범위와 그룹 규칙은 `alignment_qc.json`에 기록됩니다.

## 3번 방법의 Tukey bisquare 강건 회귀 (기본값)

첨부 MATLAB 함수 `IRLS_dFF.m`과 같은 방향으로, 필터링한 control을 설명변수로 두고 signal에 절편과 기울기를 맞춥니다. 각 반복에서 잔차를 leverage와 강건 척도로 보정한 뒤 상수 `c`로 나눈 값을 `u`라 하면, 가중치는 `|u| < 1`에서 `(1 - u²)²`, 그 밖에서 0입니다. 큰 일시적 신호는 회귀선에 적게 반영되고 dF/F에는 남습니다. 논문의 실제 데이터 분석에 사용된 **c = 1.4**가 기본값입니다. [Keevers & Jean-Richard-dit-Bressel, 2025](https://doi.org/10.1117/1.NPh.12.2.025003)

```python
f0 = intercept + slope * control_filt
dff_percent = 100 * (signal_filt - f0) / f0
```

MATLAB 함수가 반환하는 비율에 100을 곱한 값입니다. `alignment_qc.json`의 `low_pass_hz`와 `irls` 항목에서 차단 주파수, 상수, 반복 횟수, 기울기, 절편을 확인할 수 있습니다. 직접 호출할 때는 `preprocess_data(cropped, method='irls', low_pass=3, tuning_constant=1.4)`를 사용합니다. 명령줄에서도 `--low-pass`와 `--tuning-constant`로 변경할 수 있습니다.

## 1번 방법의 세션 내 공통 분모

한 세션에서는 다음과 같이 하나의 F₀를 고정합니다.

```python
session_f0 = np.mean(signal_expfit)  # 잘라낸 실험 구간 전체, ITI 포함
processed = 100 * signal_mc / session_f0
```

`signal_mc`는 시간에 따라 변하는 exponential 곡선을 차감하고 motion을 보정한 신호입니다. 그 차감 곡선은 `bleaching_fit_v`에 저장하며, 분모 `f0_v`와 구별합니다. 세 그룹을 별도로 정규화하지 않으므로 같은 크기의 보정 신호는 early/middle/late 어디서나 같은 dF/F 값으로 표현됩니다. `alignment_qc.json`의 `session_f0_v`와 HTML의 처리 기준에 실제 공통 분모를 표시합니다.

원본 함수의 시간별 `signal_expfit(t)`를 분모로 사용하려면 `preprocess_data(..., method='exponential', low_pass=10)`으로 직접 호출합니다. 분석 프로그램의 이전 1번 설정을 재현하려면 명령줄에서 `--method session_f0 --low-pass 20`을 지정합니다.

## 2번 방법: 필터링된 control 회귀로 dF/F 계산

파일 선택창 마지막 단계에서 **2**를 입력하면 아래 계산을 사용합니다. 이전 2번 설정은 명령줄에서 `--method control_fit --low-pass 20`으로 재현할 수 있습니다.

```python
slope, intercept, *_ = linregress(x=control_filt, y=signal_filt)
est_motion = intercept + slope * control_filt
signal_mc = signal_filt - est_motion
dff_percent = 100 * signal_mc / est_motion
```

실험 구간으로 먼저 자른 뒤 signal/control을 저역통과 필터링합니다. 회귀는 잘라낸 세션 전체에서 한 번 수행합니다. 이 방법에는 exponential fitting과 bleaching 곡선 차감이 없으며, 분모는 시간에 따라 변하는 회귀값입니다. `f0_v`와 `control_fit_v`에 그 값을 저장합니다. `alignment_qc.json`에는 `method: control_fit`, `session_f0_v: null`과 처리 방법을 기록합니다. 그림의 F₀ 비교도 실제 회귀값으로 계산합니다. 분모가 0 이하이거나 유한하지 않은 경우 설명과 함께 중단합니다.

`data_import.py`를 직접 사용할 때는 `preprocess_data(..., method='control_fit', normalisation='dF/F')`로 같은 값을 얻습니다. `normalisation=None`은 보정 신호만 반환합니다. 계산법은 trial 제외나 구간 선택 후에도 유지됩니다.

명령줄에서는 `align_photometry.py`의 기존 파일 경로 옵션에 `--method control_fit`을 추가합니다.

```cmd
py align_photometry.py --ppd "D:\recordings\mouse01.ppd" --events "D:\behavior\events.csv" --out "D:\analysis\control_fit" --method control_fit
```

직접 수정한 코드에 `control_flit`, `signal_flit`이 있으면 각각 `control_filt`, `signal_filt`로 고쳐야 합니다. 새 분석 경로는 반환된 `est_motion`으로 dF/F를 계산하므로, exponential 결과가 없는 상태에서도 GUI 실행과 결과 저장이 가능합니다.
