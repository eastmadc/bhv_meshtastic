#include "LocalLedConfig.h"

#include "Channels.h"
#include "FSCommon.h"
#include "RTC.h"
#include "SPILock.h"
#include "concurrency/OSThread.h"
#include "concurrency/LockGuard.h"
#include "led/LocalLedCommandParser.h"
#include "mesh/MeshService.h"
#include "mesh/NodeDB.h"
#include "mesh/Router.h"
#include "power/PowerHAL.h"

#include <string.h>

namespace
{
static constexpr const char *kFileName = "/prefs/custom_led.bin";
static constexpr uint32_t kMagic = 0x434C4544;
static constexpr uint16_t kVersion = 5;
static constexpr size_t kLegacySerializedSize = 94;
static constexpr size_t kSerializedSize = 103;
static constexpr uint32_t kLocalReplyDelayMs = 500;

class LocalLedReplyDispatcher : private concurrency::OSThread
{
  public:
    LocalLedReplyDispatcher() : concurrency::OSThread("LocalLedReply", UINT32_MAX) { enabled = false; }

    bool enqueue(meshtastic_MeshPacket *packet)
    {
        if (!packet) {
            return false;
        }

        concurrency::LockGuard guard(&lock);
        uint8_t slot = kQueueSize;
        for (uint8_t i = 0; i < kQueueSize; ++i) {
            if (!pending[i].packet) {
                slot = i;
                break;
            }
        }
        if (slot >= kQueueSize) {
            return false;
        }

        pending[slot].packet = packet;
        pending[slot].due_ms = millis() + kLocalReplyDelayMs;
        enabled = true;
        setIntervalFromNow(getNextDelayLocked(millis()));
        return true;
    }

  protected:
    int32_t runOnce() override
    {
        meshtastic_MeshPacket *ready[kQueueSize] = {};
        uint8_t readyCount = 0;
        uint32_t now = millis();
        uint32_t nextDelay = UINT32_MAX;

        {
            concurrency::LockGuard guard(&lock);
            for (uint8_t i = 0; i < kQueueSize; ++i) {
                if (!pending[i].packet) {
                    continue;
                }
                if ((int32_t)(pending[i].due_ms - now) <= 0) {
                    ready[readyCount++] = pending[i].packet;
                    pending[i].packet = nullptr;
                    pending[i].due_ms = 0;
                    continue;
                }

                uint32_t delay = pending[i].due_ms - now;
                if (delay < nextDelay) {
                    nextDelay = delay;
                }
            }

            if (nextDelay == UINT32_MAX) {
                enabled = false;
            }
        }

        for (uint8_t i = 0; i < readyCount; ++i) {
            if (service) {
                service->sendToPhone(ready[i]);
            } else {
                packetPool.release(ready[i]);
            }
        }

        if (nextDelay == UINT32_MAX) {
            return disable();
        }
        return (int32_t)nextDelay;
    }

  private:
    static constexpr uint8_t kQueueSize = 4;

    struct PendingReply {
        meshtastic_MeshPacket *packet = nullptr;
        uint32_t due_ms = 0;
    };

    uint32_t getNextDelayLocked(uint32_t now) const
    {
        uint32_t nextDelay = UINT32_MAX;
        for (uint8_t i = 0; i < kQueueSize; ++i) {
            if (!pending[i].packet) {
                continue;
            }
            uint32_t delay = ((int32_t)(pending[i].due_ms - now) <= 0) ? 0 : (pending[i].due_ms - now);
            if (delay < nextDelay) {
                nextDelay = delay;
            }
        }
        return nextDelay == UINT32_MAX ? UINT32_MAX : nextDelay;
    }

