#pragma once

#include "MeshTypes.h"

namespace BhvInfoPolicy
{
/**
 * Return true when an outgoing packet is a locally originated broadcast text message
 * targeting the protected BHV Info channel.
 *
 * Channel identification is supplied separately so this policy stays independent of
 * the channel's local index and display name.
 */
bool shouldBlockOutgoingText(const meshtastic_MeshPacket &packet, bool locallyOriginated, bool protectedChannel);
} // namespace BhvInfoPolicy
