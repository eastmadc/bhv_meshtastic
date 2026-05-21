#include "LocalLedCommandModule.h"

#include "MeshService.h"
#include "NodeDB.h"
#include "led/LocalLedConfig.h"

#include <string.h>

ProcessMessage LocalLedCommandModule::handleReceived(const meshtastic_MeshPacket &mp)
{
    if (!localLedConfigStore || mp.which_payload_variant != meshtastic_MeshPacket_decoded_tag || !MeshService::isTextPayload(&mp) ||
        mp.decoded.payload.size == 0) {
        return ProcessMessage::CONTINUE;
    }

    char text[256] = {};
    size_t length = mp.decoded.payload.size;
    if (length > sizeof(text) - 1) {
        length = sizeof(text) - 1;
    }
    memcpy(text, mp.decoded.payload.bytes, length);

    uint8_t resolvedChannel = 0;
    LocalLedCommandContext context = {
        localLedResolveIncomingChannel(mp, &resolvedChannel),
        resolvedChannel,
        isToUs(&mp) && !isBroadcast(mp.to),
        mp.from,
        false,
        mp.id,
        resolvedChannel,
    };

    LocalLedCommandResult result = {};
    if (!localLedConfigStore->handleCommand(text, context, &result)) {
        return ProcessMessage::CONTINUE;
    }

    return result.consume_packet ? ProcessMessage::STOP : ProcessMessage::CONTINUE;
}