    mutable concurrency::Lock lock;
    PendingReply pending[kQueueSize];
};

bool hasAnyChannelOverrides(const CustomLedConfig &config)
{
    for (size_t i = 0; i < 8; ++i) {
        if (config.channels[i].configured) {
            return true;
        }
    }
    return false;
}

bool isLegacyWhiteDefaultConfig(const CustomLedConfig &config)
{
    return config.node_led1_color == 0xFFFFFF && config.node_led2_color == 0xFFFFFF && config.idle_bpm == 30 &&
           config.idle_delay_ms == 1000 && !hasAnyChannelOverrides(config);
}

bool isLegacyBlueRedDefaultConfig(const CustomLedConfig &config)
{
    return config.node_led1_color == 0x0000FF && config.node_led2_color == 0xFF0000 && config.idle_bpm == 30 &&
           config.idle_delay_ms == 1000 && !hasAnyChannelOverrides(config);
}

bool isCurrentBlueRedDefaultConfig(const CustomLedConfig &config)
{
    return config.node_led1_color == 0x0000FF && config.node_led2_color == 0xFF0000 && config.idle_bpm == 30 &&
           config.idle_delay_ms == 0 && !hasAnyChannelOverrides(config);
}

void writeUint16(uint8_t *buffer, size_t &offset, uint16_t value)
{
    buffer[offset++] = (uint8_t)(value & 0xFF);
    buffer[offset++] = (uint8_t)((value >> 8) & 0xFF);
}

void writeUint32(uint8_t *buffer, size_t &offset, uint32_t value)
{
    buffer[offset++] = (uint8_t)(value & 0xFF);
    buffer[offset++] = (uint8_t)((value >> 8) & 0xFF);
    buffer[offset++] = (uint8_t)((value >> 16) & 0xFF);
    buffer[offset++] = (uint8_t)((value >> 24) & 0xFF);
}

bool readUint16(const uint8_t *buffer, size_t length, size_t &offset, uint16_t *value)
{
    if (offset + 2 > length) {
        return false;
    }
    *value = (uint16_t)buffer[offset] | ((uint16_t)buffer[offset + 1] << 8);
    offset += 2;
    return true;
}

bool readUint32(const uint8_t *buffer, size_t length, size_t &offset, uint32_t *value)
{
    if (offset + 4 > length) {
        return false;
    }
    *value = (uint32_t)buffer[offset] | ((uint32_t)buffer[offset + 1] << 8) | ((uint32_t)buffer[offset + 2] << 16) |
             ((uint32_t)buffer[offset + 3] << 24);
    offset += 4;
    return true;
}
} // namespace

LocalLedConfigStore *localLedConfigStore = nullptr;
static LocalLedReplyDispatcher *localLedReplyDispatcher = nullptr;

LocalLedConfigStore::LocalLedConfigStore() : activeChannel(channels.getPrimaryIndex())
{
    applyDefaults(&config);
}

void LocalLedConfigStore::applyDefaults(CustomLedConfig *defaults)
{
    if (!defaults) {
        return;
    }

    defaults->node_led1_color = 0x0000FF;
    defaults->node_led2_color = 0xFF0000;
    defaults->idle_bpm = 80;
    defaults->idle_delay_ms = 0;
    defaults->notification_pulses = kLocalLedDefaultNotificationPulses;
    for (size_t i = 0; i < 8; ++i) {
        defaults->channels[i].led1_color = 0;
        defaults->channels[i].led2_color = 0;
        defaults->channels[i].notification_pulses = 0;
        defaults->channels[i].configured = false;
    }
}

bool LocalLedConfigStore::serializeConfig(const CustomLedConfig &source, uint8_t *buffer, size_t capacity, size_t *usedBytes)
{
    if (!buffer || capacity < kSerializedSize) {
        return false;
    }

    size_t offset = 0;
    writeUint32(buffer, offset, kMagic);
    writeUint16(buffer, offset, kVersion);
    writeUint16(buffer, offset, 8);
    writeUint32(buffer, offset, source.node_led1_color);
    writeUint32(buffer, offset, source.node_led2_color);
    writeUint16(buffer, offset, source.idle_bpm);
    writeUint32(buffer, offset, source.idle_delay_ms);
    buffer[offset++] = source.notification_pulses;
    for (size_t i = 0; i < 8; ++i) {
        writeUint32(buffer, offset, source.channels[i].led1_color);
        writeUint32(buffer, offset, source.channels[i].led2_color);
        buffer[offset++] = source.channels[i].notification_pulses;
        buffer[offset++] = source.channels[i].configured ? 1 : 0;
    }

    if (usedBytes) {
        *usedBytes = offset;
    }
    return true;
}

