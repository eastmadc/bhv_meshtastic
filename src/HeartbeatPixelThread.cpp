#include "HeartbeatPixelThread.h"

#ifdef HAS_HEARTBEAT_NEOPIXELS

#include "configuration.h"
#include "concurrency/LockGuard.h"

#if !MESHTASTIC_EXCLUDE_HEALTH_TELEMETRY
#include "modules/Telemetry/HealthTelemetry.h"
#endif

#include <Arduino.h>
#include <math.h>

HeartbeatPixelThread *heartbeatPixelThread = nullptr;

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

// Physical LED sequence for each notification color lane.
// Lane 1: D4, D3, D2, D1, D12, D9, D8.
const uint8_t HeartbeatPixelThread::kLed1NotificationSequence[HeartbeatPixelThread::kLed1SequenceLength] = {
    3, 2, 1, 0, 11, 8, 7,
};

// Lane 2: D10, D13, D14, D11, D5, D6, D7.
const uint8_t HeartbeatPixelThread::kLed2NotificationSequence[HeartbeatPixelThread::kLed2SequenceLength] = {
    9, 12, 13, 10, 4, 5, 6,
};

HeartbeatPixelThread::HeartbeatPixelThread()
    : concurrency::OSThread("HeartbeatPixels", kAnimationIntervalMs),
      pixels(kLedCount, HEARTBEAT_NEOPIXEL_LEFT_PIN, HEARTBEAT_NEOPIXEL_TYPE)
{
    heartbeatPixelThread = this;
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
        LocalLedEffectiveConfig effective = {0x0000FF, 0xFF0000, 80, 0, kLocalLedDefaultNotificationPulses, false, 0};
        if (localLedConfigStore) {
            const CustomLedConfig cfg = localLedConfigStore->getConfig();
            effective.led1_color = cfg.node_led1_color;
            effective.led2_color = cfg.node_led2_color;
            effective.idle_bpm = cfg.idle_bpm;
            effective.idle_delay_ms = cfg.idle_delay_ms;
            effective.notification_pulses = cfg.notification_pulses;
        }
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
            hasNotificationProgress = false;
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
    initializeNotificationSequenceTimings();
    clearStrips();
    initialized = true;
}

void HeartbeatPixelThread::initializeNotificationSequenceTimings()
{
    led1SequenceTiming = calculateNotificationSequenceTiming(kLed1NotificationSequence, kLed1SequenceLength);
    led2SequenceTiming = calculateNotificationSequenceTiming(kLed2NotificationSequence, kLed2SequenceLength);
}

void HeartbeatPixelThread::renderStartupFrame(uint32_t nowMs)
{
    const double cycleTimeMs = 60000.0 / (double)kStartupBpm;
    const double elapsedMs = (double)(nowMs - startupStartMs);
    LocalLedEffectiveConfig startupEffective = {0x0000FF, 0xFF0000, kStartupBpm, 0, kLocalLedDefaultNotificationPulses, true, 0};
    hasNotificationProgress = false;
    applyFrame(cycleTimeMs, cycleTimeMs, elapsedMs, startupConfig, startupEffective);
}

void HeartbeatPixelThread::renderHeartbeatFrame(uint32_t nowMs, const LocalLedEffectiveConfig &effective)
{
    const double activeWindowMs = 60000.0 / (double)currentBpm;
    const double cycleTimeMs = activeWindowMs + (double)effective.idle_delay_ms;
    const double currentTimeMs = (double)nowMs + heartbeatOffsetMs;
    updateNotificationSequences(cycleTimeMs, activeWindowMs, currentTimeMs, true);
    applyFrame(cycleTimeMs, activeWindowMs, currentTimeMs, heartbeatConfig, effective);
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
    NotificationLane led1LaneSnapshot = {};
    NotificationLane led2LaneSnapshot = {};
    double progressSnapshot = 0.0;
    {
        concurrency::LockGuard guard(&notificationLock);
        led1LaneSnapshot = led1NotificationLane;
        led2LaneSnapshot = led2NotificationLane;
        progressSnapshot = notificationProgress;
    }

    for (uint8_t i = 0; i < kLedCount; ++i) {
        const float brightness =
            calculateBrightness(cycleTimeMs, currentTimeMs, config[i].startTime * activeWindowMs, config[i].pulseWidth * activeWindowMs);
        const bool usesLed1Color = kPixelUsesLed1Color[i];
        const RgbColor &baseColor = usesLed1Color ? led1Color : led2Color;
        const bool useNotificationColor =
            usesLed1Color ? notificationAppliesToPixel(led1LaneSnapshot, i, progressSnapshot)
                          : notificationAppliesToPixel(led2LaneSnapshot, i, progressSnapshot);
        const RgbColor &color =
            useNotificationColor ? (usesLed1Color ? led1LaneSnapshot.color : led2LaneSnapshot.color) : baseColor;
        setPixel(i, color, brightness);
    }
    showStrips();
}

