# Raspberry Pi 4B 설치·실행 안내

이 안내는 **실제 Raspberry Pi의 터미널**에서 진행합니다. 클라우드에 설치한 도구는 Raspberry Pi에 자동으로 설치되지 않습니다. Pi 4B에 64비트 Raspberry Pi OS Desktop을 설치하고, 7인치 화면에서 데스크톱이 정상적으로 보이는 상태를 기준으로 합니다.

## 1. 프로젝트 폴더 준비

새 코드가 GitHub에 저장된 뒤라면 Pi 터미널에서 저장소를 받을 수 있습니다.

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip libsdl2-2.0-0 libsdl2-image-2.0-0 libsdl2-mixer-2.0-0 libsdl2-ttf-2.0-0
git clone https://github.com/dlguswhd0613-cell/visual_cue_ex.git
cd visual_cue_ex
```

이미 폴더를 받은 경우에는 그 폴더로 이동합니다. GitHub에 아직 새 코드를 올리지 않았다면 프로젝트 폴더 전체를 USB 저장 장치 등으로 Pi에 복사해도 됩니다. 저장소의 `README.md`와 `HEADFIXED_PYTHON.py`가 보이는 위치에서 이후 명령을 실행하세요.

## 2. Python 패키지 설치

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Python 3.10 이상을 사용합니다. 새 터미널을 열 때마다 프로젝트 폴더에서 `source .venv/bin/activate`를 실행하면 이 프로젝트용 Python을 사용하게 됩니다.

Pygame 설치가 소스 빌드 과정에서 개발용 파일이 없다는 오류로 끝나면 다음 패키지를 설치한 뒤 패키지 설치를 다시 실행하세요.

```bash
sudo apt install -y build-essential python3-dev libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev libportmidi-dev
python -m pip install -r requirements.txt
```

## 3. 장치 없이 화면 확인

Pi의 7인치 화면에 열린 데스크톱 터미널에서 실행합니다. SSH 터미널만 연결한 상태에서는 화면 표시가 설정되어 있지 않을 수 있습니다.

```bash
python HEADFIXED_PYTHON.py --simulate --demo --windowed --autostart --exit-when-done
```

회색 창 왼쪽 절반의 중심(가로 25%, 세로 50%)에 정지된 줄무늬가 나타났다가 사라지는지 확인합니다. 이 실행은 Arduino 없이 가상의 lick과 보상 이벤트를 만들며, 실제 밸브를 제어하지 않습니다. `--demo`는 짧은 확인용 조건을 사용합니다. 창 모드 확인 뒤 `--windowed`를 빼면 전체 화면으로 표시합니다.

실험 화면에는 진행 글씨가 나오지 않습니다. 출력은 터미널에서 확인하세요. `--exit-when-done`을 빼면 세션이 끝나도 회색 화면이 유지됩니다.

## 4. Arduino Uno 스케치 업로드

Uno를 USB로 컴퓨터 또는 Pi에 연결하고 Arduino IDE에서 다음 파일을 엽니다.

```text
arduino/HEADFIXED_ARDUINO/HEADFIXED_ARDUINO.ino
```

보드는 **Arduino Uno**, 포트는 연결한 Uno에 해당하는 포트를 선택한 뒤 업로드합니다. IDE에서 컴파일만 하는 동작과 실제 보드에 업로드하는 동작은 다릅니다. 업로드 뒤에는 IDE의 시리얼 모니터를 닫으세요. Python과 시리얼 모니터가 동시에 같은 포트를 사용할 수 없습니다.

기존 연구실 배선인 부저 D6, 밸브 제어 D12, lick 센서 D11, LED D10, TTL D9를 사용합니다. Python 프로그램과 이 새 스케치는 함께 사용해야 합니다. `reference/`의 기존 스케치는 새 프로그램의 통신 규약과 다릅니다. 실험 전 물 공급만 시험하려면 [밸브 점검 안내](valve_test.md)의 `prime_valve.py`를 사용하세요.

## USB 포트 확인

Uno를 Pi에 USB로 연결한 뒤 확인합니다.

```bash
python -m serial.tools.list_ports
ls -l /dev/serial/by-id/
```

보통 `/dev/ttyACM0`이지만 다른 이름일 수 있습니다. `/dev/serial/by-id/`에 해당 보드 경로가 있으면 번호가 바뀌는 경우에도 구별하기 쉬우므로 그 경로를 `--port` 뒤에 넣어 사용할 수 있습니다.

포트 접근이 `Permission denied`로 실패하면 현재 사용자에게 시리얼 장치 접근 권한을 추가합니다.

```bash
sudo usermod -aG dialout "$USER"
```

그다음 로그아웃 후 다시 로그인하거나 Pi를 재부팅해야 변경이 적용됩니다. Python 프로그램 자체를 `sudo`로 실행할 필요는 없습니다.

## 5. 설정과 시행표 준비

[config/experiment.json](../config/experiment.json)을 열어 자극 크기와 공간주파수 등 실험 조건을 설정합니다. Gabor 설정의 단위와 예시는 [README](../README.md#자극과-실험-조건-바꾸기)에 있습니다.

현재 기본값은 모든 시행이 보상이고 ITI는 10–20초의 감소하는 지수분포입니다(정수 초, 시간 상수 3초). 시행표를 별도로 만들 필요는 없습니다. 프로그램이 세션 시작 전에 자동으로 시행표를 만들고 로그 폴더에 보관합니다.

여러 개체에 동일한 무작위 간격을 적용하려면 시행표를 한 번 만들어 공통으로 사용합니다. 기존 33초 ITI 시행표는 새 설정과 맞지 않으므로 다시 생성하세요.

```bash
python generate_schedule.py --seed 123 --out schedules/today.csv
```

이미 있는 파일은 덮어쓰지 않습니다. 새 실험일에는 파일 이름을 바꾸세요. 다른 설정 파일을 사용한다면 시행표 생성과 실제 실험 양쪽에 같은 `--config` 파일을 지정합니다. 생성한 파일을 사용하려면 실제 실행 명령 끝에 `--schedule schedules/today.csv`를 붙입니다.

## 6. 실제 세션 실행

자동 화면 꺼짐·화면 보호기를 Pi 데스크톱 설정에서 해제합니다. 동물에게 보이는 화면에 마우스 포인터나 다른 창이 겹치지 않는지 확인하세요. 디스플레이가 여러 개인 경우 `display.screen_index`로 자극을 보여 줄 화면을 선택할 수 있습니다.

```bash
source .venv/bin/activate
python HEADFIXED_PYTHON.py --port /dev/ttyACM0 --mouse-id mouse01
```

실제 세션에서는 `--simulate`, `--demo`를 사용하지 않습니다. 준비된 회색 화면에서 **Space**를 눌러 시작합니다. **Esc**는 세션을 중단하고 회색 화면으로 돌립니다. **Q**는 프로그램을 종료합니다. 세션이 끝난 뒤에도 회색 화면은 유지됩니다. 다음 개체는 프로그램을 다시 실행하고 `--mouse-id`를 바꾸세요.

2번 Operant의 기본 시간표는 시행 시작 → 1초에 자극 표시 → 3초에 자극 제거 → 6초에 보상 → 보상 후 첫 lick 및 밸브 닫힘 확인 시 시행 종료 → 10–20초 ITI입니다. 보상 전 lick은 종료 조건에 포함하지 않습니다. 밸브 개방 중 lick은 인정하되 30ms 개방을 완료한 뒤 종료합니다. Lick이 없으면 밸브를 닫고 회색 화면에서 계속 기다리며, 터미널에 `WAIT_LICK`이 표시됩니다. 다음 시행은 실제 시행 종료부터 ITI를 센 뒤 시작합니다. 마지막 시행도 lick을 기다린 뒤 세션을 종료합니다. 최초 대기는 별도로 90초입니다.

1번 Pavlovian은 `--task 1`로 선택합니다. lick과 관계없이 `reward_at_ms + post_reward_ms`에 trial이 끝나고 ITI가 시작됩니다. 현재 설정에서는 보상 6초 + 보상 후 관찰 4초 = trial 시작 후 10초입니다. 2번 Operant는 `--task 2`로 선택하며 위의 lick 종료 동작을 사용합니다. `--task pavlovian`, `--task operant`도 사용할 수 있습니다. 옵션을 생략하면 `session.task` 설정을 사용하며 기본은 `operant`입니다. 두 모드 모두 보상은 예정 시각에 제공되고, Operant의 lick은 trial 종료 조건입니다.

**두 task 모두 세션 시간 제한은 없습니다.** 설정된 모든 trial을 완료하면 정상 종료합니다. `metadata.json`에는 `task`, `task_number`, `trial_end_rule`, `end_reason: trial_count`와 완료 trial 수가 저장됩니다. **Pavlovian 선택에는 최신 Uno 스케치 업로드가 한 번 필요합니다.** 업로드 후 같은 스케치에서 두 모드를 사용할 수 있습니다. 기존 lick 종료 펌웨어(`771cc24`)를 사용하는 경우 Operant는 그대로 실행할 수 있습니다. `--demo`는 모의 실행에서만 사용할 수 있습니다. `--autostart`는 실제 장치에서도 Space 없이 시작하며 실제 보상을 제공합니다.

### Pi 키보드 없이 SSH에서 시작

Pi의 그래픽 데스크톱에 로그인되어 있어야 합니다. 일반적인 X11/XWayland 화면 번호가 `:0`인 환경에서는 SSH 터미널에서 다음처럼 실행합니다. 기존 실행은 먼저 Ctrl+C로 종료하세요.

```bash
cd ~/visual_cue_ex
DISPLAY=:0 python3 HEADFIXED_PYTHON.py --port /dev/ttyACM0 --mouse-id B67 --task 1 --autostart --exit-when-done
# Operant는 --task 1 대신 --task 2를 사용합니다.
```

가상환경으로 설치했다면 실행 전에 `source .venv/bin/activate`를 사용하세요. 터미널에 `START sent` 뒤 `SESSION_START`가 나오면 Uno가 세션 시작을 확인한 것입니다. 기본 설정은 시작 표시 3초와 초기 ITI 90초를 거치므로 첫 자극은 시작 약 94초 후 표시됩니다. 창은 시작 전부터 회색이어야 합니다. 이어서 `TRIAL_START`, `REWARD_ON`, 필요 시 `WAIT_LICK`, 그리고 `LICK`, `TRIAL_END`, `ITI_START`, `ITI_DURATION_S`가 출력됩니다. ITI의 시행 번호는 다음 시행이며, `ITI_DURATION_S`에는 대기 시간이 초 단위로 표시됩니다.

SSH 터미널의 **Ctrl+C**로 중단합니다. SSH 연결을 유지하고 전경에서 실행하세요. 세션 완료 후 회색 화면은 유지되며, 자동으로 프로그램도 종료하려면 `--exit-when-done`을 추가합니다. 화면 포커스를 잃으면 중단하는 기존 동작은 유지됩니다.

`DISPLAY=:0`는 모든 Pi 화면 구성에 동일하게 적용되는 값은 아닙니다. 창이 안 뜨거나 화면 연결 오류가 나오면 데스크톱의 실제 DISPLAY/Wayland 설정과 세션 접근 권한을 확인해야 합니다. SSH 자체는 화면을 제공하지 않습니다.

로그는 프로젝트의 `data/` 아래 세션별 폴더에 저장됩니다. `--outdir`로 다른 저장 폴더를 지정할 수 있습니다. 예를 들어 `--outdir /home/pi/experiment_data`를 사용할 수 있지만, 실제 Pi 사용자 이름이 `pi`가 아니라면 그에 맞게 경로를 바꿔야 합니다.

## 문제가 있을 때

| 현상 | 확인할 항목 |
|---|---|
| 포트를 열 수 없음 | USB 연결, 포트 이름, `dialout` 권한, 열린 시리얼 모니터 |
| 연결했지만 준비되지 않음 | 새 스케치를 Uno에 업로드했는지, 통신 속도가 115200인지 |
| 회색 화면에서 시작하지 않음 | 터미널의 준비 메시지 및 Space 입력 |
| Lick이 기록되지 않음 | D11 연결과 LOW→HIGH 센서 신호, 터미널 오류 및 이벤트 로그 |
| 화면이 없거나 다른 화면에 표시됨 | Pi 데스크톱 세션, 디스플레이 연결, `screen_index` |
| 자극 크기 오류 | `diameter_px`가 화면에 들어가는지 |
| 통신·화면 오류로 중단됨 | 터미널 오류 및 해당 세션의 `events.csv` |

`Arduino ERROR 1`은 알 수 없거나 형식이 잘못된 명령에 대한 응답입니다. 준비 중 오류에는 `command='...'`도 표시됩니다. 기존 실행 기록에서는 `tail -n 15 data/<세션 폴더>/events.csv`로 `ERROR` 직전의 `COMMAND`를 확인하세요. `LICK_END_CAPS`에서 실패하면 Arduino가 보상 후 lick 종료 기능을 지원하는지 확인해야 합니다. 그 기능 이전의 고정 시간 종료 펌웨어는 lick과 무관하게 trial을 진행하므로, 확인 명령만 제거하면 요청한 동작을 보장할 수 없습니다. 이 경우 저장소의 최신 스케치를 Uno에 업로드해야 합니다. `TASK 1`에서 실패한 경우에도 두 task를 지원하는 최신 스케치를 업로드하세요. 세션 시간 제한은 없으며 `SESSION_LIMIT_CAPS`는 보내지 않습니다.

프로그램과 Uno는 중단 명령이나 통신 끊김을 감지하면 출력을 닫도록 설계되어 있습니다. 최초 장치 확인은 동물 없이 진행하고, 30ms 밸브 개방의 실제 보상량과 센서 극성을 확인하세요. 정밀한 자극·DA 동기화는 TTL과 포토다이오드 측정으로 검증해야 합니다.
