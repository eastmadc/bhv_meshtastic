#include "BhvInfoPolicy.h"
#include "Channels.h"
#include "TestUtil.h"
#include "mesh-pb-constants.h"
#include <unity.h>

static meshtastic_MeshPacket makePacket(uint32_t destination = NODENUM_BROADCAST,
                                        meshtastic_PortNum portnum = meshtastic_PortNum_TEXT_MESSAGE_APP)
{
    meshtastic_MeshPacket packet = {};
    packet.to = destination;
    packet.which_payload_variant = meshtastic_MeshPacket_decoded_tag;
    packet.decoded.portnum = portnum;
    return packet;
}

static void test_blocks_local_broadcast_text_on_protected_channel()
{
    const meshtastic_MeshPacket packet = makePacket();
    TEST_ASSERT_TRUE(BhvInfoPolicy::shouldBlockOutgoingText(packet, true, true));
}

static void test_blocks_local_no_lora_broadcast_text_on_protected_channel()
{
    const meshtastic_MeshPacket packet = makePacket(NODENUM_BROADCAST_NO_LORA);
    TEST_ASSERT_TRUE(BhvInfoPolicy::shouldBlockOutgoingText(packet, true, true));
}

static void test_allows_received_or_relayed_text()
{
    const meshtastic_MeshPacket packet = makePacket();
    TEST_ASSERT_FALSE(BhvInfoPolicy::shouldBlockOutgoingText(packet, false, true));
}

static void test_allows_text_on_other_channels()
{
    const meshtastic_MeshPacket packet = makePacket();
    TEST_ASSERT_FALSE(BhvInfoPolicy::shouldBlockOutgoingText(packet, true, false));
}

static void test_allows_direct_messages()
{
    const meshtastic_MeshPacket packet = makePacket(0x12345678);
    TEST_ASSERT_FALSE(BhvInfoPolicy::shouldBlockOutgoingText(packet, true, true));
}

static void test_allows_non_text_packets()
{
    const meshtastic_MeshPacket packet = makePacket(NODENUM_BROADCAST, meshtastic_PortNum_TELEMETRY_APP);
    TEST_ASSERT_FALSE(BhvInfoPolicy::shouldBlockOutgoingText(packet, true, true));
}

static void test_blocks_compressed_text()
{
    const meshtastic_MeshPacket packet = makePacket(NODENUM_BROADCAST, meshtastic_PortNum_TEXT_MESSAGE_COMPRESSED_APP);
    TEST_ASSERT_TRUE(BhvInfoPolicy::shouldBlockOutgoingText(packet, true, true));
}

static void test_production_bhv_info_fingerprint_matches_channel_one()
{
    static const uint8_t expectedFingerprint[] = USERPREFS_BHV_INFO_PSK_SHA256;
    channels.initDefaults();
    channels.onConfigChanged();
    TEST_ASSERT_TRUE(channels.pskMatchesFingerprint(1, expectedFingerprint, sizeof(expectedFingerprint)));
    TEST_ASSERT_FALSE(channels.pskMatchesFingerprint(0, expectedFingerprint, sizeof(expectedFingerprint)));
}

void setup()
{
    initializeTestEnvironment();
    UNITY_BEGIN();
    RUN_TEST(test_blocks_local_broadcast_text_on_protected_channel);
    RUN_TEST(test_blocks_local_no_lora_broadcast_text_on_protected_channel);
    RUN_TEST(test_allows_received_or_relayed_text);
    RUN_TEST(test_allows_text_on_other_channels);
    RUN_TEST(test_allows_direct_messages);
    RUN_TEST(test_allows_non_text_packets);
    RUN_TEST(test_blocks_compressed_text);
    RUN_TEST(test_production_bhv_info_fingerprint_matches_channel_one);
    exit(UNITY_END());
}

void loop() {}
