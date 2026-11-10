// ============================================
// 1. DOM 요소 선택 및 상수
// ============================================

// 녹음 제어 버튼
const recordCancelBtn = document.getElementById("recordCancelBtn");
const recordCompleteBtn = document.getElementById("recordCompleteBtn");
const pauseBtn = document.getElementById("pause-btn");
const PauseBtnImg = document.querySelector("#pause-btn img");
const uploadListBtn = document.getElementById("upload-list-btn");

// 녹음 상태 표시
const recordingTime = document.querySelector(".recording-time");
const recordingStatusCircle = document.querySelector(
  ".recording-status-circle"
);
const remainTimeBar = document.getElementById("remainTimeBar");
const remainTimeText = document.querySelector(".remain-time-text p:last-child");

// 녹음 중 웨이브
const waveCanvas = document.getElementById("waveCanvas");

// 알림
const noti = document.querySelector(".noti");
const notiArea = document.querySelector(".noti-area");

// 세그먼트 정보
const segmentInfo = document.querySelector(".segment-info");

// 설정 메뉴 관련
const titleText = document.getElementById("titleText");
const settingBtn = document.getElementById("settingBtn");
const topBtn = document.getElementById("topBtn");
const minimizeBtn = document.getElementById("minimizeBtn");
const settingsMenu = document.getElementById("settings-menu");
const settingsAotItems = document.getElementById("settings-aot-items");
const settingsMuteItems = document.getElementById("settings-mute-items");

// 1뎁스 트리거 버튼들
const alwaysOnTab = document.getElementById("alwaysOnTab");
const muteTab = document.getElementById("muteTab");

// 설정 버튼 관련
const closeAppBtn = document.getElementById("closeAppBtn");
const changeDeviceBtn = document.getElementById("changeDeviceBtn");
const logoutBtn = document.getElementById("logoutBtn");
const aotStateText = document.getElementById("aotStateText");
const muteStateText = document.getElementById("muteStateText");
const aotItem1 = document.getElementById("aot-item-1");
const aotItem2 = document.getElementById("aot-item-2");
const muteItem1 = document.getElementById("mute-item-1");
const muteItem2 = document.getElementById("mute-item-2");
const micIcon = document.getElementById("micIcon");
const sysIcon = document.getElementById("sysIcon");

// 언어 메뉴 (MULTI_LANG_ENABLED 일 때만 보임)
const languageTab = document.getElementById("languageTab");
const languageStateText = document.getElementById("languageStateText");
const settingsLanguageItems = document.getElementById("settings-language-items");

// 화면 문구 (src/locales/*.json, preload 의 window.i18n)
const t = (key, params) => window.i18n.t(key, params);

// 레벨 미터
const micMeter = document.getElementById("micMeter");
const sysMeter = document.getElementById("sysMeter");

// 상수
const TOTAL_RECORD_MS = 3 * 60 * 60 * 1000; // 총 녹음 가능 시간: 3시간 (ms)
const SEGMENT_DURATION_MS = 3 * 60 * 1000; // 3분
// const TOTAL_RECORD_MS = 30 * 1000; // 30초(테스트 용)
// const SEGMENT_DURATION_MS = 30 * 1000; // 30초
const RESUME_SMOOTH_WINDOW_MS = 1500; // 재개 후 스무딩 지속 시간
const MAX_STEP_PER_TICK_MS = 250; // 100ms 틱당 최대 증가량
const HELPER_SILENCE_THRESHOLD = 0.02; // Helper 무음 임계값 RMS 기준 (~ -34 dBFS)
const SYSTEM_LEVEL_THRESHOLD = 0.003; // 시스템 소리 파형 기준 (~ -50 dBFS). 잡음 바닥이 없어 마이크보다 낮게 둔다

// ============================================
// 2. 전역 변수
// ============================================

// 녹음 상태
let isRecording = false;
let isPaused = false;
let startTime = null;
let pausedTime = 0;
let currentSegment = 1;
let recordingTimer = null;
let stopType = "";
let recordId = null;
let outputDir = "";
let sessionId = null;

// 시간 표시 관련
let maxRecordingDuration = 0;
let useProgressClock = false;
let lastProgressSeconds = 0;
let lastFileSeconds = 0;
let timeCompleteLogged = false;
let displayedElapsedMs = 0;
let smoothingActive = false;
let smoothingEndAt = 0;

// 오류 상태
let stoppedByLowDisk = false;
let stoppedByDeviceDisconnected = false;
let isStoppedByError = false;
let isStoppedByMaxDuration = false;

// UI 상태
let isTop = false;
let isUploadListOpen = false;
let isMicMuted = false;
let isSysMuted = false;

// 녹음 이름 (앱 DB·업로드 리스트 표시용). 서버로 가는 제목(title)은 업로드 팝업에서 따로 입력한다.
let recordingName = "";
let sessionFileName = ""; // session_created 로 받은 녹음 이름

// 업로드 및 설정
let uploadData = null;
let isSegmentReadyForUpload = false;  // 세그먼트 저장 완료 여부
let isUploadDataReady = false;         // 업로드 데이터 준비 완료 여부
let mic = localStorage.getItem("mic");

// 캡처 모드 (녹음 대상) — 마이크 테스트 화면에서 선택한 값을 그대로 사용한다.
// Helper의 CaptureMode와 1:1 대응하므로 유효하지 않은 값은 기본값으로 되돌린다.
const VALID_CAPTURE_MODES = ["MicPlusSystem", "MicOnly", "SystemOnly"];
// 사용자 동작 로그 (로그 서버 category:"user_action")
function logAction(action, context) {
  try { window.developerAPI.logAction(action, context); } catch (_) {}
}

function getCaptureMode() {
  const saved = localStorage.getItem("captureMode");
  return VALID_CAPTURE_MODES.includes(saved) ? saved : "MicPlusSystem";
}

// 캡처할 출력(스피커) 장치. Windows Helper만 사용하며, macOS는 항상 "default"다.
function getRenderDeviceId() {
  return localStorage.getItem("render") || "default";
}
let directory = "recordings";
let networkStatus = navigator.onLine;
let isAppClosing = false;

// ============================================
// 3. HELPER EVENT 처리 & 녹음 중 앱 요청 처리
// ============================================

// =======================
// Helper Event Listener
// =======================
window.electronAPI.onHelperEvent((event) => {
  switch (event.ev) {
    case "version_info":
      displayVersionInfo(event);
      break;

    case "helper_info":
      // 초기 부팅 시 Helper가 1회 송신하는 간략 버전 정보도 표시
      displayVersionInfo(event);
      break;

    case "audio_device_change":
      deviceChangeEvent(event);
      break;

    case "level":
      updateLevelMeter(event.source, event.rms);
      break;

    case "waveform":
      // this.updateWaveform(event.amplitudes);
      break;

    case "progress":
      updateProgress(event);
      break;

    case "rollover":
      handleSegmentRollover(event);
      break;

    case "silence":
      handleSilenceEvent(event);
      break;

    case "paused":
      console.log("녹음이 일시정지되었습니다", event);
      // 일시정지 시 스무딩 해제 및 표시값 고정
      smoothingActive = false;
      smoothingEndAt = 0;
      displayedElapsedMs = Math.max(0, Math.floor((lastFileSeconds || 0) * 1000));
      break;

    case "resumed":
      console.log("녹음이 재개되었습니다", event);
      // 재개 직후 스무딩 윈도우 활성화
      smoothingActive = true;
      smoothingEndAt = Date.now() + RESUME_SMOOTH_WINDOW_MS;
      // 현재 표시값을 직전 파일 시계에 맞춤 (점프를 천천히 따라가도록 시작점 설정)
      displayedElapsedMs = Math.max(0, Math.floor((lastFileSeconds || 0) * 1000));
      break;

    case "recording_started":
      console.log("녹음이 시작되었습니다", event);
      saveInitialRecording();
      break;

    case "recording_stopped":
      // 최대 녹음 시간 종료 처리
      if(event.totalSamples >= TOTAL_RECORD_MS) { 
        isStoppedByMaxDuration = true;
        recordingStoppedByMaxDuration(event);
        break;
      }
      
      if(!isStoppedByError) {
        handleRecordingStopped(event);
      }else {
        // 오류로 인한 녹음 종료는 팝업 알림 이후 취소/종료 버튼을 통해 이후 로직을 이어감.
        console.log("오류로 인해 녹음이 종료되었습니다.")
        handleRecordingStoppedByError(event); 
      }
      break;

    case "test_started":
      console.log("테스트가 시작되었습니다");
      break;

    case "test_stopped":
      console.log("테스트가 중지되었습니다");
      // 시간 표시는 유지 (다음 시작 시 초기화)
      break;

    case "segment_ready":
      handleSegmentReady(event);
      break;

    case "output_dir_set":
      console.log("output_dir_set : ", event);
      outputDir = event.directory;
      break;

    case "segment_config_set":
      console.log("segment_config_set : ", event);
      break;

    case "session_created":
      console.log("session_created : ", event);
      sessionId = event.sessionId;
      // 메인이 정한 녹음 이름(A.Biz_p_rec_YYYYMMDD_HHmmss). 업로드 리스트 제목 기본값
      sessionFileName = event.fileName || "";
      outputDir = outputDir + "/" + event.sessionId;
      console.log("outputDir : ", outputDir);
      break;

    case "disk_status":
      updateDiskStatus(event);
      break;
    
    case "mic_state":
      // disconnect/unavailable 상태 처리
      console.log('마이크 상태 변경', JSON.stringify(event));
      if(event.state === "disconnect" || event.state === "unavailable") {
        console.log('마이크가 연결되지 않았습니다. 선택 후 다시 시작하세요.', JSON.stringify(event));
      }
      
    case "error":
      console.log(`헬퍼 오류: ${event.message}`, event.code);
      switch (event.code) {
        case "SELECTED_MIC_REMOVED":
          if(isRecording) {
            deviceDisconnected(event);
          }
          break;
  
          case "MIC_DEVICE_LOST":
          if(isRecording) {
            deviceDisconnected(event);
          }
          break;
  
        case "MIC_INIT_FAILED":
          console.log("마이크 초기화 실패로 녹음 중단");
          break;

        case "DISK_SPACE_CRITICAL" :
          diskSpaceCritical(event);
          break;

        case "DISK_SPACE_LOW_STOP" :
          diskSpaceLowStop(event);
          break;

        default:
          break;
      }
      
      break;
    default:
      console.log(`알 수 없는 이벤트: ${JSON.stringify(event)}`);
  }
});

