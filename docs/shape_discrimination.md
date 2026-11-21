# 정사각형·마름모 시각 변별

기본 설정은 `config/experiment.json`입니다. 검정 배경 중앙에 정사각형 윤곽으로 잘린 수평 줄무늬를 제시합니다. 줄무늬는 두 조건 모두 같은 방향·속도·공간주파수·초기 위상으로 아래로 움직이며, 윤곽만 회전합니다.

| 조건 | 윤곽 방향 | 횟수 | 보상 |
|---|---:|---:|---|
| CS+ | 45° 마름모 | 50 | trial 시작 6초에 밸브 30ms 개방 |
| CS− | 0° 정방향 정사각형 | 50 | 없음 |

총 100회를 한꺼번에 무작위로 섞습니다. 교대 제시나 연속 조건 수 제한은 없으며, seed를 지정하면 순서를 재현할 수 있습니다. 초기 ITI 90초, 이후 ITI 10–20초의 기존 지수분포를 유지합니다. cue는 trial 시작 후 1–3초에 제시합니다.

기본 Operant에서는 CS+ 보상 후 첫 lick 및 밸브 닫힘을 확인하면 trial이 끝납니다. CS−는 lick과 관계없이 trial 시작 10초에 끝나고 ITI로 넘어갑니다. CS− lick에 별도 벌이나 시간 연장은 없습니다. `--task pavlovian`을 지정하면 두 조건 모두 trial 시작 10초에 끝납니다. CS+ 보상은 lick 발생과 관계없이 6초에 주며, Operant의 lick은 종료 조건입니다.

## 논문과 적용 범위

