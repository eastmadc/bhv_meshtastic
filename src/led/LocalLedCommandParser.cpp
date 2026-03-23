#include "led/LocalLedCommandParser.h"

#include <ctype.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>

namespace
{
struct NamedColor {
    const char *name;
    uint32_t value;
};

static const NamedColor kNamedColors[] = {
    {"red", 0xFF0000},       {"orange", 0xFF8000}, {"yellow", 0xFFFF00}, {"green", 0x00FF00},    {"blue", 0x0000FF},
    {"indigo", 0x4B0082},    {"violet", 0x8F00FF}, {"purple", 0x8000FF}, {"pink", 0xFF4080},     {"white", 0xFFFFFF},
    {"warmwhite", 0xFFF0D0}, {"cyan", 0x00FFFF},   {"magenta", 0xFF00FF}, {"teal", 0x008080},     {"lime", 0x80FF00},
    {"amber", 0xFFBF00},     {"gold", 0xFFD700},   {"off", 0x000000},
};

static const char *kHelpText =
    "#! set node led <c1> [c2]\n#! get node [led|idle_bpm|idle_delay]\n#! set node idle_bpm <n>\n#! set node idle_delay <ms>\n#! "
    "set ch [n] led <c1> [c2]\n#! get ch [n] [led]\n#! clear ch [n] led\n#! help colors";
static const char *kColorsText =
    "colors: red orange yellow green blue indigo violet purple pink white warmwhite cyan magenta teal lime amber gold off or "
    "#RRGGBB";

bool isCommandPrefix(const char *text)
{
    return text && text[0] == '#' && text[1] == '!';
}

void setResponse(LocalLedCommandResult *result, bool persist, const char *format, ...)
{
    va_list args;
    va_start(args, format);
    vsnprintf(result->response, sizeof(result->response), format, args);
    va_end(args);
    result->handled = true;
    result->consume_packet = true;
    result->persist = persist;
}

void setUnknown(LocalLedCommandResult *result)
{
    setResponse(result, false, "ERR unknown command");
}

void formatColor(char *buffer, size_t bufferSize, uint32_t color)
{
    snprintf(buffer, bufferSize, "#%06X", (unsigned int)(color & 0xFFFFFF));
}

bool parseUnsigned(const char *text, uint32_t *value)
{
    if (!text || !*text) {
        return false;
    }
    uint32_t parsed = 0;
    for (const char *cursor = text; *cursor; ++cursor) {
        if (!isdigit((unsigned char)*cursor)) {
            return false;
        }
        parsed = (parsed * 10U) + (uint32_t)(*cursor - '0');
    }
    *value = parsed;
    return true;
}

bool parseChannelToken(const char *text, uint8_t *channel)
{
    uint32_t parsed = 0;
    if (!parseUnsigned(text, &parsed)) {
        return false;
    }
    if (parsed > 7) {
        *channel = 0xFF;
        return true;
    }
    *channel = (uint8_t)parsed;
    return true;
}

bool parseHexColor(const char *text, uint32_t *color)
{
    if (!text || strlen(text) != 7 || text[0] != '#') {
        return false;
    }
    uint32_t value = 0;
    for (size_t i = 1; i < 7; ++i) {
        char c = text[i];
        uint32_t digit = 0;
        if (c >= '0' && c <= '9') {
            digit = (uint32_t)(c - '0');
        } else if (c >= 'A' && c <= 'F') {
            digit = (uint32_t)(c - 'A' + 10);
        } else if (c >= 'a' && c <= 'f') {
            digit = (uint32_t)(c - 'a' + 10);
        } else {
            return false;
        }
        value = (value << 4) | digit;
    }
    *color = value;
    return true;
}

bool parseNamedColor(const char *text, uint32_t *color)
{
    for (size_t i = 0; i < sizeof(kNamedColors) / sizeof(kNamedColors[0]); ++i) {
        if (strcasecmp(text, kNamedColors[i].name) == 0) {
            *color = kNamedColors[i].value;
            return true;
        }
    }
    return false;
}

bool parseColor(const char *text, uint32_t *color)
{
    return parseHexColor(text, color) || parseNamedColor(text, color);
}

uint8_t tokenize(char *text, char *tokens[], uint8_t maxTokens)
{
    uint8_t count = 0;
    char *cursor = text;
    while (*cursor && count < maxTokens) {
        while (*cursor == ' ' || *cursor == '\t') {
            ++cursor;
        }
        if (!*cursor) {
            break;
        }
        tokens[count++] = cursor;
        while (*cursor && *cursor != ' ' && *cursor != '\t') {
            ++cursor;
        }
        if (!*cursor) {
            break;
        }
        *cursor++ = '\0';
    }
    return count;
}

bool resolveChannel(const LocalLedCommandContext &context, bool hasExplicitChannel, uint8_t explicitChannel, uint8_t *targetChannel,
                    LocalLedCommandResult *result)
{
    if (hasExplicitChannel) {
        if (explicitChannel > 7) {
            setResponse(result, false, "ERR invalid channel");
            return false;
        }
        *targetChannel = explicitChannel;
        return true;
    }
    if (!context.has_resolved_incoming_channel) {
        setResponse(result, false, "ERR no active channel");
        return false;
    }
    *targetChannel = context.resolved_incoming_channel;
    return true;
}

void assignColors(uint32_t *led1, uint32_t *led2, uint32_t first, bool hasSecond, uint32_t second)
{
    *led1 = first;
    *led2 = hasSecond ? second : first;
}

void handleNodeGet(const CustomLedConfig &config, uint8_t argc, char *argv[], LocalLedCommandResult *result)
{
    char led1[8] = {};
    char led2[8] = {};
    formatColor(led1, sizeof(led1), config.node_led1_color);
    formatColor(led2, sizeof(led2), config.node_led2_color);

    if (argc == 0) {
        setResponse(result, false, "node led led1=%s led2=%s idle_bpm=%u idle_delay=%lu", led1, led2, config.idle_bpm,
                    (unsigned long)config.idle_delay_ms);
        return;
    }
    if (argc != 1) {
        setUnknown(result);
        return;
    }
    if (strcasecmp(argv[0], "led") == 0) {
        setResponse(result, false, "node led led1=%s led2=%s", led1, led2);
        return;
    }
    if (strcasecmp(argv[0], "idle_bpm") == 0) {
        setResponse(result, false, "node idle_bpm=%u", config.idle_bpm);
        return;
    }
    if (strcasecmp(argv[0], "idle_delay") == 0) {
        setResponse(result, false, "node idle_delay=%lu", (unsigned long)config.idle_delay_ms);
        return;
    }
    setUnknown(result);
}

void handleNodeSet(CustomLedConfig &config, uint8_t argc, char *argv[], LocalLedCommandResult *result)
{
    if (argc == 0) {
        setUnknown(result);
        return;
    }

    if (strcasecmp(argv[0], "led") == 0) {
        if (argc == 1) {
            setResponse(result, false, "ERR missing value");
            return;
        }
        if (argc > 3) {
            setResponse(result, false, "ERR too many colors");
            return;
        }

        uint32_t color1 = 0;
        uint32_t color2 = 0;
        if (!parseColor(argv[1], &color1) || (argc == 3 && !parseColor(argv[2], &color2))) {
            setResponse(result, false, "ERR invalid color");
            return;
        }
        assignColors(&config.node_led1_color, &config.node_led2_color, color1, argc == 3, color2);

        char led1[8] = {};
        char led2[8] = {};
        formatColor(led1, sizeof(led1), config.node_led1_color);
        formatColor(led2, sizeof(led2), config.node_led2_color);
        setResponse(result, true, "OK node led led1=%s led2=%s", led1, led2);
        return;
    }

    if (strcasecmp(argv[0], "idle_bpm") == 0) {
        uint32_t value = 0;
        if (argc == 1) {
            setResponse(result, false, "ERR missing value");
            return;
        }
        if (argc != 2 || !parseUnsigned(argv[1], &value) || value < 1 || value > 600) {
            setResponse(result, false, "ERR invalid idle_bpm");
            return;
        }
        config.idle_bpm = (uint16_t)value;
        setResponse(result, true, "OK node idle_bpm=%u", config.idle_bpm);
        return;
    }

    if (strcasecmp(argv[0], "idle_delay") == 0) {
        uint32_t value = 0;
        if (argc == 1) {
            setResponse(result, false, "ERR missing value");
            return;
        }
        if (argc != 2 || !parseUnsigned(argv[1], &value) || value > 600000) {
            setResponse(result, false, "ERR invalid idle_delay");
            return;
        }
        config.idle_delay_ms = value;
        setResponse(result, true, "OK node idle_delay=%lu", (unsigned long)config.idle_delay_ms);
        return;
    }

    setUnknown(result);
}

void formatChannelResponse(const CustomLedConfig &config, uint8_t channel, LocalLedCommandResult *result)
{
    uint32_t led1 = config.node_led1_color;
    uint32_t led2 = config.node_led2_color;
    bool configured = config.channels[channel].configured;
    if (configured) {
        led1 = config.channels[channel].led1_color;
        led2 = config.channels[channel].led2_color;
    }

    char led1Text[8] = {};
    char led2Text[8] = {};
    formatColor(led1Text, sizeof(led1Text), led1);
    formatColor(led2Text, sizeof(led2Text), led2);
    setResponse(result, false, "ch=%u led led1=%s led2=%s configured=%s", channel, led1Text, led2Text,
                configured ? "true" : "false");
}

void handleChannelGet(const CustomLedConfig &config, const LocalLedCommandContext &context, uint8_t argc, char *argv[],
                      LocalLedCommandResult *result)
{
    uint8_t index = 0;
    bool hasExplicitChannel = false;
    uint8_t explicitChannel = 0;

    if (argc > 0 && parseChannelToken(argv[0], &explicitChannel)) {
        hasExplicitChannel = true;
        index = 1;
    }

    uint8_t targetChannel = 0;
    if (!resolveChannel(context, hasExplicitChannel, explicitChannel, &targetChannel, result)) {
        return;
    }

    if (argc == index) {
        formatChannelResponse(config, targetChannel, result);
        return;
    }
    if (argc == index + 1 && strcasecmp(argv[index], "led") == 0) {
        formatChannelResponse(config, targetChannel, result);
        return;
    }
    setUnknown(result);
}

void handleChannelSet(CustomLedConfig &config, const LocalLedCommandContext &context, uint8_t argc, char *argv[],
                      LocalLedCommandResult *result)
{
    uint8_t index = 0;
    bool hasExplicitChannel = false;
    uint8_t explicitChannel = 0;

    if (argc > 0 && parseChannelToken(argv[0], &explicitChannel)) {
        hasExplicitChannel = true;
        index = 1;
    }

    uint8_t targetChannel = 0;
    if (!resolveChannel(context, hasExplicitChannel, explicitChannel, &targetChannel, result)) {
        return;
    }

    if (argc <= index || strcasecmp(argv[index], "led") != 0) {
        setUnknown(result);
        return;
    }
    if (argc == index + 1) {
        setResponse(result, false, "ERR missing value");
        return;
    }
    if (argc > index + 3) {
        setResponse(result, false, "ERR too many colors");
        return;
    }

    uint32_t color1 = 0;
    uint32_t color2 = 0;
    if (!parseColor(argv[index + 1], &color1) || (argc == index + 3 && !parseColor(argv[index + 2], &color2))) {
        setResponse(result, false, "ERR invalid color");
        return;
    }

    assignColors(&config.channels[targetChannel].led1_color, &config.channels[targetChannel].led2_color, color1,
                 argc == index + 3, color2);
    config.channels[targetChannel].configured = true;

    char led1[8] = {};
    char led2[8] = {};
    formatColor(led1, sizeof(led1), config.channels[targetChannel].led1_color);
    formatColor(led2, sizeof(led2), config.channels[targetChannel].led2_color);
    setResponse(result, true, "OK ch=%u led led1=%s led2=%s", targetChannel, led1, led2);
}

void handleChannelClear(CustomLedConfig &config, const LocalLedCommandContext &context, uint8_t argc, char *argv[],
                        LocalLedCommandResult *result)
{
    uint8_t index = 0;
    bool hasExplicitChannel = false;
    uint8_t explicitChannel = 0;

    if (argc > 0 && parseChannelToken(argv[0], &explicitChannel)) {
        hasExplicitChannel = true;
        index = 1;
    }

    uint8_t targetChannel = 0;
    if (!resolveChannel(context, hasExplicitChannel, explicitChannel, &targetChannel, result)) {
        return;
    }

    if (argc != index + 1 || strcasecmp(argv[index], "led") != 0) {
        setUnknown(result);
        return;
    }

    config.channels[targetChannel].led1_color = 0;
    config.channels[targetChannel].led2_color = 0;
    config.channels[targetChannel].configured = false;
    setResponse(result, true, "OK ch=%u led cleared", targetChannel);
}
} // namespace