// =========================
// Helper 이벤트 핸들러 함수들
// =========================

// 버전 정보 표시 — 설정 메뉴 "버전 정보" 칸에 앱 버전과 헬퍼 버전을 두 줄로 보여준다.
//   앱 v0.0.1
//   헬퍼 v0.4.2 AEC
// AEC 는 WebRTC 에코 제거가 들어간 헬퍼(회사 build.bat 빌드)일 때만 붙는다.
// (예전엔 없는 요소 versionInfo 를 써서 오류가 났고 버전이 어디에도 안 보였다)
const versionInfo = document.getElementById("versionInfoText");
const appVersionInfo = document.getElementById("appVersionText");
let appVersion = "";
let helperVersionData = null; // 언어가 바뀌면 다시 그리려고 남겨 둔다
function renderVersionTexts() {
  if (appVersionInfo) appVersionInfo.textContent = t("recording.version_app", { version: appVersion ? `v${appVersion}` : "-" });
  if (!versionInfo) return;
  if (!helperVersionData) {
    versionInfo.textContent = t("recording.version_helper", { version: "-" });
    return;
  }
  const v = helperVersionData;
  versionInfo.textContent = t("recording.version_helper", { version: `v${v.version}${v.webrtc_aec ? " AEC" : ""}` });
  versionInfo.title = `${v.product_name}\n${v.description}\n${t("recording.version_build", { date: v.build_date, time: v.build_time })}\n${v.copyright}`;
}
renderVersionTexts();
try {
  window.electronAPI.getAppVersion().then((v) => {
    if (v) { appVersion = v; renderVersionTexts(); }
  }).catch(() => {});
} catch (_) {}
function displayVersionInfo(versionData) {
  if (!versionInfo || !versionData) return;
  helperVersionData = versionData;
  renderVersionTexts();

  console.log(
    `Helper 버전: ${versionData.version_full}, WebRTC AEC: ${
      versionData.webrtc_aec ? "활성화" : "비활성화"
    }`
  );
}

// 장치 변경 이벤트
function deviceChangeEvent(event) {
  console.log(`장치 ${event.change_type}: ${event.device_type}`);
  /**
   * 녹음 중이 아닐때: 초기화면으로 이동
   * 녹음 중: 
   *  - 추가: 무시
   *  - 제거: 'MIC_DEVICE_LOST' 오류 발생 처리
   */
  if(!isRecording) {
    window.electronAPI.openPopupWindow({
      title: t("recording.popup_device_change_title"),
      subtitle: event.change_type === "added" ? t("recording.popup_device_added") : t("recording.popup_device_removed"),
      type: "device_change",
      width: 320,
      height: 200,
    });
  } else {
    console.log("녹음 중이므로 장치 변경 알림 무시");
  }
}

// 레벨 미터 업데이트
function updateLevelMeter(source, rms) {
  feedWave(source, rms);
  // mic 입력이 helper 무음 임계값 미만일 경우 레벨미터를 0으로 고정
  if (source === "mic" && typeof rms === "number" && rms < HELPER_SILENCE_THRESHOLD) {
    updateLevelMeterBoxes(micMeter, 0);
    return;
  }

  const dbValue = rms > 0 ? 20 * Math.log10(rms) : -Infinity;
  const percentage = Math.max(0, Math.min(100, ((dbValue + 60) / 60) * 100));

  // 10단계로 구분하여 표시
  const step = Math.floor(percentage / 10); // 0-9 단계
  const activeBoxes = Math.min(step, 10); // 최대 10개 박스

  if (source === "mic") {
    updateLevelMeterBoxes(micMeter, activeBoxes);
  } else if (source === "system") {
    updateLevelMeterBoxes(sysMeter, activeBoxes);
  }
}

// 레벨 미터 박스 업데이트
function updateLevelMeterBoxes(meter, activeCount) {
  const boxes = meter.querySelectorAll(".level-box");
  boxes.forEach((box, index) => {
    if (index < activeCount) {
      box.classList.add("active");
    } else {
      box.classList.remove("active");
    }
  });
}

// 진행 시간 업데이트
function updateProgress(event) {
  const seconds =
    typeof event.seconds === "number"
      ? event.seconds
      : (typeof event.mic_seconds === "number" ? event.mic_seconds : 0);
  // console.log("seconds : ", seconds);
  useProgressClock = true;
  lastFileSeconds = seconds;
  // 실제 렌더링 및 남은시간 갱신은 startRecordingTimer의 틱에서 일원화하여 처리 (중복 갱신 방지)
}

// 세그먼트 롤오버 처리
function handleSegmentRollover(event) {
  currentSegment = event.segmentIndex;
  segmentInfo.textContent = `#${currentSegment}`;
  console.log(`새 세그먼트 시작: #${currentSegment}`);
}

// 세그먼트 준비 완료
// Windows 경로 비교: 구분자(\ /)와 대소문자 차이는 같은 경로로 본다.
function samePath(a, b) {
  const norm = (p) => String(p || "").replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  return norm(a) === norm(b);
}

function handleSegmentReady(event) {
  console.log(
    `segment is saved: ${event.path} (${event.samples} samples, ${
      event.encrypted ? "암호화됨" : "암호화 안됨"
    })`
  );
  isSegmentReadyForUpload = true;

  console.log("event.path : ", event.path);
  console.log("outputDir : ", outputDir);
  // 업로드 경로는 실제 파일이 저장된 폴더(event.dir, 메인이 절대경로로 붙여 줌)를 따른다.
  // 조립한 경로(output_dir_set + "/" + sessionId)가 실제 위치와 다르면 업로드가
  // "filePath is not a directory" 로 실패했다.
  if (event.dir && !samePath(event.dir, outputDir)) {
    console.warn("업로드 경로를 실제 저장 폴더로 교체", { before: outputDir, after: event.dir });
    try { window.developerAPI.sendWarn("recording_dir_corrected", { before: outputDir, after: event.dir }); } catch (_) {}
    outputDir = event.dir;
    if (uploadData) uploadData.filePath = outputDir;
  }
  // 세그먼트 경계에서 실제 저장된 샘플 기준으로 UI 시간을 강제 동기화
  if (typeof event.samples === "number") {
    // 주의: 샘플 기반 시간과 progress(캡쳐 기반) 시간을 합산하면 안 됨
    const elapsedMsFromSamples = Math.floor((event.samples * 1000) / 16000);
    const progressMs = Math.max(0, Math.floor((lastFileSeconds || 0) * 1000));
    const desiredMs = Math.max(progressMs, elapsedMsFromSamples);
    // 스무딩/일원화된 렌더링 경로를 따르도록 표시값만 업데이트
    displayedElapsedMs = desiredMs;
  }
  if (typeof event.index === "number") {
    currentSegment = event.index + 1;
    segmentInfo.textContent = `#${currentSegment}`;
  }

  // DB: 녹음 메타 저장
  window.dbAPI
    .upsertRecording({
      id: recordId,
      fileName: recordingName,
      filePath: outputDir,
    })
    .then((res) => {
      if (res.success) {
        console.log("녹음 메타 저장 완료", res);

      } else {
        console.log("녹음 메타 저장 실패", res);
      }
    });

  if(isStoppedByError) {
    console.log("에러로 인한 녹음 종료 및 세그먼트 저장");
  }
    
  if(stopType === "complete") {
    console.log("세그먼트 저장 완료 - 업로드 준비 상태 설정");
    tryStartUpload();
  }else if(stopType === "cancel") {
    window.electronAPI.deleteRecording(outputDir);
  }
  stopType = "";
}

