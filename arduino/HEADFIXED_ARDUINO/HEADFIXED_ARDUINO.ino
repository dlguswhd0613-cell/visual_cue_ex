/*
 * Visual-cue Pavlovian task for Arduino Uno; protocol version 1.
 * Raspberry Pi displays the cue and acknowledges its screen flips. This board
 * controls the existing wiring: buzzer D6 (silent), valve D12, lick D11
 * (INPUT, active HIGH), session LED D10, and event TTL D9.
 *
 * Commands, ASCII, one per line, at 115200 baud:
 *   HELLO                         -> READY,1 (only while idle)
 *   CONFIG n cue_delay_ms cue_ms reward_at_ms post_reward_ms valve_ms initial_iti_s
 *   TRIAL index iti_s rewarded    -> load each index 1..n, in order
 *   START                         -> start only after every trial is loaded
 *   CUE_ON index                  -> host has displayed the cue
 *   CUE_OFF index                 -> host has restored the gray background
 *   PING                          -> PONG,1; send at least every 500 ms
 *   STOP                          -> close outputs immediately, abort
 *   VALVE_CAPS                    -> VALVE_CAPS,1 (manual-valve support)
 *   VALVE_HOLD                    -> hold valve HIGH until STOP/watchdog
 *   VALVE_PULSE on_ms off_ms      -> repeat HIGH/LOW until STOP/watchdog
 * Manual commands require IDLE. Pulse intervals are 10..60000 ms.
 * Manual modes do not run trials or assert LED/TTL. PING is still required.
 * All replies are millis,EVENT,value. Reward time is measured from TRIAL_START.
 * Cue must have been acknowledged OFF before the reward deadline.
 * TTL accompanies session LED pulses, acknowledged cue, and reward pulse;
 * it is a command marker, NOT a measurement of physical display luminance.
 *
 * CONFIG limits: n 1..200; cue delay 0..60000 ms; cue duration 1..60000 ms;
 * reward at 1..60000 ms, strictly greater than cue delay + cue duration;
 * post-reward recording 1..60000 ms and >= valve duration; valve 1..1000 ms;
 * initial ITI 0..65535 s. TRIAL_END occurs at reward_at + post_reward.
 * Next ITI starts at TRIAL_END, independently of licking.
 * TRIAL ITIs: 0..65535 s; rewarded: 0 or 1. First ITI uses CONFIG instead.
 * Defaults belong to the host: 100 trials, cue starts at 1000 ms for 2000 ms,
 * reward at 9000 ms, trial ends at 13000 ms, 30 ms valve,
 * 90 s initial ITI, later ITIs 33 s (46 s between trial starts).
 * Original marker: initially OFF 500 ms, then 3 ON/OFF transitions spaced
 * 500 ms; the initial ITI starts at the third OFF transition (3 s total).
 * A rising lick edge is accepted after >=50 ms since the previous lick.
 * Licks are always logged, including ITIs, but never gate trial progression.
 *
 * ERROR codes: 1 malformed/unknown command; 2 out-of-range value;
 * 3 command invalid in current state; 4 incomplete/out-of-order schedule;
 * 5 input line too long; 6 incorrect cue acknowledgement.
 * SESSION_ABORTED codes: 1 STOP; 2 host heartbeat lost; 3 cue-on ACK timeout;
 * 4 cue-off ACK timeout; 5 protocol error during session;
 * 7 reward deadline reached without a valid cue-off acknowledgement.
 * STOP is also accepted while loading. Protocol errors during a session
 * abort and close all outputs. No blocking delays or dynamic Strings.
 */

#include <Arduino.h>
#include <stdint.h>
#include <string.h>

const uint8_t PIN_BUZZER = 6;
const uint8_t PIN_VALVE = 12;
const uint8_t PIN_LICK = 11;
const uint8_t PIN_LED = 10;
const uint8_t PIN_TTL = 9;
const uint16_t MAX_TRIALS = 200;
const uint32_t HEARTBEAT_TIMEOUT_MS = 2000;
// Request-to-display acknowledgement must arrive within 100 ms. Rejecting
// late onset preserves the requested trial timeline rather than rewarding
// a substantially delayed cue. This limit includes USB and display latency.
const uint32_t CUE_ON_TIMEOUT_MS = 100;
const uint32_t CUE_OFF_GRACE_MS = 1000;
const uint32_t LICK_DEBOUNCE_MS = 50;

enum SessionState : uint8_t {
  IDLE, START_MARKER, ITI, TRIAL_LEAD, WAIT_CUE_ON, CUE_VISIBLE,
  REWARD_DELAY, VALVE_OPEN, POST_REWARD, MANUAL_HOLD, MANUAL_PULSE
};

