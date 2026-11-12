# pyPhotometry event-triggered plot 연결

Akam & Walton (2019), *pyPhotometry: Open source Python based hardware and software for fiber photometry data acquisition*, Scientific Reports 9:3521, [doi:10.1038/s41598-019-39724-y](https://doi.org/10.1038/s41598-019-39724-y)의 p.3, **Graphical user interface** 절에서는 **Digital 1의 상승 에지(LOW→HIGH)**에 맞춰 **Analog 1**의 recency-weighted 평균을 표시한다고 설명합니다. p.2의 **Acquisition board** 절에서는 두 디지털 입력을 동기화 및 행동 이벤트 기록에 사용하는 방법을 설명합니다.

계속 HIGH인 고정 전압은 처음 한 번만 상승 에지를 만듭니다. 이 코드에서는 평소 LOW, 이벤트마다 짧은 HIGH 펄스를 출력합니다. pyPhotometry가 신호를 취득하고 평균을 표시하므로 pyboard의 펌웨어를 이 저장소의 코드로 교체하지 않습니다.

## 출력과 시간표

| Uno 핀 | 기본 신호 | 기본 시점: 시행 시작 기준 | HIGH 지속 시간 |
|---|---|---:|---:|
| D7 | cue 사전 트리거 | 900ms (표시 요청 100ms 전) | 20ms |
| D7 | reward 사전 트리거 | 5900ms (밸브 개방 명령 100ms 전) | 20ms |
| GND | 신호 기준 전위 | pyPhotometry BNC 외부 실드와 공통 접지 | — |

cue 표시 요청은 1000ms, reward 밸브 개방 명령은 6000ms입니다. **D7 하나에서 두 이벤트 모두 같은 펄스를 출력**하므로 Digital 1 한 채널만 연결합니다. D8은 사용하지 않으며 LOW로 유지합니다. D7에는 세션 시작 LED 신호가 출력되지 않습니다. D9에는 시작 신호·cue 확인·reward가 섞여 있으므로 이 용도에는 D7을 사용하세요.

Digital 1의 두 접점은 일반적으로 **Signal과 GND**이며, 두 개의 이벤트 입력이 아닙니다. BNC는 중심 접점이 Signal, 바깥 실드가 GND입니다. 2핀 커넥터/어댑터에서는 해당 보드의 Signal/GND 표기 또는 회로도로 위치를 확인하세요. 사진이나 핀 표기 없이 왼쪽/오른쪽 위치를 지정하지 않습니다.

## 배선: Uno 출력 전압을 낮춘 뒤 BNC에 연결

Uno D7의 HIGH는 약 **5V**이며 소프트웨어로 3.3V HIGH를 지정할 수 없습니다. 사용 중인 pyPhotometry 보드 revision의 디지털 입력 허용 전압을 확인하기 전에는 5V를 직결하지 마세요. **5V 입력을 받을 수 있는 단방향 5V→3.3V 레벨 변환기**를 사용하면 됩니다. Analog 1·2가 아닌 **Digital 1의 Signal(BNC 중심 핀)**에 연결합니다.

고임피던스 디지털 입력에 짧은 케이블로 연결할 때는 다음 저항 분압도 사용할 수 있습니다. 저항 2개(1% 권장)를 사용합니다.

```text
Uno D7 ── 2.2 kΩ ──┬── Digital 1 Signal (BNC 중심 핀)
                   └── 3.3 kΩ ── GND

Uno GND ────────────── Digital 1 GND (BNC 외부 실드)
```

D8은 연결하지 않습니다. D7과 D8을 서로 묶을 필요도 없습니다.

5V HIGH를 가정하면 BNC 중심 핀에서 `5 × 3.3 / (2.2 + 3.3) = 3.0V`가 됩니다. 이는 3.3V 로직용 신호이며 입력 전원 공급용 연결이 아닙니다. 연결 전 오실로스코프로 HIGH가 해당 보드의 논리 HIGH 조건을 만족하고 최대 허용 전압을 넘지 않는지 확인하세요. 위 회로는 고임피던스 입력 기준이므로 50Ω 종단을 사용하지 않습니다. Uno 5V/3.3V 전원 핀을 BNC 신호 핀에 연결하지 않습니다.

## cue와 reward를 함께 event-triggered 평균에 표시

논문 버전 GUI는 Digital 1 기준 평균을 한 개 표시합니다. 현재 코드는 cue 전과 reward 전에 Digital 1로 동일한 펄스를 보내므로 **두 이벤트의 반응이 같은 평균에 함께 들어갑니다**. GUI에서 이벤트 종류를 구분하거나 채널을 바꾸지 않아도 됩니다. Digital 2는 비워 두어도 됩니다.

GUI에서 Analog 1과 Digital 1 입력을 확인하고 기록을 시작한 뒤 행동 세션을 시작하세요. Event triggered plot의 표시 옵션이 있는 버전에서는 이를 켭니다. 펄스 전후 구간의 데이터가 모여야 평균이 표시됩니다. Digital 1의 상승 에지가 그래프의 0초이므로, 기본 설정에서 **예정된 cue/reward는 +0.100초**에 해당합니다. 이벤트 시점이 0초인 그래프가 필요한 경우 기록 후 분석에서 보정하거나 아래 lead 값을 0으로 바꾸세요.

## 설정 및 설치

[config/experiment.json](../config/experiment.json)의 기본값:

```json
"photometry": {
  "enabled": true,
  "cue_lead_ms": 100,
  "reward_lead_ms": 100,
  "pulse_ms": 20
}
```

`cue_lead_ms`는 0부터 `cue_delay_ms`까지, `reward_lead_ms`는 0부터 `reward_at_ms - cue_delay_ms - cue_duration_ms`까지 허용합니다. `pulse_ms`는 1–1000ms입니다. 두 펄스가 하나로 합쳐지지 않도록 cue와 reward 트리거 사이에 최소 1ms LOW 구간이 남아야 하며, 겹치는 설정은 거부합니다. 실제 루프 지연으로 겹쳐도 `SESSION_ABORTED,8`로 중단합니다. 낮은 기록 속도에서는 이 LOW 구간도 샘플 간격보다 충분히 길어야 합니다. 기본 설정의 LOW 구간은 약 4.98초입니다. 0ms lead는 같은 루프에서 이벤트 명령 직전에 트리거를 출력합니다. 펄스 폭은 기록 샘플 간격보다 충분히 길게 잡으세요. 예를 들어 130Hz의 간격은 약 7.7ms여서 기본 20ms 펄스는 여러 샘플에 걸립니다. 더 낮은 샘플링 속도에서는 폭을 늘려야 합니다.

1. Pi에서 `git pull origin main`으로 Python 코드와 설정을 업데이트합니다.
2. [Arduino 스케치](../arduino/HEADFIXED_ARDUINO/HEADFIXED_ARDUINO.ino)를 **실제 Uno에 다시 업로드**합니다. D7을 다른 장치가 사용하고 있지 않은지 확인합니다.
3. 전압 변환과 공통 접지를 연결하고 Digital 1에서 시행당 두 펄스를 확인합니다.
4. pyPhotometry 기록을 먼저 시작하고 Pi에서 기존 실험 명령을 실행합니다.

```bash
python HEADFIXED_PYTHON.py --port /dev/ttyACM0 --mouse-id mouse01
```

새 Python은 `CONFIG` 뒤에 `TRIGGERS 100 100 20`을 보내고 `TRIGGERS_OK,2` 응답을 확인한 다음 세션을 준비합니다. 이 명령이 없는 이전 펌웨어나 D7/D8 분리 출력 버전(`TRIGGERS_OK,1`)이면 준비 단계에서 오류가 납니다. 이 경우 새 스케치를 업로드하세요. `photometry.enabled`를 `false`로 설정하거나 이 섹션을 생략하면 추가 트리거 명령을 보내지 않습니다. Uno도 새 `CONFIG`마다 트리거 설정을 비활성화하여 이전 세션의 설정이 남지 않게 합니다.

## 시간 해석과 중단 처리

- cue 트리거는 예정된 **CUE_REQUEST** 기준입니다. 실제 발광은 USB 전달, Pi 처리, 화면 갱신만큼 늦으므로 정확히 100ms 뒤라고 보장하지 않습니다. 실제 발광 시점은 포토다이오드로 측정합니다.
- reward 트리거는 밸브의 전기적 개방 명령 기준입니다. 실제 물 도달은 밸브와 튜브의 지연이 추가됩니다. 두 트리거 모두 Arduino 루프의 ms 단위 타이밍이며, pyPhotometry에서도 샘플 간격만큼 양자화됩니다.
- reward 전 D7 펄스는 보상 시행에서 cue-off 확인을 받은 뒤에만 출력됩니다. 비보상 시행에는 cue 전 펄스만 있습니다. cue-off 확인이 늦으면 트리거도 늦을 수 있습니다. 루프 지연으로 양의 lead를 가진 트리거를 이벤트 예정 시각까지 보내지 못하면 `SESSION_ABORTED,8`로 중단합니다.
- 이미 보낸 사전 트리거 뒤에 STOP, 통신 끊김 또는 화면 오류가 발생하면 실제 이벤트가 취소될 수 있습니다. 사전 트리거만으로 실제 이벤트 발생을 판정하지 말고 `CUE_ON`/`DISPLAY_ON`, `REWARD_ON`, `SESSION_ABORTED` 기록과 함께 확인합니다.
- STOP·watchdog·프로토콜 오류·각 시행 종료 시 D7을 LOW로 내립니다. 펄스 폭을 시행 종료보다 길게 설정하면 그 시점에 잘립니다. 수동 밸브 시험은 트리거를 출력하지 않습니다.
- `events.csv`에 `CUE_TRIGGER_ON/OFF`, `REWARD_TRIGGER_ON/OFF`를 Arduino `millis()`와 시행 번호로 기록합니다. 강제 중단 또는 시행 종료로 펄스가 잘리면 별도 OFF 이벤트 대신 중단/시행 종료 이벤트가 남습니다. `metadata.json`에는 photometry 설정이 저장됩니다. Arduino와 pyPhotometry의 시간축은 서로 다르므로 펄스로 대응시켜 분석합니다.

펌웨어 가상 입출력 검사와 Python 시뮬레이션은 실제 전압·BNC 수신·광학/유체 지연을 검증하지 않습니다. 첫 연결 때 실제 장비로 펄스 높이·폭·이벤트 간격을 확인하세요.