Wal et al. (2021), *Evaluating Visual Cues Modulates Their Representation in Mouse Visual and Cingulate Cortex*, J. Neurosci. 41:3531–3544. [원문](https://pmc.ncbi.nlm.nih.gov/articles/PMC8051678/), Methods p.3532 및 Figure 1.

논문은 아래로 움직이는 정현파 줄무늬, 대비 50%, 시간주파수 1.5Hz, 공간주파수 0.02–0.05 cycle/degree를 사용했습니다. 이 구현에서는 0.05 cycle/degree를 기본값으로 선택합니다. 도형을 돌려도 내부 줄무늬 방향과 위상은 바뀌지 않습니다. 자극 시작마다 위상을 0으로 초기화합니다. 기본 렌더링 목표는 60Hz이고, 위상은 실제 경과 시간으로 계산하므로 프레임이 생략되어도 진행 속도는 느려지지 않습니다.

0.05 cycle/degree에서는 20° 폭에 한 주기가 들어갑니다. 따라서 기존 6주기 Gabor보다 넓은 밝고 어두운 띠로 보입니다. 정방향 정사각형의 세로 폭은 약 14.21°이므로 약 0.71주기가 보이지만, 두 도형 내부의 같은 위치는 같은 줄무늬 값을 갖습니다.

논문의 40–55° 크기, 회색 배경, 달리기로 시작·종료하는 행동 조건, blank trial 및 43:43:14 비율은 적용하지 않습니다. 사용자가 지정한 검정 배경, 대각선 20°, 거리 15cm, CS+·CS− 각 50회와 기존 lick 기반 과제를 사용합니다. 화면 gray 값으로 지정한 대비·평균 밝기와 물리적 휘도의 관계는 실제 화면의 감마 보정에 따라 달라집니다.

## 크기와 화면 보정

사용자가 선택한 **20°는 두 도형의 공통 대각선** 기준입니다. 방향만 다르고 한 변 길이와 면적은 같습니다.

```text
대각선(cm) = 2 × 15 × tan(20° / 2) = 약 5.2898 cm
한 변(cm) = 대각선 / √2 = 약 3.7405 cm
대각선(px) = 대각선(cm) × 화면 가로 픽셀 수 / 화면 가로 길이(cm)
```

기본 화면 가정은 7인치 대각선, 800×480, 정사각형 픽셀입니다. 화면 가로 길이는 약 15.2462cm이며 대각선은 약 277.57px, 한 변은 약 196.27px입니다. 마름모의 가로·세로 폭은 20°이고, 정방향 정사각형의 가로·세로 폭은 약 14.21°입니다. 부드러운 가장자리를 위해 픽셀 경계에 부분 밝기를 적용합니다.

`stimulus.screen_width_cm`에는 실제 발광 영역의 가로 길이를, `screen_width_px`에는 실제 전체 화면의 가로 해상도를 넣으세요. `viewing_distance_cm`는 눈에서 화면 중심까지의 거리이며 정면에서 본다고 가정합니다. 전체 화면 해상도가 보정값과 다르면 실행 전에 오류를 표시합니다. 창 모드·이미지 미리보기는 물리적 시야각 검증용이 아닙니다. 화면 크기를 7인치라는 제품명만으로 확정할 수는 없습니다.

## 실행

```bash
cd ~/visual_cue_ex
git pull --ff-only origin main
DISPLAY=:0 python3 HEADFIXED_PYTHON.py \
  --port /dev/ttyACM0 \
  --mouse-id B67 \
  --task operant \
  --exit-when-done
```

준비 메시지가 나오면 SSH 터미널에 `start`를 입력하고 Enter를 누릅니다. `--autostart`를 붙이면 즉시 시작하므로 수동 시작 시 생략합니다. 기존 Uno의 비보상 시행 기능을 사용하므로 이번 변경을 위한 Arduino 재업로드는 필요 없습니다.

시행표를 생략하면 매번 50/50 시행표를 새로 만듭니다. 동일한 순서를 재사용하려면:

```bash
python3 generate_schedule.py --seed 123 --out schedules/shape_100_seed123.csv
# 실행 명령에 --schedule schedules/shape_100_seed123.csv 추가
```

새 CSV 열은 `Trial,ITI_Duration_S,Rewarded,Cue`입니다. CS+는 `Rewarded=1`, CS−는 `Rewarded=0`이어야 하고 각각 50행이어야 합니다. 기존 100% 보상 Gabor 시행표를 그대로 지정하면 오류를 표시합니다. 새 시행표를 생성하거나 `--schedule`을 생략하세요.

화면만 확인할 때는 Arduino 없이 다음 명령을 사용합니다. CS+·CS− 2개씩 총 4회이며 실제 보상은 없습니다.

```bash
DISPLAY=:0 python3 HEADFIXED_PYTHON.py --simulate --demo --windowed --exit-when-done
# 준비 후 start + Enter
```

이전 Gabor 설정은 `config/gabor.json`에 보관했습니다. `--config config/gabor.json`을 지정하면 기존 줄무늬와 100% 보상 시행표를 사용합니다. 이때 기존 Gabor schedule을 불러올 수 있습니다.

## 기록

세션 폴더의 `schedule.csv`에 trial별 CS+/CS−와 보상 여부를 저장합니다. `events.csv`에는 기존 `DISPLAY_ON`과 같은 소프트웨어 표시 시각으로 `CS_PLUS_ON` 또는 `CS_MINUS_ON`을 추가하고 Value에 trial 번호를 기록합니다. 실제 보상은 `REWARD_ON`, CS−의 보상 생략은 `NO_REWARD`로 구별합니다. 터미널에도 조건을 표시합니다.

D7 cue TTL은 두 조건 모두, reward TTL은 CS+에서만 발생합니다. 두 조건을 별도 TTL 전압으로 구별하지 않으며 CSV의 조건 표시를 사용합니다. `metadata.json`에는 설정, seed, cue protocol, 도형 크기, 화면 보정값과 회전 방향을 저장합니다. 화면 시각은 소프트웨어 flip 기준이므로 실제 빛의 지연은 별도 측정이 필요합니다.