SessionState state = IDLE;
uint16_t trialITISeconds[MAX_TRIALS];
uint8_t rewardBits[(MAX_TRIALS + 7) / 8];
uint16_t totalTrials = 0;
uint16_t loadedTrials = 0;
uint16_t trialIndex = 0;
uint16_t cueDelayMs = 1000;
uint16_t cueDurationMs = 2000;
uint16_t rewardAtMs = 9000;
uint16_t valveDurationMs = 30;
uint16_t initialITISeconds = 90;
uint16_t postRewardMs = 4000;
uint32_t trialStartedMs = 0;
uint32_t stateStartedMs = 0;
uint32_t currentITIMs = 0;
uint32_t lastHeartbeatMs = 0;
uint32_t lastLickMs = 0;
uint32_t lickCount = 0;
bool configured = false;
bool lastLickHigh = false;
bool markerOn = false;
uint8_t completedBlinks = 0;
char lineBuffer[96];
uint8_t lineLength = 0;
bool discardingLine = false;
uint16_t manualOnMs = 300;
uint16_t manualOffMs = 100;
bool manualValveHigh = false;

void logEvent(const __FlashStringHelper *event, uint32_t value) {
  Serial.print(millis());
  Serial.print(',');
  Serial.print(event);
  Serial.print(',');
  Serial.println(value);
}

void safeOutputs() {
  digitalWrite(PIN_VALVE, LOW);
  digitalWrite(PIN_LED, LOW);
  digitalWrite(PIN_TTL, LOW);
  digitalWrite(PIN_BUZZER, LOW);
}

void abortSession(uint8_t reason) {
  bool manual = state == MANUAL_HOLD || state == MANUAL_PULSE;
  safeOutputs();
  manualValveHigh = false;
  state = IDLE;
  configured = false;
  loadedTrials = 0;
  if (manual) {
    logEvent(F("VALVE_OFF"), 0);
    logEvent(F("MANUAL_END"), reason);
  }
  logEvent(F("SESSION_ABORTED"), reason);
}

void protocolError(uint8_t code) {
  // Close physical outputs BEFORE potentially blocking serial output.
  if (state != IDLE) safeOutputs();
  logEvent(F("ERROR"), code);
  if (state != IDLE) abortSession(5);
}

bool trialRewarded() {
  return (rewardBits[trialIndex / 8] & (1U << (trialIndex % 8))) != 0;
}

void startITI() {
  uint16_t seconds = trialIndex == 0 ? initialITISeconds : trialITISeconds[trialIndex];
  currentITIMs = uint32_t(seconds) * 1000UL;
  stateStartedMs = millis();
  state = ITI;
  logEvent(F("ITI_START"), trialIndex + 1);
  logEvent(F("ITI_DURATION_S"), seconds);
}

void advanceTrial() {
  ++trialIndex;
  if (trialIndex >= totalTrials) {
    safeOutputs();
    state = IDLE;
    logEvent(F("SESSION_END"), totalTrials);
  } else {
    startITI();
  }
}

void closeRewardIfDue() {
  if (state != VALVE_OPEN || uint32_t(millis() - stateStartedMs) < valveDurationMs) return;
  digitalWrite(PIN_VALVE, LOW);
  digitalWrite(PIN_TTL, LOW);
  logEvent(F("REWARD_OFF"), trialIndex + 1);
  state = POST_REWARD;
}

// Decimal-only parser: no negative numbers, implicit bases, overflow, or junk.
bool readNumbers(char *remaining, uint32_t *values, uint8_t count) {
  char *cursor = remaining;
  for (uint8_t i = 0; i < count; ++i) {
    char *token = strtok_r(NULL, " \t", &cursor);
    if (token == NULL || *token == '\0') return false;
    uint32_t result = 0;
    for (const char *p = token; *p; ++p) {
      if (*p < '0' || *p > '9') return false;
      uint8_t digit = *p - '0';
      if (result > (UINT32_MAX - digit) / 10UL) return false;
      result = result * 10UL + digit;
    }
    values[i] = result;
  }
  return strtok_r(NULL, " \t", &cursor) == NULL;
}