// 녹음 화면 아래 안내 줄: default(동의 안내) / early(무음 7초~) / sustained(무음 30초)
// 언어가 바뀌면 같은 상태로 다시 그린다.
let notiState = "default";
function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function renderNoti() {
  if (notiState === "default") {
    noti.classList.remove("warning");
    noti.innerHTML = `
    <span><img src="../assets/icons/noti.svg" alt="" />${escapeHtml(t("recording.noti_default"))}</span>
    `;
    return;
  }
  noti.classList.add("warning");
  noti.innerHTML = `
    <span><img src="../assets/icons/noti_red.svg" alt="" />${escapeHtml(t(`recording.noti_${notiState}_title`))}</span>
    <span>${escapeHtml(t(`recording.noti_${notiState}_desc`))}</span>
  `;
}
function setNoti(state) {
  notiState = state;
  renderNoti();
}

// 무음 이벤트 처리
async function handleSilenceEvent(event) {
  const isMinimized = await window.windowAPI.isMinimized();
  console.log("isMinimized : ", isMinimized);
  switch (event.state) {
    case "sustained":
      console.log(
        `지속 30초간 무음 지속 - 메일 알림이 필요할 수도 있습니다.`,
        "warning"
      );
      setNoti("sustained");
      if(isMinimized) {
        window.electronAPI.createSystemNotification({
          title: t("recording.noti_sustained_title"),
          subtitle: t("recording.noti_sustained_desc"),
        });
      }
      break;

    case "early":
      if (event.elapsedMs % 7000 < 1000) {
        // 7초마다 알림
        console.log(
          `지속 무음 진행중: ${(event.elapsedMs / 1000).toFixed(0)}초`
        );
      }
      setNoti("early");

      if(isMinimized) {
        window.electronAPI.createSystemNotification({
          title: t("recording.noti_early_title"),
          subtitle: t("recording.noti_early_desc"),
        });
      }
      break;

    case "off":
      setNoti("default");
      break;
    default:
      console.log("silence event : ", event);
  }
}

// 디스크 상태 업데이트
function updateDiskStatus(event){
  console.log("디스크 여유 공간 상태 업데이트", event);

  const status = event.status;
  if(status === "low"){
    window.electronAPI.openPopupWindow({
      title: t("recording.popup_disk_low_title"),
      subtitle: t("recording.popup_disk_low_subtitle"),
      warning: t("recording.popup_disk_low_warning"),
      type: "error-alert-warning",
      width: 341,
      height: 197,
    });
  }
  if(status === "critical"){
    diskSpaceCritical(event);
  }
}

// 디스크 여유 공간 임계치 도달
function diskSpaceCritical(event) {
  console.log("디스크 여유 공간 임계치 도달", event);
    // 임계값에 도달하여 다음 세그먼트 경계에서 중지 예약
  window.electronAPI.openPopupWindow({
    title: t("recording.popup_disk_low_title"),
    subtitle: t("recording.popup_disk_low_subtitle"),
    warning: t("recording.popup_disk_critical_warning"),
    type: "error-alert-warning",
    width: 341,
    height: 197,
  });
}

// 저장공간 부족으로 녹음 중단
function diskSpaceLowStop(event) {
  // 저장공간 임계로 떨어져 헬퍼가 즉시 정지 수행
  console.log("디스크 여유 공간 부족으로 녹음 중단", event);
  logAction("recording_stopped_by_disk", { sessionId, elapsedMs: getCurrentRecordingTime() });
  stoppedByLowDisk = true;
  isStoppedByError = true;
  window.electronAPI.openPopupWindow({
    title: t("recording.popup_disk_stop_title"),
    subtitle: t("recording.popup_disk_stop_subtitle"),
    warning: t("recording.popup_disk_stop_warning"),
    type: "disk-space-low-stop",
    width: 341,
    height: 241,
  });
}

// 장치 연결 끊김으로 녹음 중단
function deviceDisconnected(event) {
  console.log("장치 연결 끊김으로 녹음 중단", event);
  logAction("recording_stopped_by_device", { sessionId, elapsedMs: getCurrentRecordingTime(), code: event && event.code });
  stoppedByDeviceDisconnected = true;
  isStoppedByError = true;
  window.electronAPI.openPopupWindow({
    title: t("recording.popup_device_lost_title"),
    subtitle: t("recording.popup_device_lost_subtitle"),
    warning: t("recording.popup_device_lost_warning"),
    type: "error-alert-warning",
    width: 347,
    height: 217,
  });
}

function updateTopButtonIcon() {
  const TopBtnImg = document.querySelector("#topBtn img");
  if (!TopBtnImg) return;
  TopBtnImg.src = isTop
    ? "../assets/icons/aotActiveBtn.svg"
    : "../assets/icons/aotNoActiveBtn.svg";
  updateTopTooltip();
}

function setTopState(desired) {
  if (typeof desired !== "boolean") return;
  if (isTop !== desired) {
    window.windowAPI.topWindow(); // 메인에서 토글 수행
    isTop = desired;
  }
  updateTopButtonIcon();
  // 선택 항목 동기화
  syncAotDetailSelection();
}

function toggleTopState() {
  setTopState(!isTop);
}

// ============================================
// 4. 녹음 제어 함수
// ============================================

// 초기 녹음 데이터 DB저장
// 녹음 이름 기본값: "녹음 2026-10-13 21:05"
// 업로드 리스트 제목 기본값 = 서버로 보내는 파일명과 같은 이름(main.js buildRecordingFileName).
// 비어 있으면 메인(insert-recording)이 녹음 시작 때 정한 이름으로 채운다.
// (예전: "녹음 YYYY-MM-DD HH:mm")
function defaultRecordingName() {
  return sessionFileName || "";
}

function saveInitialRecording() {
  console.log("메타데이터 저장! 파일경로 : ", outputDir);
  recordingName = defaultRecordingName();
  window.dbAPI
    .insertRecording({
      fileName: recordingName,
      filePath: outputDir,
    })
    .then((res) => {
      if (res.success) {
        recordId = res.recordingId;
        console.log(
          "레코딩 시작 및 메타데이터 저장완료. recordId : ",
          recordId
        );
      } else {
        console.log("레코딩 시작 및 메타데이터 저장 실패", res);
      }
    });
}

// 업로드 조건 확인 및 시작
function tryStartUpload() {
  console.log("tryStartUpload 호출", {
    isSegmentReadyForUpload,
    isUploadDataReady,
    hasUploadData: uploadData !== null,
    uploadData
  });

  if(uploadData && uploadData.recordId !== recordId) {
    console.log("업로드 데이터가 현재 세션과 일치하지 않음!!",{
      uploadDataRecordId: uploadData.recordId,
      currentRecordId: recordId,
    });
    return;
  }

  // 두 조건이 모두 만족될 때만 업로드 시작
  if (isSegmentReadyForUpload && isUploadDataReady && uploadData !== null) {
    console.log("업로드 조건 만족 - 업로드 시작");
    
    // 중복 실행 방지를 위한 플래그 초기화
    isSegmentReadyForUpload = false;
    isUploadDataReady = false;
    
    // 업로드 시작
    serverUpload(uploadData);
  } else {
    console.log("업로드 조건 미충족 - 대기 중");
  }
}

// 서버 업로드 요청
function serverUpload(uploadData) {
  console.log("serverUpload : ", uploadData);

  try {
    // 장치 연결 끊김으로 인한 중단인 경우, 업로드 완료 후 홈으로 이동하도록 플래그 전달
    if (stoppedByDeviceDisconnected) {
      try { uploadData = { ...uploadData, goHomeAfterUpload: true }; } catch (_) {}
    }
  } catch (_) {}

  const payload = {...uploadData, isAppClosing: isAppClosing};
  const res = window.serviceAPI.serverUpload(payload);
  if(res.success) {
    console.log("서버 업로드 완료", res);
    openPopupWindow({
      title: "서버 업로드 "
    });
  } else {
    console.log("서버 업로드 실패", res);
  }

  

  if(isStoppedByError || isStoppedByMaxDuration) {
    variableInitialize();
  }
}

