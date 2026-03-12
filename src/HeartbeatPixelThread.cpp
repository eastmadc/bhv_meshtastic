#include "HeartbeatPixelThread.h"

#ifdef HAS_HEARTBEAT_NEOPIXELS

#include "configuration.h"

#if !MESHTASTIC_EXCLUDE_HEALTH_TELEMETRY
#include "modules/Telemetry/HealthTelemetry.h"
#endif

#include <Arduino.h>
#include <math.h>

const HeartbeatPixelThread::LedPulseConfig HeartbeatPixelThread::startupConfig[HeartbeatPixelThread::kLedCount] = {
    {0.3237f, 0.50f}, {0.2016f, 0.50f}, {0.0873f, 0.50f}, {0.0972f, 0.50f}, {0.0760f, 0.50f}, {0.2154f, 0.50f},
    {0.2739f, 0.50f}, {0.1781f, 0.50f}, {0.1110f, 0.50f}, {0.1004f, 0.50f}, {0.0967f, 0.50f}, {0.2241f, 0.50f},
    {0.3065f, 0.50f}, {0.3417f, 0.50f},
};

const HeartbeatPixelThread::LedPulseConfig HeartbeatPixelThread::heartbeatConfig[HeartbeatPixelThread::kLedCount] = {
    {0.6484f, 0.5508f}, {0.6712f, 0.7581f}, {0.1585f, 0.4541f}, {0.2585f, 0.3041f}, {0.4508f, 0.4450f},
    {0.5223f, 0.4670f}, {0.6000f, 0.3256f}, {0.6712f, 0.7581f}, {0.1585f, 0.4541f}, {0.2589f, 0.3016f},
    {0.4513f, 0.4420f}, {0.5723f, 0.2660f}, {0.5862f, 0.2656f}, {0.6032f, 0.3256f},
};

const HeartbeatPixelThread::RgbColor HeartbeatPixelThread::heartColors[HeartbeatPixelThread::kLedCount] = {
    {0x00, 0x00, 0xff}, {0x00, 0x00, 0xff}, {0x00, 0x00, 0xff}, {0x00, 0x00, 0xff}, {0x00, 0x00, 0xff},
    {0x00, 0x00, 0xff}, {0x00, 0x00, 0xff}, {0xff, 0x00, 0x00}, {0xff, 0x00, 0x00}, {0xff, 0x00, 0x00},
    {0xff, 0x00, 0x00}, {0xff, 0x00, 0x00}, {0xff, 0x00, 0x00}, {0xff, 0x00, 0x00},
};

HeartbeatPixelThread::HeartbeatPixelThread()
    : concurrency::OSThread("HeartbeatPixels", kAnimationIntervalMs),
      leftPixels(kCountPerStrip, HEARTBEAT_NEOPIXEL_LEFT_PIN, HEARTBEAT_NEOPIXEL_TYPE),
      rightPixels(kCountPerStrip, HEARTBEAT_NEOPIXEL_RIGHT_PIN, HEARTBEAT_NEOPIXEL_TYPE)
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
    if (runningStartup) {
        renderStartupFrame(nowMs);
        if ((nowMs - startupStartMs) >= (uint32_t)(60000.0f / kStartupBpm)) {
            runningStartup = false;
            idleOff();
        }
    } else {
        bool heartRateActive = false;
#if !MESHTASTIC_EXCLUDE_HEALTH_TELEMETRY
        heartRateActive = healthTelemetryModule && healthTelemetryModule->isHeartRateActive();
#endif
        if (heartRateActive) {
            syncBpm(nowMs);
            renderHeartbeatFrame(nowMs);
        } else if (!config.device.led_heartbeat_disabled) {
            currentBpm = kDefaultBpm;
            renderHeartbeatFrame(nowMs);
        } else {
            currentBpm = kDefaultBpm;
            heartbeatOffsetMs = 0.0f;
            idleOff();
        }
    }

    return kAnimationIntervalMs;
}

void HeartbeatPixelThread::initializeHardware()
{
    powerStrips(true);
    leftPixels.begin();
    rightPixels.begin();
    clearStrips();
    initialized = true;
}

