/*
 * Pavlovian Task - Habituation & CS+/CS- Conditioning
 * -----------------------------------------------------
 * Pins:
 *    6 - Buzzer         (auditory CS during conditioning, driven with tone())
 *                        NOTE: not pin 13 - pin 13 doubles as SPI SCK, which the
 *                        bootloader toggles briefly on every reset, causing an
 *                        audible click through a buzzer wired there.
 *   12 - Solenoid valve (reward delivery)
 *   11 - Lickometer     (digital input, capacitance sensor, HIGH = tongue contact)
 *   10 - LED            (session start marker)
 *    9 - TTL out        (HIGH during LED_ON / REWARD_ON in habituation;
 *                        HIGH during CS_PLUS_ON~OFF / CS_MINUS_ON~OFF,
 *                        CS+ REWARD_ON~OFF, and CS- NONREWARD_ON~OFF in
 *                        conditioning)
 *
 * Schedules (trial order / ITI durations) are no longer generated on-device.
 * A Python script pre-generates them and loads them over serial before each
 * session starts, so every mouse run on a given day can share the exact same
 * schedule. Serial protocol:
 *   'C' -> start loading a conditioning schedule. Followed by TOTAL_TRIALS
 *          comma-separated tokens like "+23,-41,+19,...,-33" (sign = CS+/CS-,
 *          number = ITI seconds before that trial), terminated by '\n'.
 *   'H' -> start loading a habituation schedule. Followed by TOTAL_REWARDS
 *          comma-separated ITI-second values like "15,12,18,...,11",
 *          terminated by '\n'.
 *   '1' -> start CS+/CS- conditioning session using the loaded schedule
 *          (refused if no conditioning schedule has been loaded yet)
 *   '2' -> start habituation session using the loaded schedule
 *          (refused if no habituation schedule has been loaded yet)
 *   '3' -> manual valve priming: pulses the valve on/off repeatedly for
 *          PRIME_TOTAL_DURATION_MS total (continuous open didn't physically
 *          push liquid through the tubing - pulsing does)
 *   '4' -> STOP: abort whatever session/priming is currently running, return to idle
 *
 * Output: one CSV line per event -> "millis,EVENT,value"
 * Intended to be read and logged to CSV by an external Python script.
 *
 * Session start timing: mode 1 and mode 2 both begin with 3 LED/TTL blinks.
 * After the third blink, the Arduino runs a fixed start ITI
 * (START_FIXED_ITI_SECONDS, default 90 s), then immediately starts the first
 * conditioning trial or first habituation reward. Later ITIs come from the
 * loaded schedule. The first loaded schedule ITI is replaced by this fixed
 * start ITI; entries 2..end are used for subsequent trials/rewards.
 *
 * Reward-contingent ITI: after a real reward (habituation REWARD_OFF, or
 * conditioning CS+ REWARD_OFF), the next ITI does not start until the mouse
 * licks at least once (consumes the reward) - a lick during the valve-open
 * pulse itself also counts. CS- (NONREWARD) trials have no reward, so their
 * ITI starts immediately with no lick required.
 */

const int PIN_BUZZER = 6;
const int PIN_VALVE  = 12;
const int PIN_LICK   = 11;
const int PIN_LED    = 10;
const int PIN_TTL    = 9;

// ---- Habituation parameters ----
const unsigned long BLINK_DURATION_MS = 500;   // start-marker LED on/off duration
const int           NUM_START_BLINKS  = 3;
const int           START_FIXED_ITI_SECONDS = 90; // fixed ITI after 3 blinks before first trial/reward
const unsigned long VALVE_OPEN_MS     = 30;    // TODO: calibrate for 20ul reward
const int           TOTAL_REWARDS     = 80;

// ---- Manual priming ('3') - repeated open/close pulses, not one continuous open ----
const unsigned long PRIME_TOTAL_DURATION_MS = 3000; // total priming window
const unsigned long PRIME_PULSE_ON_MS       = 300;  // valve open time per pulse
const unsigned long PRIME_PULSE_OFF_MS      = 100;  // valve closed time per pulse

// ---- Conditioning parameters ----
const unsigned int  CS_PLUS_FREQ_HZ   = 4000;
const unsigned int  CS_MINUS_FREQ_HZ  = 10000;
const unsigned long CUE_DURATION_MS   = 2000;
const unsigned long DELAY_DURATION_MS = 1000;
const int           TRIALS_PER_TYPE   = 50;
const int           TOTAL_TRIALS      = TRIALS_PER_TYPE * 2;