// 녹음 시작
async function startRecording(mic) {
  try {
    outputDir = "";

    // 업로드 관련 변수 초기화 추가
    uploadData = null;
    isSegmentReadyForUpload = false;
    isUploadDataReady = false;

    // 먼저 출력 디렉토리 설정
    await window.electronAPI.sendHelperCommand({
      cmd: "set_output_dir",
      directory: directory,
    });

    // 디버그 파일 저장 활성화
    await window.electronAPI.sendHelperCommand({
      cmd: "set_debug_files",
      enabled: "false",
    });

    // 세그먼트 설정 (암호화 포함)
    await window.electronAPI.sendHelperCommand({
      cmd: "set_segment_config",
      encryption_enabled: "true", // 개발 중에는 OFF
    });

    // 녹음 시작
    const command = {
      cmd: "start",
      mode: getCaptureMode(),
      out: { sr: 16000, ch: 1, blockMs: 20 },
      mic: mic,
      render: getRenderDeviceId(),
      gains: { mic: 1.0, sys: 0.7 },
      max_ms: TOTAL_RECORD_MS,
      segmenting: {
        duration_ms: SEGMENT_DURATION_MS, // 3분
        max_cipher_bytes: 60 * 1024 * 1024, // 60MB
        align_to_block: true,
      },
    };

    await window.electronAPI.sendHelperCommand(command);
    
    isMicMuted = false;
    isSysMuted = false;
    micIcon.classList.remove("muted");
    sysIcon.classList.remove("muted");

    PauseBtnImg.src = "../assets/icons/pause_small.svg";
    PauseBtnImg.style.width = "20px";
    PauseBtnImg.style.height = "20px";
    
    
    // 녹음 상태로 전환
    isRecording = true;
    isPaused = false;
    startTime = Date.now();
    pausedTime = 0;
    currentSegment = 1;
    
    // 녹음 시작/종료 버튼 활성화
    recordCancelBtn.classList.remove("disabled");
    recordCompleteBtn.classList.remove("disabled");
    
    // 새 세션 시작 시 진행 표시 방식 초기화
    useProgressClock = false;
    lastProgressSeconds = 0;
    lastFileSeconds = 0;
    timeCompleteLogged = false;


    startRecordingTimer();
    recordingStatusCircle.classList.remove("hidden");

    logAction("recording_started", { captureMode: getCaptureMode() });
  } catch (error) {
    window.developerAPI.sendError("recording_start_failed", {message: error.message});
  }
}

// 일시정지 처리 함수
function handleRecordingPause() {
  console.log("녹음 일시정지 함수 호출");
  window.electronAPI.sendHelperCommand({
      cmd: "pause",
    });
  recordingStatusCircle.classList.add("hidden");

  PauseBtnImg.src = "../assets/icons/recordingIcon.svg";
  PauseBtnImg.style.width = "36px";
  PauseBtnImg.style.height = "36px";

  isPaused = true;
  pausedTime += Date.now() - startTime;
  stopRecordingTimer();
  
  // 팝업 창 생성
  if (stopType === "cancel") {
    console.log("녹음 취소됨 파일 경로 : ", outputDir);

    window.electronAPI.openPopupWindow({
      title: t("recording.popup_delete_title"),
      subtitle: t("recording.popup_delete_subtitle"),
      type: stopType,
      dir: outputDir,
      width: 320,
      height: 180,
    });
  } else if(stopType === "complete"){

    window.electronAPI.openPopupWindow({
      title: t("recording.popup_upload_title"),
      type: stopType,
      dir: outputDir,
      width: 320,
      height: 180,
    });
  }

}

// 녹음 재개
function handleRecordingResume() {
  window.electronAPI.sendHelperCommand({
      cmd: "resume",
    });
    recordingStatusCircle.classList.remove("hidden");

    PauseBtnImg.src = "../assets/icons/pause_small.svg";
    PauseBtnImg.style.width = "20px";
    PauseBtnImg.style.height = "20px";

    stopType = "";
    isPaused = false;
    startTime = Date.now();
    startRecordingTimer();

    console.log("녹음 재개 버튼 클릭");
}

// 녹음 종료 함수(오류 없이 정상 종료)
function handleRecordingStopped(event) {
  console.log("handleRecordingStopped : ", event);
  logAction("recording_stopped", { sessionId, elapsedMs: getCurrentRecordingTime(), stopType });
  isRecording = false;
  isPaused = false;
  stopRecordingTimer();

  // 일시정지 버튼 이미지 초기화
  PauseBtnImg.src = "../assets/icons/recordingIcon.svg";
  PauseBtnImg.style.width = "36px";
  PauseBtnImg.style.height = "36px";

  // UI/상태 초기화
  variableInitialize();
}

// 녹음 종료 함수(오류로 인한 종료) -> 재시작 불가한 일시정지 상태
function handleRecordingStoppedByError(event) {  
    console.log("저장공간 부족으로 녹음 중단");
    recordingStatusCircle.classList.add("hidden");

    PauseBtnImg.src = "../assets/icons/recordingIcon.svg";
    PauseBtnImg.style.width = "36px";
    PauseBtnImg.style.height = "36px";
    
    isRecording = false;  
    isPaused = true;
    pausedTime += Date.now() - startTime;
    stopRecordingTimer();
    
    pauseBtn.disabled = true;
}

// 최대 녹음 시간 도달 시 종료
function recordingStoppedByMaxDuration(event) {
  console.log("recordingStoppedByMaxDuration : ", event);
  logAction("recording_stopped_by_max_duration", { sessionId, elapsedMs: getCurrentRecordingTime() });
  // *녹음 종료 버튼 누른 상태로 변경
  isRecording = false;
  isPaused = false;
  stopRecordingTimer();

  // 일시정지 버튼 이미지 초기화
  PauseBtnImg.src = "../assets/icons/recordingIcon.svg";
  PauseBtnImg.style.width = "36px";
  PauseBtnImg.style.height = "36px";

  // 근데 녹음은 이미 종료되서 세그먼트는 내려온 상태임
  
  // 팝업 창 생성(업로드 할래? 아니면 삭제할래?)
  window.electronAPI.openPopupWindow({
    title: t("recording.popup_max_duration_title"),
    subtitle: t("recording.popup_max_duration_subtitle"),
    type: "max_duration_stopped",
    dir: outputDir,
    width: 341,
    height: 220,
  });
  // 업로드 선택하면 업로드
  // 삭제 선택하면 삭제
  // 두 쪽중 하나라도 선택하면 정상 녹음 종료 상태로 변경
  // 재시작 준비
}


// 오류 이후 녹음 취소
function handleRecordingCancelOnError() {
  console.log("handleRecordingCancelOnError");
  
  window.electronAPI.openPopupWindow({
    title: t("recording.popup_delete_title"),
    subtitle: t("recording.popup_delete_subtitle"),
    type: "error_cancel",
    dir: outputDir,
    width: 320,
    height: 180,
  });
}

// 오류 이후 녹음 종료
function handleRecordingCompleteOnError() {
  console.log("handleRecordingCompleteOnError");

  window.electronAPI.openPopupWindow({
    title: t("recording.popup_upload_title"),
    type: "error_complete",
    dir: outputDir,
    width: 320,
    height: 180,
  });
}

// 변수 초기화
function variableInitialize(){
  try {
    // 세션 종료 시 진행 표시 방식 초기화
    useProgressClock = false;
    lastProgressSeconds = 0;
    lastFileSeconds = 0;
    recordingStatusCircle.classList.add("hidden");

    recordingName = "";
    sessionFileName = "";
    recordId = null;
    sessionId = null;
    resetWave();
    
    // 진행 시간/남은 시간 바 초기화
    recordingTime.textContent = "00 : 00 : 00";
    if (remainTimeBar) {
      remainTimeBar.style.width = "100%";
      remainTimeBar.classList.remove("ok", "warn", "danger");
      remainTimeBar.classList.add("ok"); // 파란색으로 초기화
    }
    if (remainTimeText) remainTimeText.textContent = "03:00:00";
    // 세그먼트/표시 초기화
    currentSegment = 1;
    if (typeof segmentInfo !== "undefined" && segmentInfo) {
      segmentInfo.textContent = `#${currentSegment}`;
    }
    setNoti("default");
    
    // 일시정지 버튼 비활성화 해제
    pauseBtn.disabled = false;

    // 녹음 시작/종료 버튼 비활성화
    recordCancelBtn.classList.add("disabled");
    recordCompleteBtn.classList.add("disabled");
    
    // 오류상황 해제
    isStoppedByError = false;
    isStoppedByMaxDuration = false;
    stopType = "";
    stoppedByDeviceDisconnected = false;
    stoppedByLowDisk = false;

  } catch (e) {
    console.log("reset session error:", e);
  }
}

