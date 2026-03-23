#pragma once

#include "SinglePortModule.h"

class LocalLedCommandModule : public SinglePortModule
{
  public:
    LocalLedCommandModule() : SinglePortModule("LocalLedCommandModule", meshtastic_PortNum_TEXT_MESSAGE_APP) {}

  protected:
    ProcessMessage handleReceived(const meshtastic_MeshPacket &mp) override;
};