bool LocalLedConfigStore::deserializeConfig(const uint8_t *buffer, size_t length, CustomLedConfig *destination)
{
    if (!buffer || !destination || length < kLegacySerializedSize) {
        return false;
    }

    size_t offset = 0;
    uint32_t magic = 0;
    uint16_t version = 0;
    uint16_t channelCount = 0;
    if (!readUint32(buffer, length, offset, &magic) || !readUint16(buffer, length, offset, &version) ||
        !readUint16(buffer, length, offset, &channelCount)) {
        return false;
    }
    if (magic != kMagic || channelCount != 8 || (version < 1 || version > kVersion) ||
        (version >= 5 && length < kSerializedSize)) {
        return false;
    }

    CustomLedConfig decoded = {};
    applyDefaults(&decoded);
    if (!readUint32(buffer, length, offset, &decoded.node_led1_color) ||
        !readUint32(buffer, length, offset, &decoded.node_led2_color) || !readUint16(buffer, length, offset, &decoded.idle_bpm) ||
        !readUint32(buffer, length, offset, &decoded.idle_delay_ms)) {
        return false;
    }
    if (version >= 5) {
        if (offset >= length) {
            return false;
        }
        decoded.notification_pulses = buffer[offset++];
    }
    for (size_t i = 0; i < 8; ++i) {
        if (!readUint32(buffer, length, offset, &decoded.channels[i].led1_color) ||
            !readUint32(buffer, length, offset, &decoded.channels[i].led2_color) || offset >= length) {
            return false;
        }
        if (version >= 5) {
            decoded.channels[i].notification_pulses = buffer[offset++];
            if (offset >= length) {
                return false;
            }
        }
        decoded.channels[i].configured = buffer[offset++] != 0;
    }

    if (decoded.idle_bpm < 1 || decoded.idle_bpm > 600 || decoded.idle_delay_ms > 600000 ||
        decoded.notification_pulses < 1 || decoded.notification_pulses > kLocalLedMaxNotificationPulses) {
        return false;
    }
    for (size_t i = 0; i < 8; ++i) {
        if (decoded.channels[i].notification_pulses > kLocalLedMaxNotificationPulses) {
            return false;
        }
    }

    if (version == 1 && isLegacyWhiteDefaultConfig(decoded)) {
        decoded.node_led1_color = 0x0000FF;
        decoded.node_led2_color = 0xFF0000;
        decoded.idle_delay_ms = 0;
    }

    if ((version == 1 || version == 2) && isLegacyBlueRedDefaultConfig(decoded)) {
        decoded.idle_bpm = 80;
        decoded.idle_delay_ms = 0;
    }

    if (version == 3 && isCurrentBlueRedDefaultConfig(decoded)) {
        decoded.idle_delay_ms = 0;
        decoded.idle_bpm = 80;
    }

    *destination = decoded;
    return true;
}

bool LocalLedConfigStore::isSupportedChannel(uint8_t channel)
{
    return channel < 8;
}

void LocalLedConfigStore::load()
{
    CustomLedConfig loaded = {};
    applyDefaults(&loaded);

#ifdef FSCom
    concurrency::LockGuard fileGuard(spiLock);
    auto file = FSCom.open(kFileName, FILE_O_READ);
    if (file) {
        uint8_t buffer[kSerializedSize] = {};
        size_t bytesRead = file.read(buffer, sizeof(buffer));
        file.close();
        if (!deserializeConfig(buffer, bytesRead, &loaded)) {
            applyDefaults(&loaded);
        }
    }
#endif

    concurrency::LockGuard configGuard(&lock);
    config = loaded;
    activeChannel = channels.getPrimaryIndex();
}

