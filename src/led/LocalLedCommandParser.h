#pragma once

#include "LocalLedConfig.h"

bool handleLocalLedCommand(CustomLedConfig &config, const LocalLedCommandContext &context, const char *text,
                           LocalLedCommandResult *result);
