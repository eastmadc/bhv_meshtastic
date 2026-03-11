#include "configuration.h"

#if !MESHTASTIC_EXCLUDE_HEALTH_TELEMETRY && !defined(ARCH_PORTDUINO)

#pragma once
#include "../mesh/generated/meshtastic/telemetry.pb.h"
#include "BaseTelemetryModule.h"
#include "NodeDB.h"
#include "ProtobufModule.h"
#include "Observer.h"
#include "mesh/MeshModule.h"
#include <OLEDDisplay.h>
#include <OLEDDisplayUi.h>

class HealthTelemetryModule : private concurrency::OSThread,
                              public BaseTelemetryModule,
                              public ProtobufModule<meshtastic_Telemetry>,
                              public Observable<const UIFrameEvent *>
{
    CallbackObserver<HealthTelemetryModule, const meshtastic::Status *> nodeStatusObserver =
        CallbackObserver<HealthTelemetryModule, const meshtastic::Status *>(this, &HealthTelemetryModule::handleStatusUpdate);

  public:
    HealthTelemetryModule()
        : concurrency::OSThread("HealthTelemetry"),
          ProtobufModule("HealthTelemetry", meshtastic_PortNum_TELEMETRY_APP, &meshtastic_Telemetry_msg)
    {
        lastMeasurementPacket = nullptr;
        nodeStatusObserver.observe(&nodeStatus->onNewStatus);
        setIntervalFromNow(10 * 1000);
    }

#if !HAS_SCREEN
    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y);
#else
    virtual void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y) override;
#endif

    virtual bool wantUIFrame() override;
    virtual Observable<const UIFrameEvent *> *getUIFrameObservable() override { return this; }

  protected:
    /** Called to handle a particular incoming message
    @return true if you've guaranteed you've handled this message and no other handlers should be considered for it
    */
    virtual bool handleReceivedProtobuf(const meshtastic_MeshPacket &mp, meshtastic_Telemetry *p) override;
    virtual int32_t runOnce() override;
    /** Called to get current Health telemetry data
    @return true if it contains valid data
    */
    bool getHealthTelemetry(meshtastic_Telemetry *m);
    virtual meshtastic_MeshPacket *allocReply() override;
    /**
     * Send our Telemetry into the mesh
     */
    bool sendTelemetry(NodeNum dest = NODENUM_BROADCAST, bool wantReplies = false);
    bool updateLocalMeasurement();

  private:
    bool firstTime = 1;
    meshtastic_MeshPacket *lastMeasurementPacket;
    uint32_t sensorServiceIntervalMs = 200;                 // Service MAX3010x FIFO/algorithm every 200ms
    uint32_t healthPollIntervalMs = 1 * 1000;               // Refresh local OLED measurement packet every second
    uint32_t sendToPhoneIntervalMs = SECONDS_IN_MINUTE * 1000; // Send to phone every minute
    uint32_t lastLocalMeasurementAttemptMs = 0;
    uint32_t lastSentToPhone = 0;
    uint32_t sensor_read_error_count = 0;

    // HR sensor auto-navigate to health screen
    bool lastHrEngaged = false;
    bool hrAutoWokeScreen = false;
    uint8_t previousFrameIndex = 0;
};

extern HealthTelemetryModule *healthTelemetryModule;

#endif
