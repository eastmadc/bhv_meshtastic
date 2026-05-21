#pragma once

#include "concurrency/Lock.h"
#include "mesh/MeshTypes.h"
#include "mesh/generated/meshtastic/mesh.pb.h"
#include <stddef.h>
#include <stdint.h>

static constexpr uint8_t kLocalLedDefaultNotificationPulses = 3;
static constexpr uint8_t kLocalLedDefaultSendPulses = 1;
static constexpr uint8_t kLocalLedMaxNotificationPulses = 20;
static constexpr uint8_t kLocalLedDirectMessageIndex = 8;
static constexpr uint8_t kLocalLedDirectMessageUserBaseIndex = 9;
static constexpr uint8_t kLocalLedDirectMessageUserCapacity = 10;

struct ChannelLedConfig {
    uint32_t led1_color;
    uint32_t led2_color;
    uint8_t notification_pulses;
    uint8_t send_pulses;
    bool configured;
};

struct CustomLedConfig {
    uint32_t node_led1_color;
    uint32_t node_led2_color;
    uint16_t idle_bpm;
    uint32_t idle_delay_ms;
    uint8_t notification_pulses;
    uint8_t send_pulses;
    ChannelLedConfig channels[8];
    ChannelLedConfig direct_message;
    uint32_t direct_message_nodes[kLocalLedDirectMessageUserCapacity];
    ChannelLedConfig direct_message_users[kLocalLedDirectMessageUserCapacity];
};

struct LocalLedCommandContext {
    bool has_resolved_incoming_channel;
    uint8_t resolved_incoming_channel;
    bool has_direct_message_peer;
    uint32_t direct_message_peer;
    bool local_client_origin;
    uint32_t request_id;
    uint8_t reply_channel;
};

struct LocalLedCommandResult {
    bool handled;
    bool consume_packet;
    bool persist;
    char response[256];
};

struct LocalLedEffectiveConfig {
    uint32_t led1_color;
    uint32_t led2_color;
    uint16_t idle_bpm;
    uint32_t idle_delay_ms;
    uint8_t notification_pulses;
    uint8_t send_pulses;
    bool configured;
    uint8_t channel_index;
};

bool localLedResolveIncomingChannel(const meshtastic_MeshPacket &packet, uint8_t *channelOut);

class LocalLedConfigStore
{
  public:
    LocalLedConfigStore();

    void load();
    bool save();
    bool handleCommand(const char *text, const LocalLedCommandContext &context, LocalLedCommandResult *result);

    void setActiveChannel(uint8_t channel);
    uint8_t getActiveChannel() const;
    CustomLedConfig getConfig() const;
    LocalLedEffectiveConfig getEffectiveConfigForChannel(uint8_t channel) const;
    LocalLedEffectiveConfig getEffectiveConfigForDirectMessage() const;
    LocalLedEffectiveConfig getEffectiveConfigForDirectMessage(uint32_t nodeNum) const;
    LocalLedEffectiveConfig getEffectiveConfigForActiveChannel() const;

    meshtastic_MeshPacket *createLocalReplyPacket(const char *text, uint8_t channel, uint32_t requestId, uint32_t from,
                                                  uint32_t to) const;
    meshtastic_MeshPacket *createLocalAckPacket(uint8_t channel, uint32_t requestId) const;

    static void applyDefaults(CustomLedConfig *config);
    static bool serializeConfig(const CustomLedConfig &config, uint8_t *buffer, size_t capacity, size_t *usedBytes);
    static bool deserializeConfig(const uint8_t *buffer, size_t length, CustomLedConfig *config);

  private:
    static bool isSupportedChannel(uint8_t channel);

    mutable concurrency::Lock lock;
    CustomLedConfig config;
    uint8_t activeChannel;
};

extern LocalLedConfigStore *localLedConfigStore;

void setupLocalLedConfigStore();
bool handleLocalLedPhoneCommand(const meshtastic_MeshPacket &packet, meshtastic_MeshPacket **replyPacket);
bool enqueueLocalLedReplyPacket(meshtastic_MeshPacket *packet);
