#pragma once

#ifdef HAS_HEARTBEAT_NEOPIXELS

#include "Observer.h"
#include "concurrency/OSThread.h"
#include "sleep.h"
#include <Adafruit_NeoPixel.h>

#ifndef HEARTBEAT_NEOPIXEL_COUNT_PER_STRIP
#define HEARTBEAT_NEOPIXEL_COUNT_PER_STRIP 7
#endif

#ifndef HEARTBEAT_NEOPIXEL_TYPE
#define HEARTBEAT_NEOPIXEL_TYPE (NEO_GRB + NEO_KHZ800)
#endif

class HeartbeatPixelThread : private concurrency::OSThread
{
  public:
    HeartbeatPixelThread();

  protected:
    int32_t runOnce() override;

  private:
    struct LedPulseConfig {
        float startTime;
        float pulseWidth;
    };

    struct RgbColor {
        uint8_t red;
        uint8_t green;
        uint8_t blue;
    };

    static constexpr uint8_t kCountPerStrip = HEARTBEAT_NEOPIXEL_COUNT_PER_STRIP;
    static constexpr uint8_t kLedCount = kCountPerStrip * 2;
    static constexpr uint32_t kAnimationIntervalMs = 25;
    static constexpr float kOutputScale = 0.5f;
    static constexpr uint16_t kDefaultBpm = 80;
    static constexpr uint16_t kStartupBpm = 80;

    Adafruit_NeoPixel leftPixels;
    Adafruit_NeoPixel rightPixels;

    bool initialized = false;
    bool runningStartup = true;
    bool stripsAreDark = true;
    uint32_t startupStartMs = 0;
    float heartbeatOffsetMs = 0.0f;
    uint16_t currentBpm = kDefaultBpm;

    CallbackObserver<HeartbeatPixelThread, void *> notifyDeepSleepObserver =
        CallbackObserver<HeartbeatPixelThread, void *>(this, &HeartbeatPixelThread::handleDeepSleep);

    void initializeHardware();
    void renderStartupFrame(uint32_t nowMs);
    void renderHeartbeatFrame(uint32_t nowMs);
    void idleOff();
    void applyFrame(float cycleTimeMs, float currentTimeMs, const LedPulseConfig *config);
    float calculateBrightness(float cycleTimeMs, float currentTimeMs, float startTimeMs, float pulseWidthMs) const;
    void syncBpm(uint32_t nowMs);
    void setPixel(uint8_t index, const RgbColor &color, float brightness);
    void showStrips();
    void clearStrips();
    void powerStrips(bool on);
    int handleDeepSleep(void *unused);

    static const LedPulseConfig startupConfig[kLedCount];
    static const LedPulseConfig heartbeatConfig[kLedCount];
    static const RgbColor heartColors[kLedCount];
};

#endif