const unsigned long LICK_DEBOUNCE_MS = 50;

enum SessionState {
  IDLE,
  START_MARKER,
  WAITING_FOR_REWARD,
  VALVE_OPEN_STATE,
  MANUAL_VALVE_OPEN,
  COND_ITI,
  COND_CUE,
  COND_DELAY,
  COND_REWARD_VALVE,
  COND_NONREWARD_VALVE,
  WAIT_FOR_LICK
};

enum LickWaitTarget {
  LICK_WAIT_NONE,
  LICK_WAIT_HABITUATION_ITI,
  LICK_WAIT_CONDITIONING_ADVANCE
};

enum StartMarkerTarget {
  START_TARGET_NONE,
  START_TARGET_HABITUATION,
  START_TARGET_CONDITIONING
};

enum ScheduleLoadState {
  SCHED_IDLE,
  SCHED_LOADING_CONDITIONING,
  SCHED_LOADING_HABITUATION
};

SessionState state = IDLE;
LickWaitTarget lickWaitTarget = LICK_WAIT_NONE;
StartMarkerTarget startMarkerTarget = START_TARGET_NONE;

// Habituation state
int blinkCount = 0;
bool ledOn = false;
unsigned long stateTimer = 0;
int rewardCount = 0;
unsigned long nextRewardInterval = 0;

// Conditioning state
bool trialIsCSPlus[TOTAL_TRIALS];
int trialITISeconds[TOTAL_TRIALS];
int trialIndex = 0;
unsigned long nextTrialInterval = 0;

// Habituation ITI schedule (seconds before each of the 80 rewards)
int rewardITISeconds[TOTAL_REWARDS];

// Schedule loading (from Python, over serial - see protocol note above)
ScheduleLoadState scheduleLoadState = SCHED_IDLE;
int scheduleEntryIndex = 0;   // number of entries actually written into the arrays (capped at array size)
int scheduleEntriesSeen = 0;  // true number of entries received, uncapped - used to catch "too many"
int scheduleEntryNumber = 0;
bool scheduleEntryIsPlus = true;
bool conditioningScheduleLoaded = false;
bool habituationScheduleLoaded = false;

// Lick monitoring (always active, regardless of session state)
bool lastLickState = LOW;
unsigned long lastLickTime = 0;
int lickCount = 0;

// True once a lick has been detected since the current reward's REWARD_ON,
// so a lick during the valve-open pulse itself (not just after it closes)
// still counts toward starting the next ITI.
bool rewardLickSatisfied = false;

// Manual priming pulse state
bool primeValveOn = false;
unsigned long primeSessionStart = 0;
unsigned long primePulseTimer = 0;

void setup() {
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_VALVE, OUTPUT);
  pinMode(PIN_LICK, INPUT);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_TTL, OUTPUT);

  digitalWrite(PIN_BUZZER, LOW);
  digitalWrite(PIN_VALVE, LOW);
  digitalWrite(PIN_LED, LOW);
  digitalWrite(PIN_TTL, LOW);

  Serial.begin(115200);
  Serial.println("Timestamp_ms,Event,Value");
  Serial.println(
    "Ready. Python controls this Arduino. Use Python commands: 1=conditioning, 2=habituation, 3=priming, 4=STOP."
);
}