// ============================================
// 5. 타이머 및 시간 표시 함수
// ============================================

// 타이머 시작
function startRecordingTimer() {
  recordingTimer = setInterval(() => {
    if (useProgressClock) {
      // 파일 시계 기반 목표값
      const targetMs = Math.max(0, Math.floor((lastFileSeconds || 0) * 1000));

      if (smoothingActive) {
        if (!smoothingEndAt) smoothingEndAt = Date.now() + RESUME_SMOOTH_WINDOW_MS;
        const now = Date.now();
        if (now >= smoothingEndAt || displayedElapsedMs >= targetMs) {
          displayedElapsedMs = targetMs;
          smoothingActive = false;
          smoothingEndAt = 0;
        } else {
          const gap = Math.max(0, targetMs - displayedElapsedMs);
          const step = Math.min(MAX_STEP_PER_TICK_MS, gap);
          displayedElapsedMs += step;
        }
      } else {
        displayedElapsedMs = targetMs;
      }

      recordingTime.textContent = formatRecordingTime(displayedElapsedMs);
      updateRemainTime(displayedElapsedMs);
      return;
    }

    const elapsed = getCurrentRecordingTime();
    recordingTime.textContent = formatRecordingTime(elapsed);
    updateRemainTime(elapsed);
  }, 100);
}

// 타이머 종료
function stopRecordingTimer() {
  if (recordingTimer) {
    clearInterval(recordingTimer);
    recordingTimer = null;
  }
}

// 현재 녹음 시간 반환
function getCurrentRecordingTime() {
  if (!isRecording) return 0;

  let elapsed = pausedTime;
  if (!isPaused) {
    elapsed += Date.now() - startTime;
  }
  return elapsed;
}

// 남은시간 프로그래스 바
function updateRemainTime(elapsedMs) {
  const elapsed =
    typeof elapsedMs === "number" ? elapsedMs : getCurrentRecordingTime();
  const remaining = Math.max(0, TOTAL_RECORD_MS - elapsed);
  const percent = Math.max(
    0,
    Math.min(100, (remaining / TOTAL_RECORD_MS) * 100)
  );

  if (remainTimeBar) {
    remainTimeBar.style.width = `${percent}%`;
    // 경고 단계 클래스 토글: ok (>=30m), warn (>=10m,<30m), danger (<10m)
    const THIRTY_MIN = 30 * 60 * 1000;
    const TEN_MIN = 10 * 60 * 1000;
    remainTimeBar.classList.remove("ok", "warn", "danger");
    if (remaining >= THIRTY_MIN) {
      remainTimeBar.classList.add("ok");
    } else if (remaining >= TEN_MIN) {
      remainTimeBar.classList.add("warn");
    } else {
      remainTimeBar.classList.add("danger");
    }
  }
  if (remainTimeText) {
    remainTimeText.textContent = formatTime(remaining);
  }
}

