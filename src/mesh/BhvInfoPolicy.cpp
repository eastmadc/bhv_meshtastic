#include "BhvInfoPolicy.h"

#include "mesh-pb-constants.h"

namespace BhvInfoPolicy
{
bool shouldBlockOutgoingText(const meshtastic_MeshPacket &packet, bool locallyOriginated, bool protectedChannel)
{
    if (!locallyOriginated || !protectedChannel) {
        return false;
    }

    const bool broadcast = packet.to == NODENUM_BROADCAST || packet.to == NODENUM_BROADCAST_NO_LORA;
    if (!broadcast || packet.which_payload_variant != meshtastic_MeshPacket_decoded_tag) {
        return false;
    }

    return packet.decoded.portnum == meshtastic_PortNum_TEXT_MESSAGE_APP ||
           packet.decoded.portnum == meshtastic_PortNum_TEXT_MESSAGE_COMPRESSED_APP;
}
} // namespace BhvInfoPolicy