bool HeartbeatPixelThread::enqueueChannelNotification(uint8_t channel)
{
    if (!localLedConfigStore) {
        return false;
    }

    LocalLedEffectiveConfig effective = localLedConfigStore->getEffectiveConfigForChannel(channel);
    if (!effective.configured) {
        return false;
    }

    concurrency::LockGuard guard(&notificationLock);
    if (notificationChannelIsPendingLocked(effective.channel_index) || notificationQueueCount >= kNotificationQueueSize) {
        return false;
    }

    const uint8_t insertIndex = (notificationQueueHead + notificationQueueCount) % kNotificationQueueSize;
    notificationQueue[insertIndex].used = true;
    notificationQueue[insertIndex].channel = effective.channel_index;
    notificationQueue[insertIndex].led1Color = colorFromHex(effective.led1_color);
    notificationQueue[insertIndex].led2Color = colorFromHex(effective.led2_color);
    notificationQueue[insertIndex].pulseCount =
        effective.notification_pulses > 0 ? effective.notification_pulses : kLocalLedDefaultNotificationPulses;
    notificationQueue[insertIndex].eligibleProgress = hasNotificationProgress ? floor(notificationProgress) + 1.0 : 0.0;
    notificationQueue[insertIndex].led1Loaded = false;
    notificationQueue[insertIndex].led2Loaded = false;
    notificationQueueCount++;
    return true;
}

void HeartbeatPixelThread::updateNotificationSequences(double cycleTimeMs, double activeWindowMs, double currentTimeMs,
                                                       bool allowNewNotifications)
{
    double wrappedTimeMs = fmod(currentTimeMs, cycleTimeMs);
    if (wrappedTimeMs < 0) {
        wrappedTimeMs += cycleTimeMs;
    }
    const double currentPhase = wrappedTimeMs / cycleTimeMs;
    if (!hasNotificationProgress) {
        hasNotificationProgress = true;
        lastNotificationPhase = currentPhase;
        notificationProgress = currentPhase;
        return;
    }

    double phaseDelta = currentPhase - lastNotificationPhase;
    if (phaseDelta < 0.0) {
        phaseDelta += 1.0;
    }
    const double previousProgress = notificationProgress;
    notificationProgress += phaseDelta;

    {
        concurrency::LockGuard guard(&notificationLock);
        if (allowNewNotifications) {
            const double activeWindowScale = activeWindowMs / cycleTimeMs;
            processNotificationLane(led1NotificationLane, led1SequenceTiming, true, previousProgress, notificationProgress,
                                    activeWindowScale);
            processNotificationLane(led2NotificationLane, led2SequenceTiming, false, previousProgress, notificationProgress,
                                    activeWindowScale);
        }
    }

    lastNotificationPhase = currentPhase;
}

void HeartbeatPixelThread::processNotificationLane(NotificationLane &lane, const NotificationSequenceTiming &timing, bool useLed1Color,
                                                   double previousProgress, double currentProgress, double activeWindowScale)
{
    if (lane.active && currentProgress >= lane.laneEndProgress) {
        lane = NotificationLane{};
    }

    const double startPhase = timing.startOffset * activeWindowScale;
    if (lane.active || !crossedProgressPhase(previousProgress, currentProgress, startPhase)) {
        return;
    }

    double startProgress = floor(currentProgress - startPhase) + startPhase;
    if (startProgress > currentProgress) {
        startProgress -= 1.0;
    }
    if (!lane.active) {
        loadNotificationLane(lane, timing, useLed1Color, startProgress, activeWindowScale);
    }
}

bool HeartbeatPixelThread::loadNotificationLane(NotificationLane &lane, const NotificationSequenceTiming &timing, bool useLed1Color,
                                                double laneStartProgress, double activeWindowScale)
{
    PendingNotification *pending = notificationQueueFrontLocked();
    if (!pending) {
        return false;
    }
    if (notificationProgress < pending->eligibleProgress) {
        return false;
    }
    if (!useLed1Color && !pending->led1Loaded) {
        return false;
    }

    lane.active = true;
    lane.channel = pending->channel;
    lane.color = useLed1Color ? pending->led1Color : pending->led2Color;
    lane.laneEndProgress =
        laneStartProgress + sequenceOffsetToProgressOffset(timing, timing.endOffset + pending->pulseCount, activeWindowScale);
    for (uint8_t i = 0; i < kLedCount; ++i) {
        lane.ledWindows[i] = LedNotificationWindow{};
        if (timing.ledStartOffsets[i] >= 0.0) {
            lane.ledWindows[i].active = true;
            lane.ledWindows[i].startProgress =
                laneStartProgress + sequenceOffsetToProgressOffset(timing, timing.ledStartOffsets[i], activeWindowScale);
            lane.ledWindows[i].endProgress =
                laneStartProgress +
                sequenceOffsetToProgressOffset(timing, timing.ledStartOffsets[i] + pending->pulseCount, activeWindowScale);
        }
    }
    if (useLed1Color) {
        pending->led1Loaded = true;
    } else {
        pending->led2Loaded = true;
    }

    if (pending->led1Loaded && pending->led2Loaded) {
        popNotificationQueueLocked();
    }
    return true;
}

