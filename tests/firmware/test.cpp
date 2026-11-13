#include <Arduino.h>
#include <cassert>
#include <iostream>
uint32_t fakeNow=0;
int pins[20] = {};
FakeSerial Serial;
#include "../../arduino/HEADFIXED_ARDUINO/HEADFIXED_ARDUINO.ino"

void command(const std::string& s) {
 for (char c:s+"\n") Serial.input.push_back(c);
 while (Serial.available()) loop();
}
void tick(uint32_t duration, bool heartbeat=true) {
 for (uint32_t i=0;i<duration;i++) {
  ++fakeNow;
  if (heartbeat && fakeNow % 500 == 0) command("PING");
  loop();
  assert(pins[8]==LOW);
 }
}
bool has(const std::string &s) {return Serial.output.find(s)!=std::string::npos;}
void reset() {
 command("STOP"); pins[11]=0; loop();
 Serial.output.clear();
}
void configure(unsigned n=1, unsigned iti=0, unsigned initial=0) {
 command("CONFIG "+std::to_string(n)+" 1000 2000 9000 4000 30 "+std::to_string(initial));
 for(unsigned i=1;i<=n;i++) command("TRIAL "+std::to_string(i)+" "+std::to_string(iti)+" 1");
 command("START");
}
void until(SessionState target) {
 unsigned elapsed=0;
 while(state!=target && elapsed++ < 100000) tick(1);
 assert(state==target);
}
void lick() {pins[11]=0;loop();pins[11]=1;loop();pins[11]=0;loop();}
void toCue() {until(WAIT_CUE_ON); command("CUE_ON 1");}
void toReward() {toCue();tick(2000);command("CUE_OFF 1");until(VALVE_OPEN);}
void assertSafe(){assert(pins[12]==0 && pins[9]==0 && pins[10]==0 && pins[6]==0 && pins[7]==0 && pins[8]==0);}
void configureTriggers(bool rewarded=true, unsigned count=1, unsigned lead=100, unsigned width=20) {
 command("CONFIG "+std::to_string(count)+" 1000 2000 6000 4000 30 0");
 command("TRIGGERS "+std::to_string(lead)+" "+std::to_string(lead)+" "+std::to_string(width));
 for(unsigned i=1;i<=count;i++)command("TRIAL "+std::to_string(i)+" 0 "+std::to_string(rewarded));
 command("START");
}
int main() {
 setup(); assert(has("0,READY,1\n")); assertSafe();
 command("START"); assert(has(",ERROR,4\n")); assert(state==IDLE);
 reset();configure(2,33,0);auto started=fakeNow;
 tick(499);assert(pins[10]==0);
 tick(1);assert(pins[10]==1);
 tick(2499);assert(state==START_MARKER);
 tick(1);assert(state==ITI || state==TRIAL_LEAD);assert(fakeNow-started==3000);
 until(TRIAL_LEAD);auto trial1=trialStartedMs;
 tick(999);assert(state==TRIAL_LEAD);tick(1);assert(state==WAIT_CUE_ON);assert(pins[9]==0);
 assert(fakeNow-trial1==1000);
 command("CUE_ON 1");assert(pins[9]==1);assert(pins[12]==0);
 tick(2000);command("CUE_OFF 1");assert(pins[9]==0);assert(fakeNow-trial1==3000);
 tick(5999);assert(pins[12]==0);
 tick(1);assert(pins[12]==1);auto opened=fakeNow;assert(opened-trial1==9000);
 tick(29);assert(pins[12]==1);
 tick(1);assert(pins[12]==0);assert(state==WAIT_REWARD_LICK);assert(fakeNow-opened==30);
 tick(3969);assert(state==WAIT_REWARD_LICK);
 tick(1);assert(state==WAIT_REWARD_LICK);lick();assert(state==ITI);assert(trialIndex==1);assert(fakeNow-trial1==13000);
 tick(32999);assert(state==ITI);
 tick(1);assert(state==TRIAL_LEAD);assert(trialStartedMs-trial1==46000);
 until(WAIT_CUE_ON);command("CUE_ON 2");tick(2000);command("CUE_OFF 2");until(VALVE_OPEN);
 auto trial2=trialStartedMs;lick();tick(29);assert(state==VALVE_OPEN);
 tick(1);assert(state==IDLE);assert(fakeNow-trial2==9030);assert(has(",TRIAL_END,2\n"));assert(has(",SESSION_END,2\n"));assertSafe();
 std::cout<<"PASS marker, cue1..3s, reward9s, valve30ms, lick ends trial at13s, next start46s, valve-time lick ends final trial at9030ms\n";
 reset();configure();toCue();tick(50);pins[11]=1;loop();pins[11]=0;loop();
 auto licks=lickCount;tick(49);pins[11]=1;loop();assert(lickCount==licks);
 pins[11]=0;loop();tick(1);pins[11]=1;loop();assert(lickCount==licks+1);
 tick(1900);command("CUE_OFF 1");until(VALVE_OPEN);tick(4000);assert(state==WAIT_REWARD_LICK);
 assert(!rewardLickSatisfied);lick();assert(state==IDLE);
 std::cout<<"PASS rising-edge50ms debounce; pre-reward lick and held HIGH do not finish trial\n";
 reset();configure();tick(2000,false);assert(state==IDLE);assert(has(",SESSION_ABORTED,2\n"));assertSafe();
 reset();configure();until(WAIT_CUE_ON);tick(2000);assert(state==IDLE);assert(has(",SESSION_ABORTED,3\n"));assertSafe();
 reset();configure();toCue();tick(3000);assert(state==IDLE);assert(has(",SESSION_ABORTED,4\n"));assertSafe();
 std::cout<<"PASS heartbeat loss and missing cue acknowledgements abort safely\n";
 reset();configure();until(WAIT_CUE_ON);tick(99);command("CUE_ON 1");assert(state==CUE_VISIBLE);
 for (unsigned lateAckMs : {100U, 101U}) {
  reset();configure();until(WAIT_CUE_ON);
  // Advance without loop() so the command handler itself must reject the
  // late acknowledgement, even before the regular timeout check runs.
  fakeNow += lateAckMs;
  command("CUE_ON 1");assert(state==IDLE);assert(has(",SESSION_ABORTED,3\n"));
  tick(9000);assert(!has(",REWARD_ON,"));assertSafe();
 }
 std::cout<<"PASS cue onset accepts99ms but100/101ms ACKs abort without reward\n";
 reset();configure();toReward();command("STOP");assert(state==IDLE);assertSafe();
 reset();configure();toReward();command("CUE_OFF 2");assert(state==IDLE);assert(has(",ERROR,6\n"));assert(has(",SESSION_ABORTED,5\n"));assertSafe();
 std::cout<<"PASS STOP and invalid command close valve immediately\n";
 reset();command("CONFIG 1 1000 2000 9000 4000 30 0");command("TRIAL 1 0 0");command("START");
 toCue();tick(2000);command("CUE_OFF 1");auto nonrewardStart=trialStartedMs;until(IDLE);
 assert(fakeNow-nonrewardStart==13000);assert(has(",NO_REWARD,1\n"));assert(!has(",REWARD_ON,"));assertSafe();
 std::cout<<"PASS optional nonreward trial maintains same fixed trial duration\n";
 reset();command("CONFIG 201 1000 2000 9000 4000 30 0");assert(has(",ERROR,2\n"));assert(!configured);
 command("CONFIG 1 -1 2000 9000 4000 30 0");assert(has(",ERROR,1\n"));assert(!configured);
 command("CONFIG 1 4294967296 2000 9000 4000 30 0");assert(!configured);
 command(std::string(100,'X'));assert(has(",ERROR,5\n"));command("HELLO");assert(has(",READY,1\n"));
 command("CONFIG 1 1000 2000 3000 4000 30 0");assert(!configured);
 command("CONFIG 1 1000 2000 9000 29 30 0");assert(!configured);
 command("CONFIG 200 0 59999 60000 60000 1000 65535");assert(configured);
 for(unsigned i=1;i<=200;i++)command("TRIAL "+std::to_string(i)+" 65535 1");
 assert(loadedTrials==200);assert(trialITISeconds[199]==65535);assert(rewardBits[24]==255);
 std::cout<<"PASS parser, input overflow recovery, bounds, full200-trial load\n";
 reset();fakeNow=UINT32_MAX-1000;configure();toReward();tick(4000);assert(state==WAIT_REWARD_LICK);lick();assert(state==IDLE);assertSafe();
 std::cout<<"PASS millis rollover during active session\n";
 reset();command("CONFIG 1 0 1000 1001 4000 30 0");command("TRIAL 1 0 1");command("START");
 until(WAIT_CUE_ON);command("CUE_ON 1");until(IDLE);assert(has(",SESSION_ABORTED,7\n"));assertSafe();
 std::cout<<"PASS absolute reward deadline withoutOFF aborts instead of late delivery\n";
 reset();command("VALVE_CAPS");assert(has(",VALVE_CAPS,1\n"));assertSafe();
 command("VALVE_HOLD");assert(state==MANUAL_HOLD);assert(pins[12]==HIGH);
 assert(pins[9]==LOW && pins[10]==LOW && pins[6]==LOW);
 tick(5000);assert(pins[12]==HIGH);assert(!has(",REWARD_ON,"));
 command("STOP");assert(state==IDLE);assertSafe();assert(has(",MANUAL_END,1\n"));
 std::cout<<"PASS manual hold stays open with heartbeat and STOP closes without cue/TTL\n";
 reset();command("VALVE_PULSE 300 100");assert(state==MANUAL_PULSE);
 for(unsigned cycle=0;cycle<5;cycle++) {
  assert(pins[12]==HIGH);tick(299);assert(pins[12]==HIGH);
  tick(1);assert(pins[12]==LOW);tick(99);assert(pins[12]==LOW);
  tick(1);assert(pins[12]==HIGH);
 }
 command("STOP");assertSafe();
 reset();command("VALVE_PULSE 30 100");tick(30);assert(pins[12]==LOW);
 command("STOP");tick(500);assertSafe();
 std::cout<<"PASS pulse widths and STOP during either phase prevent further opening\n";
 for(const std::string mode : {"VALVE_HOLD", "VALVE_PULSE 300 100"}) {
  reset();command(mode);tick(2000,false);assert(state==IDLE);assertSafe();
  assert(has(",SESSION_ABORTED,2\n"));
 }
 reset();command("VALVE_PULSE 0 100");assert(state==IDLE);assertSafe();assert(has(",ERROR,2\n"));
 reset();command("VALVE_PULSE 300 60001");assert(state==IDLE);assertSafe();
 reset();configure();command("VALVE_HOLD");assert(state==IDLE);assertSafe();assert(has(",ERROR,3\n"));
 reset();command("VALVE_HOLD");command("START");assert(state==IDLE);assertSafe();
 std::cout<<"PASS manual watchdog, invalid timings, and conditioning/manual exclusion\n";
 reset();fakeNow=UINT32_MAX-50;command("VALVE_PULSE 300 100");tick(300);assert(pins[12]==LOW);
 tick(100);assert(pins[12]==HIGH);command("STOP");assertSafe();
 std::cout<<"PASS manual pulse timing across millis rollover\n";
 reset();configure(100,20,90);auto sessionStart=fakeNow;unsigned cueCount=0;
 while(state!=IDLE && uint32_t(fakeNow-sessionStart)<5000000) {
  if(state==WAIT_CUE_ON) {command("CUE_ON "+std::to_string(trialIndex+1));++cueCount;}
  if(state==CUE_VISIBLE && uint32_t(fakeNow-stateStartedMs)>=cueDurationMs)command("CUE_OFF "+std::to_string(trialIndex+1));
  if(state==WAIT_REWARD_LICK) lick();
  if(state!=IDLE) tick(1);
 }
 assert(state==IDLE);assert(cueCount==100);assert(lickCount==100);assert(fakeNow-sessionStart==2976000);
 assert(has(",REWARD_ON,100\n") && has(",TRIAL_END,100\n") && has(",SESSION_END,100\n"));assertSafe();
 std::cout<<"PASS full100-trial session with100 post-reward licks and20s ITIs finishes in2976s\n";
 reset();configureTriggers(true,2);
 tick(2999);assert(pins[7]==LOW && pins[8]==LOW);until(TRIAL_LEAD);
 for(unsigned trial=1;trial<=2;trial++) {
  auto start=trialStartedMs;
  tick(899);assert(pins[7]==LOW && pins[8]==LOW);
  tick(1);assert(pins[7]==HIGH && pins[8]==LOW && pins[12]==LOW);
  assert(has(std::to_string(uint32_t(start+900))+",CUE_TRIGGER_ON,"+std::to_string(trial)+"\n"));
  tick(19);assert(pins[7]==HIGH);tick(1);assert(pins[7]==LOW);
  tick(80);assert(state==WAIT_CUE_ON);
  command("CUE_ON "+std::to_string(trial));tick(2000);command("CUE_OFF "+std::to_string(trial));
  tick(2899);assert(pins[7]==LOW);tick(1);assert(pins[7]==HIGH && pins[12]==LOW);
  assert(has(std::to_string(uint32_t(start+5900))+",REWARD_TRIGGER_ON,"+std::to_string(trial)+"\n"));
  tick(19);assert(pins[7]==HIGH);tick(1);assert(pins[7]==LOW);
  tick(80);assert(state==VALVE_OPEN && pins[12]==HIGH);assert(fakeNow-start==6000);
  tick(30);assert(state==WAIT_REWARD_LICK);lick();assertSafe();
  if(trial==1)until(TRIAL_LEAD);
 }
 assert(state==IDLE);
 std::cout<<"PASS shared D7 pulses100ms before cue/reward,20ms wide, reset each trial\n";
 reset();configureTriggers(false);toCue();tick(2000);command("CUE_OFF 1");until(IDLE);
 assert(has(",CUE_TRIGGER_ON,1\n"));assert(!has(",REWARD_TRIGGER_ON,"));assertSafe();
 reset();configure();toReward();tick(4000);lick();assert(!has("TRIGGER_ON"));assertSafe();
 reset();command("VALVE_HOLD");tick(3000);command("STOP");assert(!has("TRIGGER_ON"));assertSafe();
 std::cout<<"PASS no reward trigger for omission; legacy CONFIG and manual valve have no triggers\n";
 for(bool reward : {false,true}) {
  reset();configureTriggers();until(TRIAL_LEAD);
  if(reward) {toCue();tick(2000);command("CUE_OFF 1");tick(2900);} else tick(900);
  assert(pins[7]==HIGH);command("STOP");assertSafe();tick(10000);assertSafe();
  assert(!has(",REWARD_ON,"));
 }
 reset();configureTriggers();until(TRIAL_LEAD);tick(900);lastHeartbeatMs=fakeNow-2000;
 loop();assert(state==IDLE);assertSafe();assert(has(",SESSION_ABORTED,2\n"));
 reset();configureTriggers();until(TRIAL_LEAD);tick(900);command("BAD");assertSafe();assert(state==IDLE);
 std::cout<<"PASS STOP, watchdog and protocol error clear active trigger outputs\n";
 reset();command("TRIGGERS 100 100 20");assert(has(",ERROR,4\n"));
 command("CONFIG 1 1000 2000 6000 4000 30 0");
 for(const std::string args : {"1001 100 20", "100 3001 20", "100 100 0", "100 100 1001", "-1 100 20"}) {
  command("TRIGGERS "+args);assert(!triggersEnabled);
 }
 command("TRIGGERS 100 100 20");assert(triggersEnabled);
 command("CONFIG 1 1000 2000 6000 4000 30 0");assert(!triggersEnabled);
 reset();configureTriggers();until(TRIAL_LEAD);fakeNow+=1000;command("PING");
 assert(state==IDLE);assert(has(",SESSION_ABORTED,8\n"));assert(!has(",CUE_REQUEST,"));assertSafe();
 reset();configureTriggers();toCue();tick(2000);command("CUE_OFF 1");tick(2800);
 fakeNow+=200;command("PING");assert(state==IDLE);assert(has(",SESSION_ABORTED,8\n"));
 assert(!has(",REWARD_ON,"));assertSafe();
 std::cout<<"PASS trigger bounds, CONFIG resets enable, missed pre-event markers abort\n";
 reset();fakeNow=UINT32_MAX-3909;configureTriggers();until(TRIAL_LEAD);tick(900);
 assert(pins[7]==HIGH);tick(20);assert(pins[7]==LOW);until(WAIT_CUE_ON);
 command("CUE_ON 1");tick(2000);command("CUE_OFF 1");tick(2900);
 assert(pins[7]==HIGH);tick(20);assert(pins[7]==LOW);until(WAIT_REWARD_LICK);lick();assert(state==IDLE);assertSafe();
 reset();configureTriggers(true,1,0);toCue();assert(pins[7]==HIGH);
 tick(2000);command("CUE_OFF 1");until(VALVE_OPEN);assert(pins[7]==HIGH);
 assert(Serial.output.find(",REWARD_TRIGGER_ON,") < Serial.output.find(",REWARD_ON,"));
 tick(4000);lick();assertSafe();
 std::cout<<"PASS trigger pulse expiry across millis rollover and zero-lead event ordering\n";
 reset();command("CONFIG 2 1000 2000 6000 30 30 0");command("TRIGGERS 100 100 1000");
 command("TRIAL 1 0 1");command("TRIAL 2 0 1");command("START");toReward();
 assert(pins[7]==HIGH);lick();tick(30);assert(state==ITI);assertSafe();
 until(TRIAL_LEAD);assertSafe();command("STOP");
 std::cout<<"PASS trial end truncates long trigger pulses before the next trial\n";
 reset();command("CONFIG 1 1000 10 2000 4000 30 0");
 command("TRIGGERS 0 990 20");assert(!triggersEnabled); // Overlap.
 command("TRIGGERS 0 990 10");assert(!triggersEnabled); // No LOW gap.
 command("TRIGGERS 0 990 9");assert(triggersEnabled);assert(has(",TRIGGERS_OK,2\n"));
 command("TRIAL 1 0 1");command("START");until(WAIT_CUE_ON);
 command("CUE_ON 1");tick(10);command("CUE_OFF 1");assert(pins[7]==HIGH && pins[8]==LOW);
 tick(9);assert(pins[7]==LOW);command("STOP");assertSafe();
 // A late cue trigger can overlap despite a valid nominal schedule.
 reset();command("CONFIG 1 1000 10 2000 4000 30 0");command("TRIGGERS 100 990 105");
 command("TRIAL 1 0 1");command("START");until(TRIAL_LEAD);fakeNow+=999;command("PING");
 assert(pins[7]==HIGH);tick(1);command("CUE_ON 1");tick(10);command("CUE_OFF 1");
 assert(state==IDLE);assert(has(",SESSION_ABORTED,8\n"));assertSafe();
 std::cout<<"PASS shared trigger requires a LOW gap and aborts if delayed pulses overlap\n";
 reset();command("TTL_CAPS");assert(has(",TTL_CAPS,1\n"));assertSafe();
 for(unsigned width : {1U,20U,100U,1000U}) {
  command("TTL_PULSE "+std::to_string(width));assert(state==TTL_TEST);
  assert(pins[7]==HIGH && pins[12]==LOW && pins[9]==LOW && pins[10]==LOW && pins[6]==LOW);
  tick(width-1);assert(pins[7]==HIGH);tick(1);assert(state==IDLE);assertSafe();
 }
 assert(has(",TTL_ON,1\n") && has(",TTL_OFF,1\n"));
 assert(!has(",REWARD_ON,") && !has(",CUE_REQUEST,"));
 std::cout<<"PASS standalone D7 pulse widths1/20/100/1000ms without valve/cue/LED/D9\n";
 reset();command("TTL_PULSE 1000");tick(10);command("STOP");assertSafe();tick(2000);assertSafe();
 reset();command("TTL_PULSE 20");fakeNow+=2000;loop();assertSafe();assert(state==IDLE);
 reset();fakeNow=UINT32_MAX-10;command("TTL_PULSE 20");tick(20);assertSafe();assert(state==IDLE);
 std::cout<<"PASS TTL-only STOP, host disappearance and millis rollover return LOW\n";
 for(const std::string args : {"0", "1001", "-1", "20 30"}) {
  reset();command("TTL_PULSE "+args);assert(state==IDLE);assertSafe();
 }
 reset();configure();command("TTL_PULSE 20");assert(state==IDLE);assertSafe();assert(!has(",TTL_ON,"));
 reset();command("VALVE_HOLD");command("TTL_PULSE 20");assertSafe();assert(!has(",TTL_ON,"));
 reset();command("TTL_PULSE 1000");command("VALVE_HOLD");assertSafe();assert(state==IDLE);
 std::cout<<"PASS TTL-only bounds and mutual exclusion with conditioning/manual valve\n";
 reset();command("LICK_END_CAPS");assert(has(",LICK_END_CAPS,1\n"));
 configure(2,10,0);toReward();tick(60000);
 assert(state==WAIT_REWARD_LICK);assertSafe();assert(!has(",TRIAL_END,"));
 auto consumed=fakeNow;lick();assert(state==ITI);
 assert(has(std::to_string(consumed)+",TRIAL_END,1\n"));
 assert(has(std::to_string(consumed)+",ITI_START,2\n"));
 tick(9999);assert(state==ITI);tick(1);assert(state==TRIAL_LEAD);
 until(WAIT_CUE_ON);command("CUE_ON 2");tick(2000);command("CUE_OFF 2");until(VALVE_OPEN);
 tick(4000);assert(state==WAIT_REWARD_LICK);assert(!has(",SESSION_END,"));
 lick();assert(state==IDLE);assert(has(",SESSION_END,2\n"));assertSafe();
 std::cout<<"PASS no-lick waiting, ITI anchored to lick, latch reset and final-trial gating\n";
 reset();configure();toCue();tick(2000);command("CUE_OFF 1");tick(5990);lick();
 tick(10);assert(state==VALVE_OPEN);lick();assert(!rewardLickSatisfied);
 tick(30);assert(state==WAIT_REWARD_LICK);tick(10);lick();assert(state==IDLE);assertSafe();
 std::cout<<"PASS debounce rejects too-close post-reward edge, later accepted lick finishes trial\n";
 for(bool watchdog : {false,true}) {
  reset();configure();toReward();tick(4000);assert(state==WAIT_REWARD_LICK);
  if(watchdog) tick(2000,false);else command("STOP");
  assert(state==IDLE);assertSafe();assert(!has(",TRIAL_END,"));
 }
 reset();fakeNow=UINT32_MAX-12036;configure();toReward();tick(30);command("PING");
 tick(10);lick();assert(state==IDLE);assertSafe();
 std::cout<<"PASS STOP/watchdog while waiting and lick accepted across millis rollover\n";
 reset();command("SESSION_LIMIT_CAPS");assert(has(",SESSION_LIMIT_CAPS,3600\n"));
 for(SessionState target : {START_MARKER, ITI, TRIAL_LEAD, WAIT_CUE_ON, CUE_VISIBLE,
                            REWARD_DELAY, VALVE_OPEN, WAIT_REWARD_LICK, POST_REWARD}) {
  reset();
  command("CONFIG 2 1000 2000 6000 4000 30 1");
  command(std::string("TRIAL 1 0 ")+(target==POST_REWARD?"0":"1"));
  command("TRIAL 2 10 1");command("START");
  if(target==ITI || target==TRIAL_LEAD || target==WAIT_CUE_ON) until(target);
  else if(target!=START_MARKER) {
   toCue();
   if(target!=CUE_VISIBLE) {tick(2000);command("CUE_OFF 1");}
   if(target==VALVE_OPEN || target==WAIT_REWARD_LICK || target==POST_REWARD) until(target);
  }
  assert(state==target);
  sessionStartedMs=fakeNow-(SESSION_LIMIT_MS-1);
  command("PING");assert(state==target);Serial.output.clear();
  tick(1);assert(state==IDLE);assertSafe();assert(!sessionRunning);
  assert(has(",SESSION_TIME_LIMIT,0\n") && has(",SESSION_END,0\n"));
  assert(!has(",TRIAL_END,") && !has(",REWARD_ON,"));
  command("CUE_ON 1");command("CUE_OFF 1");assert(!has(",ERROR,"));assertSafe();
 }
 std::cout<<"PASS one-hour cutoff in every session state, partial trial excluded, late ACK ignored\n";
 reset();configure(2,10,0);auto limitStart=sessionStartedMs;toReward();tick(30);lick();
 assert(trialIndex==1);sessionStartedMs=fakeNow-(SESSION_LIMIT_MS-1);
 tick(1);assert(has(",SESSION_TIME_LIMIT,1\n") && has(",SESSION_END,1\n"));assertSafe();
 Serial.output.clear();configure(1,0,4000);limitStart=sessionStartedMs;tick(3000);assert(state==ITI);
 fakeNow=limitStart+SESSION_LIMIT_MS-1;command("PING");assert(state==ITI);
 tick(1);assert(state==IDLE);assertSafe();assert(!has(",TRIAL_START,1\n"));
 std::cout<<"PASS completed-trial count and start marker/initial ITI included in one-hour limit\n";
 reset();configureTriggers();until(TRIAL_LEAD);tick(900);assert(pins[7]==HIGH);
 sessionStartedMs=fakeNow-(SESSION_LIMIT_MS-1);tick(1);assertSafe();assert(state==IDLE);
 reset();fakeNow=UINT32_MAX-1000;configure(1,0,4000);limitStart=sessionStartedMs;tick(3000);
 fakeNow=limitStart+SESSION_LIMIT_MS-1;command("PING");assert(state==ITI);
 tick(1);assert(state==IDLE);assertSafe();assert(has(",SESSION_TIME_LIMIT,0\n"));
 reset();command("VALVE_HOLD");sessionStartedMs=fakeNow-SESSION_LIMIT_MS;
 tick(1);assert(state==MANUAL_HOLD);command("STOP");assertSafe();
 std::cout<<"PASS cutoff lowers active D7, handles rollover, and excludes manual modes\n";
}