void loop() {
  handleSerialCommand();
  checkLick();

  switch (state) {
    case IDLE:
      break;

    case START_MARKER:
      runStartMarker();
      break;

    case WAITING_FOR_REWARD:
      if (millis() - stateTimer >= nextRewardInterval) {
        logEvent("ITI_END", rewardCount + 1);
        openValve(VALVE_OPEN_STATE, "REWARD_ON", true);
      }
      break;

    case VALVE_OPEN_STATE:
      if (millis() - stateTimer >= VALVE_OPEN_MS) {
        digitalWrite(PIN_VALVE, LOW);
        digitalWrite(PIN_TTL, LOW);
        rewardCount++;
        logEvent("REWARD_OFF", rewardCount);

        if (rewardCount >= TOTAL_REWARDS) {
          state = IDLE;
          logEvent("SESSION_END", rewardCount);
        } else if (rewardLickSatisfied) {
          startHabituationITI(false);
        } else {
          state = WAIT_FOR_LICK;
          lickWaitTarget = LICK_WAIT_HABITUATION_ITI;
        }
      }
      break;

    case MANUAL_VALVE_OPEN:
      if (millis() - primeSessionStart >= PRIME_TOTAL_DURATION_MS) {
        digitalWrite(PIN_VALVE, LOW);
        logEvent("MANUAL_VALVE_OFF", 0);
        state = IDLE;
      } else {
        unsigned long phaseDuration = primeValveOn ? PRIME_PULSE_ON_MS : PRIME_PULSE_OFF_MS;
        if (millis() - primePulseTimer >= phaseDuration) {
          primeValveOn = !primeValveOn;
          digitalWrite(PIN_VALVE, primeValveOn ? HIGH : LOW);
          primePulseTimer = millis();
        }
      }
      break;

    case COND_ITI:
      if (millis() - stateTimer >= nextTrialInterval) {
        logEvent("ITI_END", trialIndex + 1);
        startTrialCue();
      }
      break;

    case COND_CUE:
      if (millis() - stateTimer >= CUE_DURATION_MS) {
        noTone(PIN_BUZZER);
        digitalWrite(PIN_TTL, LOW);
        logEvent(trialIsCSPlus[trialIndex] ? "CS_PLUS_OFF" : "CS_MINUS_OFF", trialIndex + 1);

        state = COND_DELAY;
        stateTimer = millis();
      }
      break;

    case COND_DELAY:
      if (millis() - stateTimer >= DELAY_DURATION_MS) {
        if (trialIsCSPlus[trialIndex]) {
          state = COND_REWARD_VALVE;
          stateTimer = millis();
          rewardLickSatisfied = false;
          digitalWrite(PIN_VALVE, HIGH);
          digitalWrite(PIN_TTL, HIGH);
          logEvent("REWARD_ON", rewardCount + 1);
        } else {
          state = COND_NONREWARD_VALVE;
          stateTimer = millis();
          digitalWrite(PIN_TTL, HIGH);
          logEvent("NONREWARD_ON", trialIndex + 1);
        }
      }
      break;

    case COND_REWARD_VALVE:
      if (millis() - stateTimer >= VALVE_OPEN_MS) {
        digitalWrite(PIN_VALVE, LOW);
        digitalWrite(PIN_TTL, LOW);
        rewardCount++;
        logEvent("REWARD_OFF", rewardCount);
        if (rewardLickSatisfied) {
          advanceTrial();
        } else {
          state = WAIT_FOR_LICK;
          lickWaitTarget = LICK_WAIT_CONDITIONING_ADVANCE;
        }
      }
      break;

    case COND_NONREWARD_VALVE:
      if (millis() - stateTimer >= VALVE_OPEN_MS) {
        digitalWrite(PIN_TTL, LOW);
        logEvent("NONREWARD_OFF", trialIndex + 1);
        advanceTrial();
      }
      break;

    case WAIT_FOR_LICK:
      break; // handled in checkLick() once a lick is detected
  }
}

void handleSerialCommand() {
  if (!Serial.available()) return;
  char c = Serial.read();

  if (scheduleLoadState != SCHED_IDLE) {
    processScheduleChar(c);
    return;
  }

  if (c == 'C') {
    if (state != IDLE) {
      Serial.println("# Ignored 'C': cannot load schedule while a session is active.");
      return;
    }
    scheduleLoadState = SCHED_LOADING_CONDITIONING;
    scheduleEntryIndex = 0;
    scheduleEntriesSeen = 0;
    scheduleEntryNumber = 0;
    scheduleEntryIsPlus = true;
    conditioningScheduleLoaded = false;
    Serial.println("# Receiving conditioning schedule...");
  } else if (c == 'H') {
    if (state != IDLE) {
      Serial.println("# Ignored 'H': cannot load schedule while a session is active.");
      return;
    }
    scheduleLoadState = SCHED_LOADING_HABITUATION;
    scheduleEntryIndex = 0;
    scheduleEntriesSeen = 0;
    scheduleEntryNumber = 0;
    habituationScheduleLoaded = false;
    Serial.println("# Receiving habituation schedule...");
  } else if (c == '1') {
    if (state != IDLE) {
      Serial.println("# Ignored '1': session already running.");
    } else if (!conditioningScheduleLoaded) {
      Serial.println("# Ignored '1': no conditioning schedule loaded (send 'C' schedule first).");
    } else {
      startConditioningSession();
    }
  } else if (c == '2') {
    if (state != IDLE) {
      Serial.println("# Ignored '2': session already running.");
    } else if (!habituationScheduleLoaded) {
      Serial.println("# Ignored '2': no habituation schedule loaded (send 'H' schedule first).");
    } else {
      startHabituationSession();
    }
  } else if (c == '3') {
    if (state == IDLE) {
      startPriming();
    } else {
      Serial.println("# Ignored '3': cannot manually trigger while session is active.");
    }
  } else if (c == '4') {
    if (state != IDLE) {
      abortSession();
    } else {
      Serial.println("# Ignored '4': nothing running.");
    }
  }
}