bool HeartbeatPixelThread::notificationChannelIsPendingLocked(uint8_t channel) const
{
    if ((led1NotificationLane.active && led1NotificationLane.channel == channel) ||
        (led2NotificationLane.active && led2NotificationLane.channel == channel)) {
        return true;
    }

    for (uint8_t i = 0; i < notificationQueueCount; ++i) {
        const uint8_t index = (notificationQueueHead + i) % kNotificationQueueSize;
        if (notificationQueue[index].used && notificationQueue[index].channel == channel) {
            return true;
        }
    }
    return false;
}

HeartbeatPixelThread::PendingNotification *HeartbeatPixelThread::notificationQueueFrontLocked()
{
    if (notificationQueueCount == 0) {
        return nullptr;
    }
    PendingNotification &front = notificationQueue[notificationQueueHead];
    return front.used ? &front : nullptr;
}

void HeartbeatPixelThread::popNotificationQueueLocked()
{
    if (notificationQueueCount == 0) {
        return;
    }

    notificationQueue[notificationQueueHead] = PendingNotification{};
    notificationQueueHead = (notificationQueueHead + 1) % kNotificationQueueSize;
    notificationQueueCount--;
}

void HeartbeatPixelThread::clearNotificationState()
{
    concurrency::LockGuard guard(&notificationLock);
    notificationQueueHead = 0;
    notificationQueueCount = 0;
    for (uint8_t i = 0; i < kNotificationQueueSize; ++i) {
        notificationQueue[i] = PendingNotification{};
    }
    led1NotificationLane = NotificationLane{};
    led2NotificationLane = NotificationLane{};
    hasNotificationProgress = false;
}

bool HeartbeatPixelThread::crossedProgressPhase(double previousProgress, double currentProgress, double phase)
{
    double triggerProgress = floor(previousProgress - phase) + phase;
    if (triggerProgress <= previousProgress) {
        triggerProgress += 1.0;
    }
    return triggerProgress <= currentProgress;
}

bool HeartbeatPixelThread::notificationAppliesToPixel(const NotificationLane &lane, uint8_t ledIndex, double currentProgress)
{
    if (!lane.active || ledIndex >= kLedCount || !lane.ledWindows[ledIndex].active) {
        return false;
    }

    const LedNotificationWindow &window = lane.ledWindows[ledIndex];
    return currentProgress >= window.startProgress && currentProgress < window.endProgress;
}

double HeartbeatPixelThread::sequenceOffsetToProgressOffset(const NotificationSequenceTiming &timing, double sequenceOffset,
                                                            double activeWindowScale)
{
    const double absoluteSequencePosition = timing.startOffset + sequenceOffset;
    const double cycleOffset = floor(absoluteSequencePosition);
    const double phaseOffset = absoluteSequencePosition - cycleOffset;
    return cycleOffset + ((phaseOffset - timing.startOffset) * activeWindowScale);
}

HeartbeatPixelThread::NotificationSequenceTiming
HeartbeatPixelThread::calculateNotificationSequenceTiming(const uint8_t *sequence, uint8_t sequenceLength)
{
    NotificationSequenceTiming timing = {};
    for (uint8_t i = 0; i < kLedCount; ++i) {
        timing.ledStartOffsets[i] = kInactiveSequenceOffset;
    }

    if (sequenceLength == 0) {
        return timing;
    }

    timing.startOffset = heartbeatConfig[sequence[0]].startTime;
    double ledStartOffset = timing.startOffset;
    timing.ledStartOffsets[sequence[0]] = 0.0;
    for (uint8_t i = 1; i < sequenceLength; ++i) {
        const uint8_t ledIndex = sequence[i];
        const double offset = heartbeatConfig[ledIndex].startTime;
        double nextStartOffset = floor(ledStartOffset - offset) + offset;
        while (nextStartOffset <= ledStartOffset) {
            nextStartOffset += 1.0;
        }
        ledStartOffset = nextStartOffset;
        timing.ledStartOffsets[ledIndex] = ledStartOffset - timing.startOffset;
    }

    timing.endOffset = timing.ledStartOffsets[sequence[sequenceLength - 1]];
    return timing;
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
    clearNotificationState();
    if (initialized) {
        clearStrips();
        delay(1); // Let the final all-off NeoPixel frame latch before cutting strip power.
    }
    powerStrips(false);
    return 0;
}

#endif
