# Method Channel Registration Guide — Audio Sync Platform

## Purpose
이 문서는 `mobile_app/` Flutter shell이 fake bridge 모드에서 real native bridge 모드로 전환될 때,
iOS/Android에서 method channel을 어떻게 등록하고 연결해야 하는지 설명한다.

이 가이드는 현재 저장소에 있는 다음 계약을 연결한다.
- `.omx/plans/native-bridge-interface-audio-sync-v1.md`
- `mobile_app/lib/native/*/*_method_channel.dart`
- `mobile_app/ios/Runner/AudioSyncBridges/*.swift`
- `mobile_app/android/app/src/main/kotlin/com/example/audiosyncplatform/bridges/*.kt`

---

## 1. Channels to Register
Must register these four channels:
- `audio_sync/recorder`
- `audio_sync/time_sync`
- `audio_sync/route`
- `audio_sync/beep`

Each channel must expose the methods already assumed by Flutter:

### Recorder channel
- `prepareRecorder`
- `startRecording`
- `stopRecording`
- `getRecorderState`

### Time sync channel
- `measureTimeSync`

### Route channel
- `inspectCurrentRoute`
- `inspectProcessingFlags`

### Beep channel
- `scheduleSyncBeep`
- optional `playSyncBeepNow`

---

## 2. iOS Registration (Swift)
### Target location
The scaffold currently contains placeholder bridge classes under:
- `mobile_app/ios/Runner/AudioSyncBridges/RecorderBridge.swift`
- `mobile_app/ios/Runner/AudioSyncBridges/TimeSyncBridge.swift`
- `mobile_app/ios/Runner/AudioSyncBridges/RouteInspectorBridge.swift`
- `mobile_app/ios/Runner/AudioSyncBridges/SyncBeepBridge.swift`

### Registration pattern
Inside `AppDelegate.swift` (or `SceneDelegate`/plugin bootstrap depending on Flutter template), register channels against the Flutter engine messenger.

### Sketch
```swift
import Flutter
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate {
  private let recorderBridge = RecorderBridge()
  private let timeSyncBridge = TimeSyncBridge()
  private let routeBridge = RouteInspectorBridge()
  private let beepBridge = SyncBeepBridge()

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    let controller = window?.rootViewController as! FlutterViewController
    let messenger = controller.binaryMessenger

    let recorderChannel = FlutterMethodChannel(name: "audio_sync/recorder", binaryMessenger: messenger)
    recorderChannel.setMethodCallHandler { [weak self] call, result in
      self?.handleRecorder(call: call, result: result)
    }

    let timeSyncChannel = FlutterMethodChannel(name: "audio_sync/time_sync", binaryMessenger: messenger)
    timeSyncChannel.setMethodCallHandler { [weak self] call, result in
      self?.handleTimeSync(call: call, result: result)
    }

    let routeChannel = FlutterMethodChannel(name: "audio_sync/route", binaryMessenger: messenger)
    routeChannel.setMethodCallHandler { [weak self] call, result in
      self?.handleRoute(call: call, result: result)
    }

    let beepChannel = FlutterMethodChannel(name: "audio_sync/beep", binaryMessenger: messenger)
    beepChannel.setMethodCallHandler { [weak self] call, result in
      self?.handleBeep(call: call, result: result)
    }

    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }
}
```

### Dispatch pattern
Each handler should:
1. cast `call.arguments` to `[String: Any]`
2. switch on `call.method`
3. call the corresponding bridge function
4. return structured JSON payload
5. convert native exceptions into `FlutterError`

### Example recorder handler
```swift
private func handleRecorder(call: FlutterMethodCall, result: @escaping FlutterResult) {
  do {
    let args = call.arguments as? [String: Any] ?? [:]
    switch call.method {
    case "prepareRecorder":
      result(try recorderBridge.prepareRecorder(args))
    case "startRecording":
      result(try recorderBridge.startRecording(args))
    case "stopRecording":
      result(try recorderBridge.stopRecording())
    case "getRecorderState":
      result(["ok": true, "recorderState": "idle"])
    default:
      result(FlutterMethodNotImplemented)
    }
  } catch {
    result(FlutterError(code: "native_bridge_error", message: String(describing: error), details: nil))
  }
}
```

---