bool LocalLedConfigStore::save()
{
    if (!powerHAL_isPowerLevelSafe()) {
        return false;
    }

    CustomLedConfig snapshot = {};
    {
        concurrency::LockGuard guard(&lock);
        snapshot = config;
    }

#ifdef FSCom
    uint8_t buffer[kSerializedSize] = {};
    size_t usedBytes = 0;
    if (!serializeConfig(snapshot, buffer, sizeof(buffer), &usedBytes)) {
        return false;
    }

    concurrency::LockGuard guard(spiLock);
    FSCom.mkdir("/prefs");
    if (FSCom.exists(kFileName)) {
        FSCom.remove(kFileName);
    }
    auto file = FSCom.open(kFileName, FILE_O_WRITE);
    if (!file) {
        return false;
    }
    size_t written = file.write(buffer, usedBytes);
    file.flush();
    file.close();
    return written == usedBytes;
#else
    return true;
#endif
}

bool LocalLedConfigStore::handleCommand(const char *text, const LocalLedCommandContext &context, LocalLedCommandResult *result)
{
    if (!result) {
        return false;
    }

    LocalLedCommandResult localResult = {};
    CustomLedConfig working = {};
    {
        concurrency::LockGuard guard(&lock);
        working = config;
    }

    if (!handleLocalLedCommand(working, context, text, &localResult)) {
        *result = localResult;
        return false;
    }

    {
        concurrency::LockGuard guard(&lock);
        if (context.has_resolved_incoming_channel && isSupportedChannel(context.resolved_incoming_channel)) {
            activeChannel = context.resolved_incoming_channel;
        }
        if (localResult.persist) {
            config = working;
        }
    }

    if (localResult.persist) {
        save();
    }

    *result = localResult;
    return localResult.handled;
}

void LocalLedConfigStore::setActiveChannel(uint8_t channel)
{
    if (!isSupportedChannel(channel)) {
        return;
    }

    concurrency::LockGuard guard(&lock);
    activeChannel = channel;
}

uint8_t LocalLedConfigStore::getActiveChannel() const
{
    concurrency::LockGuard guard(&lock);
    return activeChannel;
}

CustomLedConfig LocalLedConfigStore::getConfig() const
{
    concurrency::LockGuard guard(&lock);
    return config;
}

LocalLedEffectiveConfig LocalLedConfigStore::getEffectiveConfigForChannel(uint8_t channel) const
{
    CustomLedConfig snapshot = {};
    {
        concurrency::LockGuard guard(&lock);
        snapshot = config;
    }

    uint8_t resolvedChannel = isSupportedChannel(channel) ? channel : channels.getPrimaryIndex();
    LocalLedEffectiveConfig effective = {
        snapshot.node_led1_color,
        snapshot.node_led2_color,
        snapshot.idle_bpm,
        snapshot.idle_delay_ms,
        snapshot.notification_pulses,
        false,
        resolvedChannel,
    };
    if (snapshot.channels[resolvedChannel].configured) {
        effective.led1_color = snapshot.channels[resolvedChannel].led1_color;
        effective.led2_color = snapshot.channels[resolvedChannel].led2_color;
        if (snapshot.channels[resolvedChannel].notification_pulses > 0) {
            effective.notification_pulses = snapshot.channels[resolvedChannel].notification_pulses;
        }
        effective.configured = true;
    }
    return effective;
}

LocalLedEffectiveConfig LocalLedConfigStore::getEffectiveConfigForActiveChannel() const
{
    return getEffectiveConfigForChannel(getActiveChannel());
}

meshtastic_MeshPacket *LocalLedConfigStore::createLocalReplyPacket(const char *text, uint8_t channel, uint32_t requestId) const
{
    if (!text) {
        return nullptr;
    }

    meshtastic_MeshPacket *packet = packetPool.allocZeroed();
    if (!packet) {
        return nullptr;
    }

    packet->which_payload_variant = meshtastic_MeshPacket_decoded_tag;
    packet->id = generatePacketId();
    packet->from = nodeDB->getNodeNum();
    packet->to = NODENUM_BROADCAST;
    packet->channel = isSupportedChannel(channel) ? channel : channels.getPrimaryIndex();
    packet->rx_time = getValidTime(RTCQualityFromNet);
    packet->decoded.portnum = meshtastic_PortNum_TEXT_MESSAGE_APP;
    packet->decoded.request_id = requestId;

    size_t length = strlen(text);
    if (length > sizeof(packet->decoded.payload.bytes)) {
        length = sizeof(packet->decoded.payload.bytes);
    }
    packet->decoded.payload.size = length;
    memcpy(packet->decoded.payload.bytes, text, length);
    return packet;
}