void HeartbeatPixelThread::renderStartupFrame(uint32_t nowMs)
{
    const float cycleTimeMs = 60000.0f / kStartupBpm;
    const float elapsedMs = (float)(nowMs - startupStartMs);
    applyFrame(cycleTimeMs, elapsedMs, startupConfig);
}

void HeartbeatPixelThread::renderHeartbeatFrame(uint32_t nowMs)
{
    const float cycleTimeMs = 60000.0f / currentBpm;
    applyFrame(cycleTimeMs, (float)nowMs + heartbeatOffsetMs, heartbeatConfig);
}

void HeartbeatPixelThread::idleOff()
{
    if (!stripsAreDark) {
        clearStrips();
    }
}

void HeartbeatPixelThread::applyFrame(float cycleTimeMs, float currentTimeMs, const LedPulseConfig *config)
{
    for (uint8_t i = 0; i < kLedCount; ++i) {
        const float brightness =
            calculateBrightness(cycleTimeMs, currentTimeMs, config[i].startTime * cycleTimeMs, config[i].pulseWidth * cycleTimeMs);
        setPixel(i, heartColors[i], brightness);
    }
    showStrips();
}

float HeartbeatPixelThread::calculateBrightness(float cycleTimeMs, float currentTimeMs, float startTimeMs, float pulseWidthMs) const
{
    const float wrappedTime = fmodf(currentTimeMs, cycleTimeMs);
    const float endTimeMs = startTimeMs + pulseWidthMs;

    if ((endTimeMs < cycleTimeMs) && (wrappedTime >= startTimeMs) && (wrappedTime <= fmodf(endTimeMs, cycleTimeMs))) {
        return 0.5f - 0.5f * cosf((wrappedTime - startTimeMs) / pulseWidthMs * 2.0f * PI);
    }
    if ((endTimeMs > cycleTimeMs) && ((wrappedTime >= startTimeMs) || (wrappedTime <= fmodf(endTimeMs, cycleTimeMs)))) {
        if (wrappedTime >= startTimeMs) {
            return 0.5f - 0.5f * cosf((wrappedTime - startTimeMs) / pulseWidthMs * 2.0f * PI);
        }
        return 0.5f - 0.5f * cosf((wrappedTime + cycleTimeMs - startTimeMs) / pulseWidthMs * 2.0f * PI);
    }

    return 0.0f;
}

void HeartbeatPixelThread::syncBpm(uint32_t nowMs)
{
#if !MESHTASTIC_EXCLUDE_HEALTH_TELEMETRY
    uint8_t measuredBpm = 0;
    if (healthTelemetryModule && healthTelemetryModule->getCurrentHeartBpm(&measuredBpm) && measuredBpm >= 30 && measuredBpm <= 220 &&
        measuredBpm != currentBpm) {
        const float currentCycleMs = 60000.0f / currentBpm;
        heartbeatOffsetMs = fmodf((float)nowMs + heartbeatOffsetMs, currentCycleMs) * currentBpm / measuredBpm - (float)nowMs;
        currentBpm = measuredBpm;
    }
#else
    (void)nowMs;
#endif
}

void HeartbeatPixelThread::setPixel(uint8_t index, const RgbColor &color, float brightness)
{
    const uint8_t red = (uint8_t)roundf((float)color.red * kOutputScale * brightness);
    const uint8_t green = (uint8_t)roundf((float)color.green * kOutputScale * brightness);
    const uint8_t blue = (uint8_t)roundf((float)color.blue * kOutputScale * brightness);
    const uint32_t pixelColor = leftPixels.Color(red, green, blue);

    if (index < kCountPerStrip) {
        leftPixels.setPixelColor(index, pixelColor);
    } else {
        rightPixels.setPixelColor(index - kCountPerStrip, pixelColor);
    }
}

void HeartbeatPixelThread::showStrips()
{
    leftPixels.show();
    rightPixels.show();
    stripsAreDark = false;
}

void HeartbeatPixelThread::clearStrips()
{
    leftPixels.clear();
    rightPixels.clear();
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
    }
    powerStrips(false);
    return 0;
}

#endif
