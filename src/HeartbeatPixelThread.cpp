#include "HeartbeatPixelThread.h"

#ifdef HAS_HEARTBEAT_NEOPIXELS

#include "configuration.h"

#if !MESHTASTIC_EXCLUDE_HEALTH_TELEMETRY
#include "modules/Telemetry/HealthTelemetry.h"
#endif

#include <Arduino.h>
#include <math.h>

// Pattern arrays are stored directly in the current physical LED order:
// new D1..D14 = old D4, D3, D2, D1, D12, D13, D14, D7, D6, D8, D11, D5, D9, D10.
const HeartbeatPixelThread::LedPulseConfig HeartbeatPixelThread::startupConfig[HeartbeatPixelThread::kLedCount] = {
    {0.0972f, 0.50f}, {0.0873f, 0.50f}, {0.2016f, 0.50f}, {0.3237f, 0.50f}, {0.2241f, 0.50f}, {0.3065f, 0.50f},
    {0.3417f, 0.50f}, {0.2739f, 0.50f}, {0.2154f, 0.50f}, {0.1781f, 0.50f}, {0.0967f, 0.50f}, {0.0760f, 0.50f},
    {0.1110f, 0.50f}, {0.1004f, 0.50f},
};

const HeartbeatPixelThread::LedPulseConfig HeartbeatPixelThread::heartbeatConfig[HeartbeatPixelThread::kLedCount] = {
    {0.2585f, 0.3041f}, {0.1585f, 0.4541f}, {0.6712f, 0.7581f}, {0.5600f, 0.7200f}, {0.5723f, 0.2860f},
    {0.6145f, 0.2856f}, {0.6566f, 0.3256f}, {0.7100f, 0.3600f}, {0.5223f, 0.4670f}, {0.6712f, 0.7581f},
    {0.4513f, 0.4520f}, {0.4508f, 0.4550f}, {0.1585f, 0.4541f}, {0.2589f, 0.3016f},
};

const float HeartbeatPixelThread::kPixelBrightnessModifiers[HeartbeatPixelThread::kLedCount] = {
    1.0f, 1.0f, 1.0f, 0.8f, 0.8f, 0.8f, 0.8f, 0.8f, 0.8f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f,
};

const bool HeartbeatPixelThread::kPixelUsesLed1Color[HeartbeatPixelThread::kLedCount] = {
    true, true, true, true, false, false, false, true, true, false, false, true, false, false,
};

HeartbeatPixelThread::HeartbeatPixelThread()
    : concurrency::OSThread("HeartbeatPixels", kAnimationIntervalMs),
      pixels(kLedCount, HEARTBEAT_NEOPIXEL_LEFT_PIN, HEARTBEAT_NEOPIXEL_TYPE)
{
    notifyDeepSleepObserver.observe(&notifyDeepSleep);
}

int32_t HeartbeatPixelThread::runOnce()
{
    if (!initialized) {
        initializeHardware();
        startupStartMs = millis();
    }

    const uint32_t nowMs = millis();
    if (nextFrameMs == 0) {
        nextFrameMs = nowMs;
    }

    if (runningStartup) {
        renderStartupFrame(nowMs);
        if ((nowMs - startupStartMs) >= (uint32_t)(60000.0f / kStartupBpm)) {
            runningStartup = false;
            idleOff();
        }
    } else {
        const LocalLedEffectiveConfig effective =
            localLedConfigStore ? localLedConfigStore->getEffectiveConfigForActiveChannel()
                                : LocalLedEffectiveConfig{0x0000FF, 0xFF0000, 80, 0, false, 0};
        bool heartRateActive = false;
#if !MESHTASTIC_EXCLUDE_HEALTH_TELEMETRY
        heartRateActive = healthTelemetryModule && healthTelemetryModule->isHeartRateActive();
#endif
        if (heartRateActive) {
            syncBpm(nowMs);
            renderHeartbeatFrame(nowMs, effective);
        } else if (!config.device.led_heartbeat_disabled) {
            currentBpm = effective.idle_bpm;
            renderHeartbeatFrame(nowMs, effective);
        } else {
            currentBpm = effective.idle_bpm;
            heartbeatOffsetMs = 0.0f;
            idleOff();
        }
    }

    uint32_t targetNextFrameMs = nextFrameMs + kAnimationIntervalMs;
    if ((int32_t)(nowMs - targetNextFrameMs) >= 0) {
        targetNextFrameMs = nowMs + kAnimationIntervalMs;
    }
    nextFrameMs = targetNextFrameMs;

    return RUN_SAME;
}

bool HeartbeatPixelThread::shouldRun(unsigned long time)
{
    if (!enabled) {
        return false;
    }
    if (nextFrameMs == 0) {
        return true;
    }
    return (int32_t)(time - nextFrameMs) >= 0;
}

long HeartbeatPixelThread::tillRun(unsigned long time)
{
    if (!enabled) {
        return __LONG_MAX__;
    }
    if (nextFrameMs == 0) {
        return 0;
    }
    return (long)((int32_t)(nextFrameMs - time));
}

void HeartbeatPixelThread::initializeHardware()
{
    powerStrips(true);
    pixels.begin();
    clearStrips();
    initialized = true;
}