## 3. Android Registration (Kotlin)
### Target location
The scaffold currently contains placeholder bridge classes under:
- `mobile_app/android/app/src/main/kotlin/com/example/audiosyncplatform/bridges/RecorderBridge.kt`
- `mobile_app/android/app/src/main/kotlin/com/example/audiosyncplatform/bridges/TimeSyncBridge.kt`
- `mobile_app/android/app/src/main/kotlin/com/example/audiosyncplatform/bridges/RouteInspectorBridge.kt`
- `mobile_app/android/app/src/main/kotlin/com/example/audiosyncplatform/bridges/SyncBeepBridge.kt`

### Registration pattern
Inside `MainActivity.kt` or a dedicated Flutter plugin registration file, attach channels to `flutterEngine.dartExecutor.binaryMessenger`.

### Sketch
```kotlin
class MainActivity: FlutterActivity() {
  private val recorderBridge = RecorderBridge()
  private val timeSyncBridge = TimeSyncBridge()
  private val routeBridge = RouteInspectorBridge()
  private val beepBridge = SyncBeepBridge()

  override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
    super.configureFlutterEngine(flutterEngine)

    MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "audio_sync/recorder")
      .setMethodCallHandler { call, result -> handleRecorder(call, result) }

    MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "audio_sync/time_sync")
      .setMethodCallHandler { call, result -> handleTimeSync(call, result) }

    MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "audio_sync/route")
      .setMethodCallHandler { call, result -> handleRoute(call, result) }

    MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "audio_sync/beep")
      .setMethodCallHandler { call, result -> handleBeep(call, result) }
  }
}
```

### Example recorder handler
```kotlin
private fun handleRecorder(call: MethodCall, result: MethodChannel.Result) {
  try {
    val args = call.arguments as? Map<String, Any?> ?: emptyMap()
    when (call.method) {
      "prepareRecorder" -> result.success(recorderBridge.prepareRecorder(args))
      "startRecording" -> result.success(recorderBridge.startRecording(args))
      "stopRecording" -> result.success(recorderBridge.stopRecording())
      "getRecorderState" -> result.success(mapOf("ok" to true, "recorderState" to "idle"))
      else -> result.notImplemented()
    }
  } catch (t: Throwable) {
    result.error("native_bridge_error", t.message, null)
  }
}
```

---

## 4. Error Mapping Rules
Every channel should map native failures into the shared error shape from `.omx/plans/native-bridge-interface-audio-sync-v1.md`.

### Preferred error payload shape
```json
{
  "ok": false,
  "code": "mic_route_bluetooth_not_allowed",
  "message": "Bluetooth route is not allowed in research mode.",
  "severity": "blocker"
}
```

### Flutter-side rule
- `MethodChannel` exceptions should be converted into `NativeBridgeException`
- if the native side returns `{ ok: false, ... }`, the Dart wrapper should also turn it into a typed exception or degraded state object

---

## 5. Registration Checklist
### iOS
- [ ] `FlutterMethodChannel` created for all 4 channels
- [ ] all required methods switched
- [ ] `FlutterMethodNotImplemented` used for unknown methods
- [ ] native bridge errors mapped to `FlutterError`
- [ ] app launches without crashing when fake mode is replaced

### Android
- [ ] `MethodChannel` created for all 4 channels
- [ ] all required methods switched
- [ ] `result.notImplemented()` used for unknown methods
- [ ] exceptions mapped to `result.error(...)`
- [ ] app launches without crashing when fake mode is replaced

---

## 6. Safe Integration Order
1. keep `AppBootstrap.runtimeMode = AppRuntimeMode.fake`
2. register channels on iOS and Android without switching runtime mode yet
3. add one smoke screen or debug action that pings `getRecorderState`
4. switch only one bridge at a time from fake to method-channel
5. confirm payload matches the Dart DTO expectations
6. only after recorder + route + time sync are stable, switch beep and recording flow together

---

## 7. First Real Smoke Test
Once registration exists, first smoke test should be minimal:
- app boots
- Flutter can call `getRecorderState`
- Flutter can call `measureTimeSync`
- Flutter can call `inspectCurrentRoute`
- Flutter can call `scheduleSyncBeep`
- no real recording session yet

Only after this should `startRecording` be exercised.

---

## 8. Decision Rule
If method-channel registration is stable but recorder payload fidelity is weak:
- keep Flutter shell
- move recorder implementation deeper into native module
- do not abandon the shell immediately

If method-channel registration itself is unstable across both platforms:
- revisit app bootstrap strategy before further UI investment

## Additional Reference
- `docs/mobile/method-channel-registration-checklist.md`

## Additional Reference
- `docs/mobile/native-smoke-evidence-template.md`