// Called once per incoming byte while a schedule is being received. Runs
// every loop() iteration (no blocking reads), so the small hardware serial
// buffer never has a chance to overflow.
void processScheduleChar(char c) {
  if (scheduleLoadState == SCHED_LOADING_CONDITIONING) {
    if (c == '+' || c == '-') {
      scheduleEntryIsPlus = (c == '+');
      scheduleEntryNumber = 0;
    } else if (c >= '0' && c <= '9') {
      scheduleEntryNumber = scheduleEntryNumber * 10 + (c - '0');
    } else if (c == ',' || c == '\n') {
      if (scheduleEntryIndex < TOTAL_TRIALS) {
        trialIsCSPlus[scheduleEntryIndex] = scheduleEntryIsPlus;
        trialITISeconds[scheduleEntryIndex] = scheduleEntryNumber;
        scheduleEntryIndex++;
      }
      scheduleEntriesSeen++;
      scheduleEntryNumber = 0;
      scheduleEntryIsPlus = true;

      if (c == '\n') {
        if (scheduleEntriesSeen == TOTAL_TRIALS) {
          conditioningScheduleLoaded = true;
          Serial.println("# Conditioning schedule loaded.");
        } else {
          Serial.print("# ERROR: conditioning schedule had ");
          Serial.print(scheduleEntriesSeen);
          Serial.print(" entries, expected ");
          Serial.println(TOTAL_TRIALS);
        }
        scheduleLoadState = SCHED_IDLE;
        scheduleEntryIndex = 0;
        scheduleEntriesSeen = 0;
      }
    }
    // any other character (e.g. stray '\r') is ignored
  } else if (scheduleLoadState == SCHED_LOADING_HABITUATION) {
    if (c >= '0' && c <= '9') {
      scheduleEntryNumber = scheduleEntryNumber * 10 + (c - '0');
    } else if (c == ',' || c == '\n') {
      if (scheduleEntryIndex < TOTAL_REWARDS) {
        rewardITISeconds[scheduleEntryIndex] = scheduleEntryNumber;
        scheduleEntryIndex++;
      }
      scheduleEntriesSeen++;
      scheduleEntryNumber = 0;

      if (c == '\n') {
        if (scheduleEntriesSeen == TOTAL_REWARDS) {
          habituationScheduleLoaded = true;
          Serial.println("# Habituation schedule loaded.");
        } else {
          Serial.print("# ERROR: habituation schedule had ");
          Serial.print(scheduleEntriesSeen);
          Serial.print(" entries, expected ");
          Serial.println(TOTAL_REWARDS);
        }
        scheduleLoadState = SCHED_IDLE;
        scheduleEntryIndex = 0;
        scheduleEntriesSeen = 0;
      }
    }
  }
}

void abortSession() {
  noTone(PIN_BUZZER);
  digitalWrite(PIN_VALVE, LOW);
  digitalWrite(PIN_LED, LOW);
  digitalWrite(PIN_TTL, LOW);
  logEvent("SESSION_ABORTED", 0);
  state = IDLE;
  lickWaitTarget = LICK_WAIT_NONE;
  startMarkerTarget = START_TARGET_NONE;
  rewardLickSatisfied = false;
}

// ---------------- Habituation ----------------

void startHabituationSession() {
  rewardCount = 0;
  lickCount = 0;
  blinkCount = 0;
  ledOn = false;
  digitalWrite(PIN_LED, LOW);
  digitalWrite(PIN_TTL, LOW);

  startMarkerTarget = START_TARGET_HABITUATION;
  state = START_MARKER;
  stateTimer = millis();
  logEvent("SESSION_START", TOTAL_REWARDS);
}

void runStartMarker() {
  if (millis() - stateTimer < BLINK_DURATION_MS) return;

  stateTimer = millis();
  ledOn = !ledOn;
  digitalWrite(PIN_LED, ledOn ? HIGH : LOW);
  digitalWrite(PIN_TTL, ledOn ? HIGH : LOW);
  logEvent(ledOn ? "LED_ON" : "LED_OFF", blinkCount + 1);

  if (!ledOn) {
    blinkCount++;
    if (blinkCount >= NUM_START_BLINKS) {
      if (startMarkerTarget == START_TARGET_HABITUATION) {
        startHabituationITI(true);
      } else if (startMarkerTarget == START_TARGET_CONDITIONING) {
        startConditioningITI(true);
      } else {
        state = IDLE;
      }
      startMarkerTarget = START_TARGET_NONE;
    }
  }
}