void handleLine() {
  char *remaining;
  char *command = strtok_r(lineBuffer, " \t", &remaining);
  if (command == NULL) return;
  uint32_t values[7];

  if (strcmp(command, "STOP") == 0) {
    if (!readNumbers(remaining, values, 0)) { protocolError(1); return; }
    abortSession(1);
  } else if (strcmp(command, "PING") == 0) {
    if (!readNumbers(remaining, values, 0)) { protocolError(1); return; }
    lastHeartbeatMs = millis();
    logEvent(F("PONG"), 1);
  } else if (strcmp(command, "HELLO") == 0) {
    if (!readNumbers(remaining, values, 0)) { protocolError(1); return; }
    if (state != IDLE) { protocolError(3); return; }
    logEvent(F("READY"), 1);
  } else if (strcmp(command, "VALVE_CAPS") == 0) {
    if (!readNumbers(remaining, values, 0)) { protocolError(1); return; }
    if (state != IDLE) { protocolError(3); return; }
    logEvent(F("VALVE_CAPS"), 1);
  } else if (strcmp(command, "VALVE_HOLD") == 0 || strcmp(command, "VALVE_PULSE") == 0) {
    if (state != IDLE) { protocolError(3); return; }
    bool pulse = strcmp(command, "VALVE_PULSE") == 0;
    if (!readNumbers(remaining, values, pulse ? 2 : 0)) { protocolError(1); return; }
    if (pulse && (values[0] < 10 || values[0] > 60000 || values[1] < 10 || values[1] > 60000)) {
      protocolError(2); return;
    }
    safeOutputs();
    configured = false;
    loadedTrials = 0;
    if (pulse) { manualOnMs = values[0]; manualOffMs = values[1]; }
    state = pulse ? MANUAL_PULSE : MANUAL_HOLD;
    stateStartedMs = lastHeartbeatMs = millis();
    manualValveHigh = true;
    digitalWrite(PIN_VALVE, HIGH);
    logEvent(F("MANUAL_START"), pulse ? 2 : 1);
    logEvent(F("VALVE_ON"), 0);
  } else if (strcmp(command, "CONFIG") == 0) {
    if (state != IDLE) { protocolError(3); return; }
    if (!readNumbers(remaining, values, 7)) { protocolError(1); return; }
    if (values[0] < 1 || values[0] > MAX_TRIALS ||
        values[1] > 60000 || values[2] < 1 || values[2] > 60000 ||
        values[3] > 60000 || values[3] <= values[1] + values[2] ||
        values[4] < 1 || values[4] > 60000 || values[4] < values[5] ||
        values[5] < 1 || values[5] > 1000 || values[6] > 65535) {
      protocolError(2); return;
    }
    totalTrials = values[0];
    cueDelayMs = values[1];
    cueDurationMs = values[2];
    rewardAtMs = values[3];
    postRewardMs = values[4];
    valveDurationMs = values[5];
    initialITISeconds = values[6];
    loadedTrials = 0;
    memset(rewardBits, 0, sizeof(rewardBits));
    configured = true;
    logEvent(F("CONFIG_OK"), totalTrials);
  } else if (strcmp(command, "TRIAL") == 0) {
    if (state != IDLE) { protocolError(3); return; }
    if (!readNumbers(remaining, values, 3)) { protocolError(1); return; }
    if (!configured || loadedTrials >= totalTrials || values[0] != loadedTrials + 1UL) {
      protocolError(4); return;
    }
    if (values[1] > 65535 || values[2] > 1) { protocolError(2); return; }
    trialITISeconds[loadedTrials] = values[1];
    if (values[2]) rewardBits[loadedTrials / 8] |= 1U << (loadedTrials % 8);
    ++loadedTrials;
    logEvent(F("TRIAL_OK"), loadedTrials);
  } else if (strcmp(command, "START") == 0) {
    if (!readNumbers(remaining, values, 0)) { protocolError(1); return; }
    if (state != IDLE) { protocolError(3); return; }
    if (!configured || loadedTrials != totalTrials) { protocolError(4); return; }
    safeOutputs();
    trialIndex = 0;
    lickCount = 0;
    lastLickHigh = digitalRead(PIN_LICK) == HIGH;
    lastLickMs = millis() - LICK_DEBOUNCE_MS;
    completedBlinks = 0;
    markerOn = false;
    state = START_MARKER;
    stateStartedMs = lastHeartbeatMs = millis();
    logEvent(F("SESSION_START"), totalTrials);
  } else if (strcmp(command, "CUE_ON") == 0 || strcmp(command, "CUE_OFF") == 0) {
    if (!readNumbers(remaining, values, 1)) { protocolError(1); return; }
    bool isOn = strcmp(command, "CUE_ON") == 0;
    if (values[0] != trialIndex + 1UL || (isOn ? state != WAIT_CUE_ON : state != CUE_VISIBLE)) {
      protocolError(6); return;
    }
    uint32_t now = millis();
    if (uint32_t(now - trialStartedMs) >= rewardAtMs) { abortSession(7); return; }
    if (isOn && uint32_t(now - stateStartedMs) >= CUE_ON_TIMEOUT_MS) { abortSession(3); return; }
    if (!isOn && uint32_t(now - stateStartedMs) >= uint32_t(cueDurationMs) + CUE_OFF_GRACE_MS) {
      abortSession(4); return;
    }
    stateStartedMs = now;
    state = isOn ? CUE_VISIBLE : REWARD_DELAY;
    digitalWrite(PIN_TTL, isOn ? HIGH : LOW);
    logEvent(isOn ? F("CUE_ON") : F("CUE_OFF"), trialIndex + 1);
  } else {
    protocolError(1);
  }
}

