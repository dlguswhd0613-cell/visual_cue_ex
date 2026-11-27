# 현재 Arduino에서 물 보상 habituation

`habituation.py`는 현재 `arduino/HEADFIXED_ARDUINO/HEADFIXED_ARDUINO.ino`가 업로드된 Uno에서 실행합니다. 기존 `reference/HEADFIXED_PYTHON.py`의 habituation 동작과 시행표 형식을 따릅니다.

## Pi SSH에서 실행

```bash
cd ~/visual_cue_ex
git pull --ff-only origin main
python3 habituation.py --port /dev/ttyACM0 --mouse-id NPY195_2
```

준비 메시지가 나오면 `start` 또는 `2`를 입력하고 Enter를 누릅니다. `stop` 또는 `4`로 중단, `q` 또는 `quit`로 종료합니다. Ctrl+C도 출력을 중지합니다. 한 번의 실행에서 한 세션을 진행하고, 완료하면 프로그램이 종료됩니다.

- 시작 LED/TTL 표시 약 3초 후 최초 대기 90초
- 물 제공 80회, 매번 밸브 개방 30ms
- 보상 후 첫 유효 lick과 밸브 닫힘 확인 후 다음 ITI 시작
- 이후 lick으로 종료된 trial부터 다음 물 제공까지 10–20초의 균등분포
- 마지막 보상도 lick 확인 후 종료
- Lick이 없으면 밸브를 닫은 채 계속 대기, 세션 시간 제한 없음

보상 전 lick은 해당 보상을 소비한 것으로 처리하지 않습니다. 밸브가 열린 동안 발생한 lick은 인정하고, 30ms 개방을 완료한 뒤 ITI로 넘어갑니다. 센서의 보상 후 LOW→HIGH 신호로 소비를 판단합니다.

프로그램은 디스플레이에 접근하지 않습니다. 실행 전에 Pi 화면의 상태를 원하는 대로 설정하세요. `DISPLAY` 환경 변수나 화면 창은 필요 없습니다.

## 기존 시행표 사용

`Reward,ITI_Duration_S` 형식의 80행 시행표를 그대로 지정할 수 있습니다.

```bash
python3 habituation.py \
  --port /dev/ttyACM0 \
  --mouse-id NPY195_2 \
  --schedule schedules/habituation/20261127_164925_habituation_schedule.csv
```

`--schedule`을 생략하면 자동으로 시행표를 만듭니다. 동일한 순서를 다시 생성하려면 `--seed 123`처럼 seed를 지정합니다. 기본 ITI 범위는 reference와 같은 10–20초 균등분포입니다.

보상 횟수는 `--rewards`, 밸브 시간은 `--valve-ms`, 최초 대기는 `--initial-iti-s`, 이후 범위는 `--iti-min-s`와 `--iti-max-s`로 지정합니다. 보상 횟수는 1–200회, 밸브 시간은 1–1000ms, ITI는 1–65535초 범위입니다. 시행표를 불러올 때도 행 수와 ITI 설정이 맞아야 합니다. 현재 형식의 `Trial,ITI_Duration_S,Rewarded` 시행표도 모든 행이 보상인 경우 사용할 수 있습니다.

## 모의 시험

아래 명령은 보드 연결 없이 2회만 진행합니다. 준비 후 `start`를 입력하세요. 합성 lick을 자동으로 생성합니다.

```bash
python3 habituation.py --simulate --rewards 2 --initial-iti-s 1 --iti-min-s 1 --iti-max-s 1
```

`--autostart`를 추가하면 입력 대기를 생략합니다. 이 옵션은 실제 장치에서도 즉시 세션을 시작합니다.

## 기록 및 통신

`data/habituation/` 아래 개체별 고유 세션 폴더에 `events.csv`, `schedule.csv`, `metadata.json`을 저장합니다. 터미널에는 보상 번호, `LICK`, `WAIT_LICK`, 다음 물 제공까지의 ITI를 표시합니다. `schedule.csv`는 실제 요청한 물 제공 간격을 현재의 `Trial,ITI_Duration_S,Rewarded` 형식으로 보관합니다.

현재 펌웨어는 cue 확인 명령을 받아야 보상을 진행하므로 Python이 시각 자극 없이 `CUE_ON/OFF`를 내부적으로 확인합니다. 이 과정에 1초를 배정하고, 보드의 ITI에서 1초를 빼서 요청한 물 제공 간격에 포함합니다. 예를 들어 요청 ITI 10초는 보드 ITI 9초와 내부 처리 1초입니다. `events.csv`의 Arduino `ITI_DURATION_S`는 9초로 기록되며 `schedule.csv`와 터미널에는 요청값 10초가 표시됩니다. 실제 간격에는 보드 루프 및 통신의 작은 시간 오차가 있을 수 있습니다.

`CUE_ON/OFF`는 내부 통신 이벤트이고 화면 표시 시각이 아닙니다. D9에는 시작 표시, 내부 확인 절차의 짧은 펄스, 보상 개방 펄스가 발생합니다. D7 사전 트리거는 설정하지 않아 LOW로 유지됩니다. 내부 단계와 TTL 동작은 metadata에도 기록됩니다. Arduino가 마지막 보상 이후 lick을 기다리는 동안에도 연결 확인 신호를 계속 보내며, 통신이 끊기면 펌웨어가 출력을 닫습니다.