void startHabituationITI(bool useFixedStartITI) {
  state = WAITING_FOR_REWARD;
  int itiSeconds = useFixedStartITI ? START_FIXED_ITI_SECONDS : rewardITISeconds[rewardCount];
  nextRewardInterval = (unsigned long)itiSeconds * 1000UL;
  stateTimer = millis();
  if (useFixedStartITI) logEvent("INITIAL_FIXED_ITI", rewardCount + 1);
  logEvent("ITI_START", rewardCount + 1);
  logEvent("ITI_DURATION_S", itiSeconds);
}

void openValve(SessionState nextState, const char *eventName, bool driveTTL) {
  state = nextState;
  stateTimer = millis();
  rewardLickSatisfied = false;
  digitalWrite(PIN_VALVE, HIGH);
  if (driveTTL) digitalWrite(PIN_TTL, HIGH);
  logEvent(eventName, rewardCount + 1);
}

void startPriming() {
  state = MANUAL_VALVE_OPEN;
  primeSessionStart = millis();
  primePulseTimer = millis();
  primeValveOn = true;
  digitalWrite(PIN_VALVE, HIGH);
  logEvent("MANUAL_VALVE_ON", 0);
}

// ---------------- Conditioning ----------------

void startConditioningSession() {
  trialIndex = 0;
  rewardCount = 0;
  lickCount = 0;
  blinkCount = 0;
  ledOn = false;
  digitalWrite(PIN_LED, LOW);
  digitalWrite(PIN_TTL, LOW);

  startMarkerTarget = START_TARGET_CONDITIONING;
  state = START_MARKER;
  stateTimer = millis();
  logEvent("SESSION_START", TOTAL_TRIALS);
}

void startConditioningITI(bool useFixedStartITI) {
  state = COND_ITI;
  int itiSeconds = useFixedStartITI ? START_FIXED_ITI_SECONDS : trialITISeconds[trialIndex];
  nextTrialInterval = (unsigned long)itiSeconds * 1000UL;
  stateTimer = millis();
  if (useFixedStartITI) logEvent("INITIAL_FIXED_ITI", trialIndex + 1);
  logEvent("ITI_START", trialIndex + 1);
  logEvent("ITI_DURATION_S", itiSeconds);
}

void startTrialCue() {
  bool isPlus = trialIsCSPlus[trialIndex];
  tone(PIN_BUZZER, isPlus ? CS_PLUS_FREQ_HZ : CS_MINUS_FREQ_HZ);
  digitalWrite(PIN_TTL, HIGH);

  state = COND_CUE;
  stateTimer = millis();
  logEvent(isPlus ? "CS_PLUS_ON" : "CS_MINUS_ON", trialIndex + 1);
}

void advanceTrial() {
  trialIndex++;
  if (trialIndex >= TOTAL_TRIALS) {
    state = IDLE;
    logEvent("SESSION_END", TOTAL_TRIALS);
  } else {
    startConditioningITI(false);
  }
}

// ---------------- Shared ----------------

void checkLick() {
  bool currentLickState = digitalRead(PIN_LICK);
  if (currentLickState == HIGH && lastLickState == LOW &&
      (millis() - lastLickTime > LICK_DEBOUNCE_MS)) {
    lickCount++;
    logEvent("LICK", lickCount);
    lastLickTime = millis();

    if (state == VALVE_OPEN_STATE || state == COND_REWARD_VALVE) {
      // Lick arrived while the reward valve pulse was still running - it still
      // counts; the ITI/next-trial transition happens once REWARD_OFF fires.
      rewardLickSatisfied = true;
    } else if (state == WAIT_FOR_LICK) {
      LickWaitTarget target = lickWaitTarget;
      lickWaitTarget = LICK_WAIT_NONE;
      if (target == LICK_WAIT_HABITUATION_ITI) {
        startHabituationITI(false);
      } else if (target == LICK_WAIT_CONDITIONING_ADVANCE) {
        advanceTrial();
      }
    }
  }
  lastLickState = currentLickState;
}

void logEvent(const char *eventName, int value) {
  Serial.print(millis());
  Serial.print(",");
  Serial.print(eventName);
  Serial.print(",");
  Serial.println(value);
}