void handleSerial() {
  // Bounded work per loop keeps timers and licking responsive during input.
  for (uint8_t n = 0; n < 16 && Serial.available(); ++n) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (!discardingLine) {
        lineBuffer[lineLength] = '\0';
        handleLine();
      }
      lineLength = 0;
      discardingLine = false;
    } else if (!discardingLine) {
      if (c < 32 && c != '\t') {
        discardingLine = true;
        protocolError(1);
      } else if (lineLength >= sizeof(lineBuffer) - 1) {
        discardingLine = true;
        protocolError(5);
      } else {
        lineBuffer[lineLength++] = c;
      }
    }
  }
}

void checkLick() {
  bool high = digitalRead(PIN_LICK) == HIGH;
  uint32_t now = millis();
  if (high && !lastLickHigh && uint32_t(now - lastLickMs) >= LICK_DEBOUNCE_MS) {
    lastLickMs = now;
    ++lickCount;
    logEvent(F("LICK"), lickCount);
  }
  lastLickHigh = high;
}

void runSession() {
  uint32_t now = millis();
  if (state != IDLE && uint32_t(now - lastHeartbeatMs) >= HEARTBEAT_TIMEOUT_MS) {
    abortSession(2);
    return;
  }
  if ((state == WAIT_CUE_ON || state == CUE_VISIBLE) &&
      uint32_t(now - trialStartedMs) >= rewardAtMs) {
    abortSession(7);
    return;
  }
  uint32_t elapsed = now - stateStartedMs;
  switch (state) {
    case MANUAL_PULSE:
      if (elapsed >= (manualValveHigh ? manualOnMs : manualOffMs)) {
        manualValveHigh = !manualValveHigh;
        stateStartedMs = now;
        digitalWrite(PIN_VALVE, manualValveHigh ? HIGH : LOW);
        logEvent(manualValveHigh ? F("VALVE_ON") : F("VALVE_OFF"), 0);
      }
      break;
    case MANUAL_HOLD:
      break;
    case START_MARKER:
      if (elapsed >= 500) {
        markerOn = !markerOn;
        stateStartedMs = now;
        digitalWrite(PIN_LED, markerOn ? HIGH : LOW);
        digitalWrite(PIN_TTL, markerOn ? HIGH : LOW);
        logEvent(markerOn ? F("LED_ON") : F("LED_OFF"), completedBlinks + 1);
        if (!markerOn && ++completedBlinks == 3) startITI();
      }
      break;
    case ITI:
      if (elapsed >= currentITIMs) {
        state = TRIAL_LEAD;
        stateStartedMs = trialStartedMs = now;
        logEvent(F("TRIAL_START"), trialIndex + 1);
      }
      break;
    case TRIAL_LEAD:
      if (uint32_t(now - trialStartedMs) >= cueDelayMs) {
        state = WAIT_CUE_ON;
        stateStartedMs = now;
        logEvent(F("CUE_REQUEST"), trialIndex + 1);
      }
      break;
    case WAIT_CUE_ON:
      if (elapsed >= CUE_ON_TIMEOUT_MS) abortSession(3);
      break;
    case CUE_VISIBLE:
      if (elapsed >= uint32_t(cueDurationMs) + CUE_OFF_GRACE_MS) abortSession(4);
      break;
    case REWARD_DELAY:
      if (uint32_t(now - trialStartedMs) >= rewardAtMs) {
        if (trialRewarded()) {
          state = VALVE_OPEN;
          stateStartedMs = now;
          digitalWrite(PIN_VALVE, HIGH);
          digitalWrite(PIN_TTL, HIGH);
          logEvent(F("REWARD_ON"), trialIndex + 1);
        } else {
          logEvent(F("NO_REWARD"), trialIndex + 1);
          state = POST_REWARD;
        }
      }
      break;
    case POST_REWARD:
      if (uint32_t(now - trialStartedMs) >= uint32_t(rewardAtMs) + postRewardMs) {
        logEvent(F("TRIAL_END"), trialIndex + 1);
        advanceTrial();
      }
      break;
    case VALVE_OPEN:
    case IDLE:
      break;
  }
}

void setup() {
  // Preload LOW before switching the output pins to OUTPUT.
  safeOutputs();
  pinMode(PIN_VALVE, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_TTL, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_LICK, INPUT);
  lastLickHigh = digitalRead(PIN_LICK) == HIGH;
  lastLickMs = millis() - LICK_DEBOUNCE_MS;
  Serial.begin(115200);
  logEvent(F("READY"), 1);
}

void loop() {
  closeRewardIfDue();
  handleSerial();
  checkLick();
  runSession();
}