void HeartbeatPixelThread::renderStartupFrame(uint32_t nowMs)
{
    const double cycleTimeMs = 60000.0 / (double)kStartupBpm;
    const double elapsedMs = (double)(nowMs - startupStartMs);
    LocalLedEffectiveConfig startupEffective = {0x0000FF, 0xFF0000, kStartupBpm, 0, true, 0};
    applyFrame(cycleTimeMs, cycleTimeMs, elapsedMs, startupConfig, startupEffective);
}

void HeartbeatPixelThread::renderHeartbeatFrame(uint32_t nowMs, const LocalLedEffectiveConfig &effective)
{
    const double activeWindowMs = 60000.0 / (double)currentBpm;
    const double cycleTimeMs = activeWindowMs + (double)effective.idle_delay_ms;
    applyFrame(cycleTimeMs, activeWindowMs, (double)nowMs + heartbeatOffsetMs, heartbeatConfig, effective);
}

void HeartbeatPixelThread::idleOff()
{
    if (!stripsAreDark) {
        clearStrips();
    }
}

void HeartbeatPixelThread::applyFrame(double cycleTimeMs, double activeWindowMs, double currentTimeMs, const LedPulseConfig *config,
                                      const LocalLedEffectiveConfig &effective)
{
    const RgbColor led1Color = colorFromHex(effective.led1_color);
    const RgbColor led2Color = colorFromHex(effective.led2_color);
    for (uint8_t i = 0; i < kLedCount; ++i) {
        const float brightness =
            calculateBrightness(cycleTimeMs, currentTimeMs, config[i].startTime * activeWindowMs, config[i].pulseWidth * activeWindowMs);
        setPixel(i, kPixelUsesLed1Color[i] ? led1Color : led2Color, brightness);
    }
    showStrips();
}

float HeartbeatPixelThread::calculateBrightness(double cycleTimeMs, double currentTimeMs, double startTimeMs, double pulseWidthMs) const
{
    const double wrappedTime = fmod(currentTimeMs, cycleTimeMs);
    const double endTimeMs = startTimeMs + pulseWidthMs;

    if ((endTimeMs < cycleTimeMs) && (wrappedTime >= startTimeMs) && (wrappedTime <= fmod(endTimeMs, cycleTimeMs))) {
        return (float)(0.5 - 0.5 * cos((wrappedTime - startTimeMs) / pulseWidthMs * 2.0 * PI));
    }
    if ((endTimeMs > cycleTimeMs) && ((wrappedTime >= startTimeMs) || (wrappedTime <= fmod(endTimeMs, cycleTimeMs)))) {
        if (wrappedTime >= startTimeMs) {
            return (float)(0.5 - 0.5 * cos((wrappedTime - startTimeMs) / pulseWidthMs * 2.0 * PI));
        }
        return (float)(0.5 - 0.5 * cos((wrappedTime + cycleTimeMs - startTimeMs) / pulseWidthMs * 2.0 * PI));
    }

    return 0.0f;
}

void HeartbeatPixelThread::syncBpm(uint32_t nowMs)
{
#if !MESHTASTIC_EXCLUDE_HEALTH_TELEMETRY
    uint8_t measuredBpm = 0;
    if (healthTelemetryModule && healthTelemetryModule->getCurrentHeartBpm(&measuredBpm) && measuredBpm >= 30 && measuredBpm <= 220 &&
        measuredBpm != currentBpm) {
        const double currentCycleMs = 60000.0 / (double)currentBpm;
        heartbeatOffsetMs = fmod((double)nowMs + heartbeatOffsetMs, currentCycleMs) * (double)currentBpm / (double)measuredBpm -
                            (double)nowMs;
        currentBpm = measuredBpm;
    }
#else
    (void)nowMs;
#endif
}

HeartbeatPixelThread::RgbColor HeartbeatPixelThread::colorFromHex(uint32_t color)
{
    return RgbColor{(uint8_t)((color >> 16) & 0xFF), (uint8_t)((color >> 8) & 0xFF), (uint8_t)(color & 0xFF)};
}

void HeartbeatPixelThread::setPixel(uint8_t index, const RgbColor &color, float brightness)
{
    const float scaledBrightness = brightness * kPixelBrightnessModifiers[index];
    const uint8_t red = (uint8_t)roundf((float)color.red * kOutputScale * scaledBrightness);
    const uint8_t green = (uint8_t)roundf((float)color.green * kOutputScale * scaledBrightness);
    const uint8_t blue = (uint8_t)roundf((float)color.blue * kOutputScale * scaledBrightness);
    const uint32_t pixelColor = pixels.Color(red, green, blue);
    pixels.setPixelColor(index, pixelColor);
}

void HeartbeatPixelThread::showStrips()
{
    pixels.show();
    stripsAreDark = false;
}

void HeartbeatPixelThread::clearStrips()
{
    pixels.clear();
    showStrips();
    stripsAreDark = true;
}

void HeartbeatPixelThread::powerStrips(bool on)
{
#ifdef HEARTBEAT_NEOPIXEL_POWER_PIN
    pinMode(HEARTBEAT_NEOPIXEL_POWER_PIN, OUTPUT);
    digitalWrite(HEARTBEAT_NEOPIXEL_POWER_PIN, on ? HIGH : LOW);
#else
    (void)on;
#endif
}

int HeartbeatPixelThread::handleDeepSleep(void *unused)
{
    (void)unused;
    if (initialized) {
        clearStrips();
        delay(1); // Let the final all-off NeoPixel frame latch before cutting strip power.
    }
    powerStrips(false);
    return 0;
}

#endif
