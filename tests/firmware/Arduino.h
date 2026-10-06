#pragma once
#include <cstdint>
#include <deque>
#include <string>
#include <type_traits>
#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
class __FlashStringHelper {};
#define F(x) reinterpret_cast<const __FlashStringHelper *>(x)
extern uint32_t fakeNow;
extern int pins[20];
inline uint32_t millis() { return fakeNow; }
inline void digitalWrite(int pin, int value) { pins[pin] = value; }
inline int digitalRead(int pin) { return pins[pin]; }
inline void pinMode(int, int) {}
struct FakeSerial {
 std::deque<char> input;
 std::string output;
 void begin(int) {}
 int available() { return input.size(); }
 char read() { char c=input.front(); input.pop_front(); return c; }
 void print(char c) { output += c; }
 void print(const char* s) { output += s; }
 void print(const __FlashStringHelper *s) { output += reinterpret_cast<const char*>(s); }
 template <class T> typename std::enable_if<std::is_integral<T>::value>::type
 print(T v) { output += std::to_string(v); }
 template <class T> void println(T v) { print(v); output += '\n'; }
};
extern FakeSerial Serial;