// 시간 포맷팅 (HH:MM:SS)
function formatTime(ms) {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  return `${hours.toString().padStart(2, "0")}:${minutes
    .toString()
    .padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
}

// 녹음 시간 포맷팅 (HH : MM : SS)
function formatRecordingTime(ms) {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60 <= 59 ? totalSeconds % 60 + 1 : totalSeconds % 60;

  return `${hours.toString().padStart(2, "0")} : ${minutes
    .toString()
    .padStart(2, "0")} : ${seconds.toString().padStart(2, "0")}`;
}

// ============================================
// 6. 녹음 중 웨이브
// ============================================
// 헬퍼의 level 이벤트(mic/system RMS)를 일정 간격으로 모아 막대로 그린다. 오른쪽에서 새 막대가 들어와 왼쪽으로 흐른다.
// 녹음 중: 파란 막대가 흐름 / 일시정지·종료: 멈추고 회색. 음소거한 쪽 소리는 반영하지 않는다.
const WAVE_SAMPLE_MS = 70;  // 막대 하나 = 70ms
const WAVE_BAR_WIDTH = 3;
const WAVE_BAR_GAP = 2;
const WAVE_ACTIVE_COLOR = "#1c6eff";
const WAVE_IDLE_COLOR = "#4d5256";
let waveBars = [];   // 0~1
let wavePeak = 0;    // 이번 간격 동안 들어온 가장 큰 값
let waveTimer = null;

function rmsToLevel(rms, threshold) {
  if (typeof rms !== "number" || rms < threshold) return 0;
  const db = 20 * Math.log10(rms);
  return Math.max(0, Math.min(1, (db + 60) / 60));
}

function feedWave(source, rms) {
  if (source === "mic" && isMicMuted) return;
  if (source === "system" && isSysMuted) return;
  const threshold = source === "system" ? SYSTEM_LEVEL_THRESHOLD : HELPER_SILENCE_THRESHOLD;
  wavePeak = Math.max(wavePeak, rmsToLevel(rms, threshold));
}

function waveCapacity() {
  const width = waveCanvas ? waveCanvas.clientWidth : 0;
  return Math.max(1, Math.floor(width / (WAVE_BAR_WIDTH + WAVE_BAR_GAP)));
}

function drawWave() {
  if (!waveCanvas) return;
  const dpr = window.devicePixelRatio || 1;
  const width = waveCanvas.clientWidth;
  const height = waveCanvas.clientHeight;
  if (waveCanvas.width !== Math.round(width * dpr) || waveCanvas.height !== Math.round(height * dpr)) {
    waveCanvas.width = Math.round(width * dpr);
    waveCanvas.height = Math.round(height * dpr);
  }
  const ctx = waveCanvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = isRecording && !isPaused ? WAVE_ACTIVE_COLOR : WAVE_IDLE_COLOR;

  const step = WAVE_BAR_WIDTH + WAVE_BAR_GAP;
  const capacity = waveCapacity();
  const mid = height / 2;
  // 빈 칸은 가는 점선(기준선)으로 채워 "멈춤/무음" 도 보이게 한다.
  for (let i = 0; i < capacity; i += 1) {
    const level = waveBars[waveBars.length - capacity + i] || 0;
    const barHeight = Math.max(2, level * (height - 4));
    const x = width - (capacity - i) * step;
    ctx.fillRect(x, mid - barHeight / 2, WAVE_BAR_WIDTH, barHeight);
  }
}

function tickWave() {
  if (isRecording && !isPaused) {
    waveBars.push(wavePeak);
    const keep = waveCapacity();
    if (waveBars.length > keep) waveBars.splice(0, waveBars.length - keep);
  }
  wavePeak = 0;
  drawWave();
}

function startWave() {
  if (waveTimer) return;
  waveTimer = setInterval(tickWave, WAVE_SAMPLE_MS);
}

function resetWave() {
  waveBars = [];
  wavePeak = 0;
  drawWave();
}

// ============================================
// 7. UI 컨트롤 함수
// ============================================

// 툴팁 관리
function updateTopTooltip() {
  if (topBtn) {
    topBtn.setAttribute("data-tooltip", isTop ? t("recording.tooltip_aot_off") : t("recording.tooltip_aot_on"));
    ensureTooltipAlignment(topBtn);
  }
}

function setStaticTooltips() {
  if (minimizeBtn) {
    minimizeBtn.setAttribute("data-tooltip", t("common.minimize"));
    ensureTooltipAlignment(minimizeBtn);
  }
}

// 툴팁 정렬 계산: 기본 중앙 정렬, 우측으로 넘칠 때만 오른쪽 정렬
function ensureTooltipAlignment(btn) {
  if (!btn) return;
  const text = btn.getAttribute("data-tooltip") || "";
  if (!text) {
    btn.removeAttribute("data-align");
    return;
  }
  const rect = btn.getBoundingClientRect();
  // 측정 엘리먼트 생성 (툴팁 스타일 반영)
  const measure = document.createElement("div");
  measure.textContent = text;
  measure.style.position = "fixed";
  measure.style.visibility = "hidden";
  measure.style.pointerEvents = "none";
  measure.style.whiteSpace = "nowrap";
  measure.style.fontSize = "12px";
  measure.style.lineHeight = "1.2";
  measure.style.padding = "6px 8px";
  measure.style.border = "1px solid #323234";
  measure.style.background = "#292a2b";
  measure.style.zIndex = "-1";
  document.body.appendChild(measure);
  const tooltipWidth = measure.getBoundingClientRect().width;
  document.body.removeChild(measure);

  // 중앙 정렬 가정 하여 좌우 계산
  const centerLeft = rect.left + rect.width / 2 - tooltipWidth / 2;
  const rightEdge = centerLeft + tooltipWidth;
  const viewportRight = window.innerWidth - 8; // 여백 8px

  if (rightEdge > viewportRight) {
    btn.setAttribute("data-align", "right");
  } else {
    btn.removeAttribute("data-align");
  }
}

// Top 버튼 관련
function updateTopButtonIcon() {
  const TopBtnImg = document.querySelector("#topBtn img");
  if (!TopBtnImg) return;
  TopBtnImg.src = isTop
    ? "../assets/icons/aotActiveBtn.svg"
    : "../assets/icons/aotNoActiveBtn.svg";
  updateTopTooltip();
}

function setTopState(desired) {
  if (typeof desired !== "boolean") return;
  if (isTop !== desired) {
    window.windowAPI.topWindow(); // 메인에서 토글 수행
    isTop = desired;
  }
  updateTopButtonIcon();
  // 선택 항목 동기화
  syncAotDetailSelection();
}

function toggleTopState() {
  setTopState(!isTop);
}

// ============================================
// 8. 설정 메뉴 UI 함수
// ============================================

// 설정 메뉴 위치 조정 함수
function positionMenu() {
  const rect = settingBtn.getBoundingClientRect();
  // 버튼 바로 아래 우측 정렬(필요시 조정)
  const offsetX = rect.right - 138; // 메뉴 폭(최소 160px) 기준
  const offsetY = rect.bottom + 6;
  // 화면 좌표 → CSS 위치
  settingsMenu.style.left = `${Math.max(8, offsetX + 70)}px`;
  settingsMenu.style.top = `${offsetY}px`;
  // 메뉴 폭은 언어마다 다르다. 창 오른쪽 밖으로 나가면 안쪽으로 당긴다(보이는 상태에서만 폭을 잴 수 있다)
  const maxLeft = window.innerWidth - settingsMenu.offsetWidth - 4;
  if (settingsMenu.offsetWidth && settingsMenu.offsetLeft > maxLeft) {
    settingsMenu.style.left = `${Math.max(4, maxLeft)}px`;
  }
}

// 1뎁스 메뉴에 현재 상태 표시(항상 위: 켜짐/꺼짐, 음소거: 켜짐/꺼짐/일부 — 마이크·시스템 중 하나만 음소거)
function syncMenuStateTexts() {
  if (aotStateText) {
    aotStateText.textContent = isTop ? t("recording.state_on") : t("recording.state_off");
    aotStateText.classList.toggle("on", !!isTop);
  }
  if (muteStateText) {
    const state = isMicMuted && isSysMuted ? "on" : (isMicMuted || isSysMuted) ? "partial" : "off";
    muteStateText.textContent = t(`recording.state_${state}`);
    muteStateText.classList.toggle("on", state !== "off");
  }
  if (languageStateText) {
    const current = window.i18n.languages().find((l) => l.code === window.i18n.lang());
    languageStateText.textContent = current ? current.name : "";
  }
}

function openMenu() {
  syncMenuStateTexts();
  settingsMenu.hidden = false;
  positionMenu();
  window.addEventListener("click", onClickOutside);
}

function closeMenu() {
  settingsMenu.hidden = true;
  closeAllDetails();
  window.removeEventListener("click", onClickOutside);
}

function onClickOutside(e) {
  if (
    !settingsMenu.contains(e.target) &&
    e.target !== settingBtn &&
    !isInAnyDetail(e.target)
  ) {
    closeAllDetails();
    closeMenu();
  }
}

// 서브메뉴 관리
let openedDetail = null;
const DETAIL_OPEN_DELAY = 250; // ms: 항목 위에 머물면 열기
const DETAIL_CLOSE_DELAY = 500; // ms: 메뉴/서브메뉴에서 벗어나면 닫기
let detailOpenTimer = null;
let detailCloseTimer = null;

function isInAnyDetail(target) {
  return (
    (settingsAotItems && settingsAotItems.contains(target)) ||
    (settingsMuteItems && settingsMuteItems.contains(target)) ||
    (settingsLanguageItems && settingsLanguageItems.contains(target))
  );
}

function closeAllDetails() {
  if (settingsAotItems) settingsAotItems.hidden = true;
  if (settingsMuteItems) settingsMuteItems.hidden = true;
  if (settingsLanguageItems) settingsLanguageItems.hidden = true;
  openedDetail = null;
}

function positionDetail(detailEl, triggerEl) {
  if (!detailEl || !triggerEl) return;
  const itemRect = triggerEl.getBoundingClientRect();
  const menuRect = settingsMenu.getBoundingClientRect();
  // 메인 메뉴의 우측 외곽선에 정확히 붙도록 위치 설정 (공백 0)
  const left = menuRect.right; // 경계선에 바로 붙임
  const top = itemRect.top - 3; // 메뉴 padding 보정
  detailEl.style.left = `${left}px`;
  detailEl.style.top = `${top}px`;
}

function openDetail(detailEl, triggerEl) {
  if (!detailEl) return;
  if (openedDetail === detailEl && !detailEl.hidden) {
    detailEl.hidden = true;
    openedDetail = null;
    return;
  }
  closeAllDetails();
  positionDetail(detailEl, triggerEl);
  detailEl.hidden = false;
  // 창 오른쪽 밖으로 나가면 안쪽으로 당긴다(예전엔 잘려서 선택 표시 ✓ 가 안 보였다)
  try {
    const maxLeft = window.innerWidth - detailEl.offsetWidth - 4;
    if (detailEl.offsetLeft > maxLeft) detailEl.style.left = `${Math.max(4, maxLeft)}px`;
  } catch (_) {}
  openedDetail = detailEl;
  // 상태 기반 사전 선택 동기화
  if (detailEl === settingsAotItems) syncAotDetailSelection();
  if (detailEl === settingsMuteItems) syncMuteDetailSelection();
  if (detailEl === settingsLanguageItems) renderLanguageItems();
}

function scheduleOpenDetail(detailEl, triggerEl) {
  if (detailOpenTimer) clearTimeout(detailOpenTimer);
  detailOpenTimer = setTimeout(() => openDetail(detailEl, triggerEl), DETAIL_OPEN_DELAY);
}

function scheduleCloseDetail() {
  if (detailCloseTimer) clearTimeout(detailCloseTimer);
  detailCloseTimer = setTimeout(() => {
    if (openedDetail) {
      openedDetail.hidden = true;
      openedDetail = null;
    }
  }, DETAIL_CLOSE_DELAY);
}

// 선택 체크 표시 토글 유틸
function markSelected(containerEl, clickedBtn) {
  if (!containerEl || !clickedBtn) return;
  const all = containerEl.querySelectorAll("button");
  all.forEach((b) => b.classList.remove("selected"));
  clickedBtn.classList.add("selected");
}

// 상태 기반 사전 체크 동기화
function syncAotDetailSelection() {
  if (!settingsAotItems) return;
  const targetBtn = isTop ? aotItem1 : aotItem2;
  if (targetBtn) markSelected(settingsAotItems, targetBtn);
}

// 음소거 서브메뉴 선택 상태 동기화
function syncMuteDetailSelection() {
  if (!settingsMuteItems) return;
  // 조건: mic와 sys가 모두 음소거이거나 모두 음소거 아님일 때만 체크 표시
  if (isMicMuted === isSysMuted) {
    const targetBtn = isMicMuted ? muteItem1 : muteItem2;
    if (targetBtn) markSelected(settingsMuteItems, targetBtn);
  } else {
    const all = settingsMuteItems.querySelectorAll("button");
    all.forEach((b) => b.classList.remove("selected"));
  }
}

// ============================================
// 9. 이벤트 리스너 등록
// ============================================

// === Electron IPC 이벤트들 ===

// 파일 삭제 결과 수신
window.electronAPI.onDeleteRecordingResult((payload) => {
  if(payload.success) {
    const shouldGoHome = !!stoppedByDeviceDisconnected;
    console.log("녹음 파일 삭제 완료", payload);
    variableInitialize();
    if (shouldGoHome) {
      try { window.electronAPI.loadIndex(); } catch (_) {}
    }
    if(isAppClosing) {
      window.windowAPI.appQuit();
    }
  } else {
    console.log("파일 삭제 실패", payload);
  }
});

// 업로드 요청 수신 및 처리
window.electronAPI.onRequestUpload((data) => {
  console.log("job 업로드 요청 수신", data);
  console.log("job 업로드 요청 수신 recordId : ", recordId);
  // 팝업에서 제목을 넣었으면 이후 세그먼트 저장(upsertRecording) 때도 그 이름을 쓴다(메인이 DB 이름도 바꿈)
  if (data && String(data.title || "").trim()) recordingName = String(data.title).trim();
  // jobs 테이블에 정보 저장
  window.dbAPI.enqueueUpload(recordId, data).then((res) => {
    if (res.success) {
      console.log("업로드 작업 추가 완료", res);
      uploadData = {
        jobId: res.jobId,
        lang: data.lang,
        attendeeNum: data.attendeeNum,
        title: data.title || "",
        templateId: data.templateId || "",
        recordId: recordId,
        filePath: outputDir,
        fileName: recordingName,
        type: 'single',
      }
      console.log("업로드 데이터 준비 완료 - 업로드 준비 상태 설정");
      isUploadDataReady = true;
      
      // 에러상활일 경우 업로드 시행
      if(isStoppedByError) {
        serverUpload(uploadData);
      } else {
        tryStartUpload();
      }
    } else {
      console.log("업로드 작업 추가 실패", res);
      return res;
    }
  });
});

// 업로드 리스트 상태 동기화
window.electronAPI.onUploadListState((payload) => {
  if (!payload || !payload.state) return;
  isUploadListOpen = payload.state === "opened";
});

// 녹음 중 앱종료 처리
window.windowAPI.onAppCloseRecording((event) => {
  console.log("녹음 중 앱요청 처리", event);
  switch(event.ev) {
    case "confirm_app_close_recording": 
      window.electronAPI.openPopupWindow({
        title: t("recording.popup_app_close_recording_title"),
        subtitle: t("recording.popup_app_close_recording_subtitle"),
        type: "app-close-recording",
        data: {
            isRecording: isRecording,
            outputDir: outputDir,
            recordId: recordId,
        },
        width: 373,
        height: 210,
      });
      break;
    case "stop_type_selected": {
      console.log("stop_type_selected", event);
      stopType = event.stopType;
      // 앱 종료 예약 트리거
      isAppClosing = true;
      if(stopType === 'cancel') {
        handleRecordingPause();
      }
      break;
    }
    default: 
      console.log("알수없는 요청:", event);
      break;
  }
});

// 최대 녹음 시간 도달 시 종료 처리
window.windowAPI.onMaxDurationStopped((event) => {
  console.log("최대 녹음 시간 도달 시 종료 처리", event);
  switch(event.stopType) {
    case "cancel":
      console.log("최대 녹음시간 도달 후 녹음 취소 처리");
      window.electronAPI.deleteRecording(outputDir);
      break;

    case "complete":
      console.log("최대 녹음시간 도달 후 녹음 종료 처리")
      break;
    
    default:
      console.log("알수없는 요청:", event);
      break;
  }
});

// === DOM 버튼 이벤트들 ===

// 최소화 버튼
minimizeBtn.addEventListener("click", () => {
  window.windowAPI.minimizeWindow();
});

// Top 버튼
topBtn.addEventListener("click", () => {
  toggleTopState();
});

// 음소거 아이콘
micIcon.addEventListener("click", () => {
  logAction("mute_toggled", { target: "mic", muted: !isMicMuted });
  if(isMicMuted){
    isMicMuted = false;
    micIcon.classList.remove("muted");
    window.electronAPI.sendHelperCommand({
      cmd: "set_mute",
      target: "mic",
      value: "off",
    });
  } else {
    isMicMuted = true;
    micIcon.classList.add("muted");
    window.electronAPI.sendHelperCommand({
      cmd: "set_mute",
      target: "mic",
      value: "on",
    });
  }
});

sysIcon.addEventListener("click", () => {
  logAction("mute_toggled", { target: "system", muted: !isSysMuted });
  if(isSysMuted){
    isSysMuted = false;
    sysIcon.classList.remove("muted");
    window.electronAPI.sendHelperCommand({
      cmd: "set_mute",
      target: "system",
      value: "off",
    });
  } else {
    isSysMuted = true;
    sysIcon.classList.add("muted");
    window.electronAPI.sendHelperCommand({
      cmd: "set_mute",
      target: "system",
      value: "on",
    });
  }
});

// 업로드 리스트 버튼
uploadListBtn.addEventListener("click", async () => {
  const state = await window.electronAPI.toggleUploadList();
  isUploadListOpen = state === "opened";
  logAction("upload_list_toggled", { state });
});

// 녹음 취소 버튼
recordCancelBtn.addEventListener("click", async () => {
  stopType = "cancel";
  logAction("recording_cancel_clicked", { sessionId, elapsedMs: getCurrentRecordingTime(), afterError: isStoppedByError });

  if(isStoppedByError) {
    console.log("오류로 인한 녹음 중단 상태에서 취소 버튼 클릭");
    handleRecordingCancelOnError();
    return;
  }
  
  handleRecordingPause();
});

// 녹음 종료 버튼
recordCompleteBtn.addEventListener("click", async () => {
  stopType = "complete";
  logAction("recording_complete_clicked", { sessionId, elapsedMs: getCurrentRecordingTime(), afterError: isStoppedByError });
  
  if(isStoppedByError) {
    console.log("오류로 인한 녹음 중단 상태에서 종료 버튼 클릭");
    handleRecordingCompleteOnError();
    return;
  }
  handleRecordingPause();
});

// 일시정지 버튼
pauseBtn.addEventListener("click", () => {
  if (!isRecording) {
    console.log("새로운 녹음 시작!");
    logAction("recording_start_clicked");
    window.electronAPI.sendHelperCommand({
      cmd: "stop_test",
    })
    startRecording(mic);
    recordingStatusCircle.classList.remove("hidden");
    return;
  }

  if (!isPaused) {
    logAction("recording_paused", { sessionId, elapsedMs: getCurrentRecordingTime() });
    handleRecordingPause();
  } else {
    logAction("recording_resumed", { sessionId, elapsedMs: getCurrentRecordingTime() });
    handleRecordingResume();
  }
});

// === 설정 메뉴 이벤트들 ===

// 설정 버튼
settingBtn.addEventListener("click", (e) => {
  console.log("settingBtn click", e);
  e.stopPropagation();
  if (settingsMenu.hidden) openMenu();
  else closeMenu();
});

window.addEventListener("resize", () => {
  if (!settingsMenu.hidden) positionMenu();
});
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !settingsMenu.hidden) closeMenu();
});

// 녹음이 진행/대기 중인지(녹음 중, 일시정지, 오류·최대시간으로 멈춰 업로드/삭제 선택 전)
// 장치 변경·로그아웃은 이때 막는다.
function isRecordingSessionActive() {
  return !!(isRecording || sessionId || isStoppedByError || isStoppedByMaxDuration);
}

// titleKey: recording.popup_busy_change_device / _logout / _language
function showBusyAlert(titleKey) {
  window.electronAPI.openPopupWindow({
    title: t(titleKey),
    subtitle: t("recording.popup_busy_subtitle"),
    type: "error-alert",
    width: 340,
    height: 190,
  });
}

// 장치 변경: 마이크 테스트 화면으로 이동(로그인 유지, 녹음 동의는 다시 체크)
if (changeDeviceBtn) {
  changeDeviceBtn.addEventListener("click", () => {
    const busy = isRecordingSessionActive();
    logAction("change_device_clicked", { blocked: busy });
    closeMenu();
    if (busy) {
      showBusyAlert("recording.popup_busy_change_device");
      return;
    }
    try { window.electronAPI.closeUploadList(); } catch (_) {}
    window.electronAPI.loadIndex();
  });
}

// 로그아웃: 확인 팝업 → 세션 삭제 → 로그인 화면 (popupWindow.js 'logout')
if (logoutBtn) {
  logoutBtn.addEventListener("click", () => {
    const busy = isRecordingSessionActive();
    logAction("logout_clicked", { blocked: busy });
    closeMenu();
    if (busy) {
      showBusyAlert("recording.popup_busy_logout");
      return;
    }
    window.electronAPI.openPopupWindow({
      title: t("recording.popup_logout_title"),
      subtitle: t("recording.popup_logout_subtitle"),
      type: "logout",
      width: 340,
      height: 190,
    });
  });
}

// 앱 종료 버튼 클릭 이벤트 리스너
closeAppBtn.addEventListener("click", () => {
  logAction("app_close_clicked", { isRecording });
  // if(!isRecording){
    // 녹음 중이 아닐때
    window.electronAPI.openPopupWindow({
      title: t("recording.popup_app_close_title"),
      type: "app-close",
      data: {
        isRecording: isRecording,
        outputDir: outputDir,
        recordId: recordId,
      },
      width: 283,
      height: 174,
    });
  // }
  // else{
  //   // 녹음 중일 때
  //   window.electronAPI.openPopupWindow({
  //     title: `<span>녹음 중입니다.</span> <br> <span>녹음을 종료하고 파일을 업로드 할까요?</span>`,
  //     subtitle: "업로드를 하지 않으면 녹음한 파일은 삭제됩니다.",
  //     type: "app-close-recording",
  //     width: 373,
  //     height: 210,
  //   });
  // }
});

// 언어 메뉴: MULTI_LANG_ENABLED 일 때만 보인다. 항목은 언어 목록으로 그리고 지금 언어에 ✓
function renderLanguageItems() {
  if (!settingsLanguageItems) return;
  const current = window.i18n.lang();
  settingsLanguageItems.innerHTML = "";
  window.i18n.languages().forEach((language) => {
    const btn = document.createElement("button");
    btn.className = "language-item";
    btn.dataset.lang = language.code;
    btn.textContent = language.name;
    if (language.code === current) btn.classList.add("selected");
    settingsLanguageItems.appendChild(btn);
  });
}

if (languageTab) {
  languageTab.hidden = !window.i18n.enabled();
  languageTab.addEventListener("click", (e) => {
    e.stopPropagation();
    openDetail(settingsLanguageItems, languageTab);
  });
  languageTab.addEventListener("mouseenter", () => {
    if (detailCloseTimer) clearTimeout(detailCloseTimer);
    scheduleOpenDetail(settingsLanguageItems, languageTab);
  });
  languageTab.addEventListener("mouseleave", () => {
    scheduleCloseDetail();
  });
}
if (settingsLanguageItems) {
  settingsLanguageItems.addEventListener("click", async (e) => {
    const btn = e.target instanceof HTMLElement ? e.target.closest("button[data-lang]") : null;
    if (!btn) return;
    const lang = btn.dataset.lang;
    const busy = isRecordingSessionActive();
    logAction("language_clicked", { lang, from: window.i18n.lang(), blocked: busy });
    closeMenu();
    // 녹음 중에는 막는다(장치 변경·로그아웃과 같음). 화면 문구가 섞이지 않게
    if (busy) {
      showBusyAlert("recording.popup_busy_language");
      return;
    }
    if (lang === window.i18n.lang()) return;
    try { await window.i18n.setLang(lang); } catch (_) {}
  });
  settingsLanguageItems.addEventListener("mouseenter", () => {
    if (detailCloseTimer) clearTimeout(detailCloseTimer);
  });
  settingsLanguageItems.addEventListener("mouseleave", () => {
    scheduleCloseDetail();
  });
}

// 언어가 바뀌면(data-i18n 은 preload 가 이미 바꿈) 스크립트가 그린 글자를 다시 그린다
window.i18n.onChange(() => {
  renderNoti();
  renderVersionTexts();
  syncMenuStateTexts();
  setStaticTooltips();
  updateTopTooltip();
  renderLanguageItems();
});

// 1뎁스 클릭 시 해당 서브메뉴 열기
if (alwaysOnTab) {
  alwaysOnTab.addEventListener("click", (e) => {
    e.stopPropagation();
    openDetail(settingsAotItems, alwaysOnTab);
  });
  // hover open/close
  alwaysOnTab.addEventListener("mouseenter", () => {
    if (detailCloseTimer) clearTimeout(detailCloseTimer);
    scheduleOpenDetail(settingsAotItems, alwaysOnTab);
  });
  alwaysOnTab.addEventListener("mouseleave", () => {
    scheduleCloseDetail();
  });
}
if (muteTab) {
  muteTab.addEventListener("click", (e) => {
    e.stopPropagation();
    openDetail(settingsMuteItems, muteTab);
  });
  // hover open/close
  muteTab.addEventListener("mouseenter", () => {
    if (detailCloseTimer) clearTimeout(detailCloseTimer);
    scheduleOpenDetail(settingsMuteItems, muteTab);
  });
  muteTab.addEventListener("mouseleave", () => {
    scheduleCloseDetail();
  });
}
// 선택 체크 표시 토글 유틸
function markSelected(containerEl, clickedBtn) {
  if (!containerEl || !clickedBtn) return;
  const all = containerEl.querySelectorAll("button");
  all.forEach((b) => b.classList.remove("selected"));
  clickedBtn.classList.add("selected");
}

// 각 서브메뉴 항목 클릭 시 체크 표시만 처리 (동작 연결은 별도)
if (settingsAotItems) {
  settingsAotItems.addEventListener("click", (e) => {
    const target = e.target;
    if (!(target instanceof HTMLElement)) return;
    const btn = target.closest("button");
    if (!btn) return;
    markSelected(settingsAotItems, btn);
    // 실제 동작 연결
    if (btn.id === "aot-item-1") {
      setTopState(true);
    } else if (btn.id === "aot-item-2") {
      setTopState(false);
    }
    // 동작 수행 후 메뉴 닫기
    closeMenu();
  });
  settingsAotItems.addEventListener("mouseenter", () => {
    if (detailCloseTimer) clearTimeout(detailCloseTimer);
  });
  settingsAotItems.addEventListener("mouseleave", () => {
    scheduleCloseDetail();
  });
}
if (settingsMuteItems) {
  settingsMuteItems.addEventListener("click", (e) => {
    const target = e.target;
    if (!(target instanceof HTMLElement)) return;
    const btn = target.closest("button");
    if (!btn) return;
    markSelected(settingsMuteItems, btn);
    logAction("mute_toggled", { target: "both", muted: btn.id === "mute-item-1" });
    // 실제 동작 연결: 둘 다 동일 상태로 설정
    if (btn.id === "mute-item-1") {
      // 음소거 설정 (둘 다 on)
      isMicMuted = true;
      isSysMuted = true;
      if (micIcon) micIcon.classList.add("muted");
      if (sysIcon) sysIcon.classList.add("muted");
      window.electronAPI.sendHelperCommand({
        cmd: "set_mute",
        target: "both",
        value: "on",
      });
    } else if (btn.id === "mute-item-2") {
      // 음소거 해제 (둘 다 off)
      isMicMuted = false;
      isSysMuted = false;
      if (micIcon) micIcon.classList.remove("muted");
      if (sysIcon) sysIcon.classList.remove("muted");
      window.electronAPI.sendHelperCommand({
        cmd: "set_mute",
        target: "both",
        value: "off",
      });
    }
    // 동작 수행 후 메뉴 닫기
    closeMenu();
  });
  settingsMuteItems.addEventListener("mouseenter", () => {
    if (detailCloseTimer) clearTimeout(detailCloseTimer);
  });
  settingsMuteItems.addEventListener("mouseleave", () => {
    scheduleCloseDetail();
  });
}
// 메뉴 자체에서 나갔다가 들어오는 경우 close 지연 제어
if (settingsMenu) {
  settingsMenu.addEventListener("mouseenter", () => {
    if (detailCloseTimer) clearTimeout(detailCloseTimer);
  });
  settingsMenu.addEventListener("mouseleave", () => {
    scheduleCloseDetail();
  });
}

// === Window 이벤트들 ===

// 창 크기 변경 시
window.addEventListener("resize", () => {
  [topBtn, minimizeBtn].forEach((b) => ensureTooltipAlignment(b));
  drawWave();
  if (!settingsMenu.hidden) positionMenu();
});

// 키보드 이벤트
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !settingsMenu.hidden) closeMenu();
});

// 호버/포커스 시 툴팁 정렬 재계산
[topBtn, minimizeBtn].forEach((b) => {
  if (!b) return;
  b.addEventListener("mouseenter", () => ensureTooltipAlignment(b));
  b.addEventListener("focus", () => ensureTooltipAlignment(b));
});

// ============================================
// 10. 초기화
// ============================================

// 초기 툴팁·안내 줄 (고른 언어로)
renderNoti();
setStaticTooltips();
updateTopTooltip();
startWave();
// 헬퍼는 마이크 테스트 화면에서 이미 켜져 있어 helper_info 가 다시 오지 않으므로 버전을 직접 묻는다.
window.electronAPI.sendHelperCommand({ cmd: "get_version" });

// 녹음 창은 크기 고정 (메모 모드가 없어져 늘릴 이유가 없다). 값은 index.js 의 녹음 화면 전환과 맞춘다.
const RECORDING_WINDOW_WIDTH = 360;
const RECORDING_WINDOW_HEIGHT = 320;
function applyRecordingWindowSize() {
  window.electronAPI.setWindowConstraints({
    resizable: false,
    minWidth: RECORDING_WINDOW_WIDTH,
    minHeight: RECORDING_WINDOW_HEIGHT,
    maxWidth: RECORDING_WINDOW_WIDTH,
    maxHeight: RECORDING_WINDOW_HEIGHT,
    width: RECORDING_WINDOW_WIDTH,
    height: RECORDING_WINDOW_HEIGHT,
  });
}

// 화면 로드시 녹음 시작
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", async () => {
    applyRecordingWindowSize();
    
    // 약간의 딜레이 추가 (Helper 정리 대기)
    await new Promise(resolve => setTimeout(resolve, 300));
    startRecording(mic);
  });
} else {
  applyRecordingWindowSize();
  
  setTimeout(() => startRecording(mic), 300);
}