bool handleLocalLedCommand(CustomLedConfig &config, const LocalLedCommandContext &context, const char *text,
                           LocalLedCommandResult *result)
{
    if (!result) {
        return false;
    }

    memset(result, 0, sizeof(*result));
    if (!isCommandPrefix(text)) {
        return false;
    }

    char buffer[256] = {};
    strncpy(buffer, text + 2, sizeof(buffer) - 1);
    char *tokens[8] = {};
    const uint8_t tokenCount = tokenize(buffer, tokens, 8);
    if (tokenCount == 0) {
        setUnknown(result);
        return true;
    }

    if (strcasecmp(tokens[0], "help") == 0) {
        if (tokenCount == 1) {
            setResponse(result, false, "%s", kHelpText);
        } else if (tokenCount == 2 && strcasecmp(tokens[1], "colors") == 0) {
            setResponse(result, false, "%s", kColorsText);
        } else {
            setUnknown(result);
        }
        return true;
    }

    if (tokenCount < 2) {
        setUnknown(result);
        return true;
    }

    const char *verb = tokens[0];
    const char *scope = tokens[1];
    char **argv = tokenCount > 2 ? &tokens[2] : nullptr;
    uint8_t argc = tokenCount > 2 ? (uint8_t)(tokenCount - 2) : 0;

    if (strcasecmp(scope, "node") == 0) {
        if (strcasecmp(verb, "get") == 0) {
            handleNodeGet(config, argc, argv, result);
            return true;
        }
        if (strcasecmp(verb, "set") == 0) {
            handleNodeSet(config, argc, argv, result);
            return true;
        }
        setUnknown(result);
        return true;
    }

    if (strcasecmp(scope, "ch") == 0) {
        if (strcasecmp(verb, "get") == 0) {
            handleChannelGet(config, context, argc, argv, result);
            return true;
        }
        if (strcasecmp(verb, "set") == 0) {
            handleChannelSet(config, context, argc, argv, result);
            return true;
        }
        if (strcasecmp(verb, "clear") == 0) {
            handleChannelClear(config, context, argc, argv, result);
            return true;
        }
        setUnknown(result);
        return true;
    }

    setUnknown(result);
    return true;
}
