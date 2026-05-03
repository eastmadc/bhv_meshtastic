#pragma once

#ifdef HAS_HEARTBEAT_NEOPIXELS

#include "Observer.h"
#include "led/LocalLedConfig.h"
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
    bool shouldRun(unsigned long time) override;
    long tillRun(unsigned long time) override;

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
    static constexpr float kOutputScale = 0.35f;
    static constexpr uint16_t kStartupBpm = 80;
    static const float kPixelBrightnessModifiers[kLedCount];
    static const bool kPixelUsesLed1Color[kLedCount];

    Adafruit_NeoPixel pixels;

    bool initialized = false;
    bool runningStartup = true;
    bool stripsAreDark = true;
    uint32_t startupStartMs = 0;
    uint32_t nextFrameMs = 0;
    double heartbeatOffsetMs = 0.0;
    uint16_t currentBpm = 80;

    CallbackObserver<HeartbeatPixelThread, void *> notifyDeepSleepObserver =
        CallbackObserver<HeartbeatPixelThread, void *>(this, &HeartbeatPixelThread::handleDeepSleep);

    void initializeHardware();
    void renderStartupFrame(uint32_t nowMs);
    void renderHeartbeatFrame(uint32_t nowMs, const LocalLedEffectiveConfig &effective);
    void idleOff();
    void applyFrame(double cycleTimeMs, double activeWindowMs, double currentTimeMs, const LedPulseConfig *config,
                    const LocalLedEffectiveConfig &effective);
    float calculateBrightness(double cycleTimeMs, double currentTimeMs, double startTimeMs, double pulseWidthMs) const;
    void syncBpm(uint32_t nowMs);
    void setPixel(uint8_t index, const RgbColor &color, float brightness);
    static RgbColor colorFromHex(uint32_t color);
    void showStrips();
    void clearStrips();
    void powerStrips(bool on);
    int handleDeepSleep(void *unused);

    static const LedPulseConfig startupConfig[kLedCount];
    static const LedPulseConfig heartbeatConfig[kLedCount];
};

#endif
