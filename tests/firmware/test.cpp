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
void toCue() {until(WAIT_CUE_ON); command("CUE_ON 1");}
void toReward() {toCue();tick(2000);command("CUE_OFF 1");until(VALVE_OPEN);}
void assertSafe(){assert(pins[12]==0 && pins[9]==0 && pins[10]==0 && pins[6]==0);}
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
 tick(1);assert(pins[12]==0);assert(state==POST_REWARD);assert(fakeNow-opened==30);
 tick(3969);assert(state==POST_REWARD);
 tick(1);assert(state==ITI);assert(trialIndex==1);assert(fakeNow-trial1==13000);
 tick(32999);assert(state==ITI);
 tick(1);assert(state==TRIAL_LEAD);assert(trialStartedMs-trial1==46000);
 until(WAIT_CUE_ON);command("CUE_ON 2");tick(2000);command("CUE_OFF 2");until(VALVE_OPEN);
 auto trial2=trialStartedMs;pins[11]=1;loop();tick(30);assert(state==POST_REWARD);
 tick(3970);assert(state==IDLE);assert(fakeNow-trial2==13000);assert(has(",TRIAL_END,2\n"));assert(has(",SESSION_END,2\n"));assertSafe();
 std::cout<<"PASS marker, cue1..3s, reward9s, valve30ms, trial end13s, next start46s, final end13s\n";
 reset();configure();toCue();tick(50);pins[11]=1;loop();pins[11]=0;loop();
 auto licks=lickCount;tick(49);pins[11]=1;loop();assert(lickCount==licks);
 pins[11]=0;loop();tick(1);pins[11]=1;loop();assert(lickCount==licks+1);
 tick(1900);command("CUE_OFF 1");until(VALVE_OPEN);tick(4000);assert(state==IDLE);
 std::cout<<"PASS rising-edge50ms debounce; licking never gates fixed timeline\n";
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
 reset();fakeNow=UINT32_MAX-1000;configure();toReward();tick(4000);assert(state==IDLE);assertSafe();
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
 reset();configure(100,33,90);auto sessionStart=fakeNow;unsigned cueCount=0;
 while(state!=IDLE && uint32_t(fakeNow-sessionStart)<5000000) {
  if(state==WAIT_CUE_ON) {command("CUE_ON "+std::to_string(trialIndex+1));++cueCount;}
  if(state==CUE_VISIBLE && uint32_t(fakeNow-stateStartedMs)>=cueDurationMs)command("CUE_OFF "+std::to_string(trialIndex+1));
  tick(1);
 }
 assert(state==IDLE);assert(cueCount==100);assert(lickCount==0);assert(fakeNow-sessionStart==4660000);
 assert(has(",REWARD_ON,100\n") && has(",TRIAL_END,100\n") && has(",SESSION_END,100\n"));assertSafe();
 std::cout<<"PASS full100-trial no-lick session finishes in4660s with90s initialITI/33s ITIs\n";
}