meshtastic_MeshPacket *LocalLedConfigStore::createLocalAckPacket(uint8_t channel, uint32_t requestId) const
{
    meshtastic_MeshPacket *packet = packetPool.allocZeroed();
    if (!packet) {
        return nullptr;
    }

    meshtastic_Routing routing = meshtastic_Routing_init_default;
    routing.error_reason = meshtastic_Routing_Error_NONE;
    routing.which_variant = meshtastic_Routing_error_reason_tag;

    packet->which_payload_variant = meshtastic_MeshPacket_decoded_tag;
    packet->id = generatePacketId();
    packet->from = nodeDB->getNodeNum();
    packet->to = nodeDB->getNodeNum();
    packet->channel = isSupportedChannel(channel) ? channel : channels.getPrimaryIndex();
    packet->rx_time = getValidTime(RTCQualityFromNet);
    packet->priority = meshtastic_MeshPacket_Priority_ACK;
    packet->decoded.portnum = meshtastic_PortNum_ROUTING_APP;
    packet->decoded.request_id = requestId;
    packet->decoded.payload.size =
        pb_encode_to_bytes(packet->decoded.payload.bytes, sizeof(packet->decoded.payload.bytes), &meshtastic_Routing_msg, &routing);
    return packet;
}

bool localLedResolveIncomingChannel(const meshtastic_MeshPacket &packet, uint8_t *channelOut)
{
    uint8_t channel = packet.channel ? packet.channel : channels.getPrimaryIndex();
    if (channel >= 8) {
        return false;
    }
    if (channelOut) {
        *channelOut = channel;
    }
    return true;
}

void setupLocalLedConfigStore()
{
    if (!localLedConfigStore) {
        localLedConfigStore = new LocalLedConfigStore();
    }
    if (!localLedReplyDispatcher) {
        localLedReplyDispatcher = new LocalLedReplyDispatcher();
    }
    localLedConfigStore->load();
}

bool enqueueLocalLedReplyPacket(meshtastic_MeshPacket *packet)
{
    return localLedReplyDispatcher && localLedReplyDispatcher->enqueue(packet);
}

bool handleLocalLedPhoneCommand(const meshtastic_MeshPacket &packet, meshtastic_MeshPacket **replyPacket)
{
    if (replyPacket) {
        *replyPacket = nullptr;
    }
    if (!localLedConfigStore || packet.which_payload_variant != meshtastic_MeshPacket_decoded_tag ||
        packet.decoded.portnum != meshtastic_PortNum_TEXT_MESSAGE_APP || packet.decoded.payload.size == 0) {
        return false;
    }

    char text[256] = {};
    size_t length = packet.decoded.payload.size;
    if (length > sizeof(text) - 1) {
        length = sizeof(text) - 1;
    }
    memcpy(text, packet.decoded.payload.bytes, length);

    uint8_t resolvedChannel = 0;
    LocalLedCommandContext context = {
        localLedResolveIncomingChannel(packet, &resolvedChannel),
        resolvedChannel,
        true,
        packet.id,
        resolvedChannel,
    };
    LocalLedCommandResult result = {};
    if (!localLedConfigStore->handleCommand(text, context, &result)) {
        return false;
    }

    meshtastic_MeshPacket *ackPacket = localLedConfigStore->createLocalAckPacket(context.reply_channel, packet.id);
    if (ackPacket && service) {
        service->sendToPhone(ackPacket);
    } else if (ackPacket) {
        packetPool.release(ackPacket);
    }

    if (replyPacket && result.response[0] != '\0') {
        *replyPacket = localLedConfigStore->createLocalReplyPacket(result.response, context.reply_channel, packet.id);
    }

    return true;
}
