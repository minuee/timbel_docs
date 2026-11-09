const micSelect = document.getElementById("mic-select");
const startBtn = document.getElementById("start-recording-btn");
const micMeter = document.getElementById("micMeter");
const sysMeter = document.getElementById("sysMeter");
const checkAgree = document.getElementById("check");
const minimizeBtn = document.getElementById("minimizeBtn");
const closeBtn = document.getElementById("closeBtn");
const checkTextDetail = document.querySelector(".check-text-detail");

const modeSelect = document.getElementById("mode-select");
const modeHint = document.getElementById("modeHint");
const renderSelect = document.getElementById("render-select");
const renderGroup = document.getElementById("renderGroup");

const languageSelectWrap = document.getElementById("languageSelectWrap");

const checkCloseBtn = document.getElementById("checkCloseBtn");
const checkCloseBtnImg = checkCloseBtn.querySelector("img");

// 시작 시 기본 비활성화
startBtn.disabled = true;
let checkIsClosed = false;

let isTestStarted = false;
let deviceChanged = false;

// 캡처 모드 (녹음 대상) — Helper의 CaptureMode와 1:1 대응
const DEFAULT_CAPTURE_MODE = "MicPlusSystem";
const VALID_CAPTURE_MODES = ["MicPlusSystem", "MicOnly", "SystemOnly"];

// 현재 선택된 캡처 모드. 저장값이 깨져 있어도 항상 유효한 값을 돌려준다.
function getCaptureMode() {
  const saved = localStorage.getItem("captureMode");
  return VALID_CAPTURE_MODES.includes(saved) ? saved : DEFAULT_CAPTURE_MODE;
}

// 캡처할 출력(스피커) 장치 ID. "default"면 Helper가 기본 출력 장치를 쓴다.
// macOS Helper는 renderDevices를 보고하지 않으므로 항상 "default"가 된다.
function getRenderDeviceId() {
  return localStorage.getItem("render") || "default";
}

// --- 창 크기 -------------------------------------------------------------
// body가 height:100vh + overflow:hidden이라 콘텐츠가 넘치면 잘려서 보이지 않는다.
// (모드 선택 행/안내 문구가 추가되면서 녹음 시작 버튼이 잘리는 문제가 있었다)
// 고정 높이 대신 마지막 요소(녹음 시작 버튼)의 실제 위치를 measure해서 창을 맞춘다.
// 창 위치는 그대로 두고 아래로만 늘어난다. 화면 아래 끝을 넘으면 거기까지만 키우고 스크롤로 본다.
// (요소가 줄어들지 않는 건 micTest.css 의 flex-shrink:0 덕분이다. 없으면 버튼이 찌그러져 측정이 틀린다)
const WINDOW_WIDTH = 380;
const WINDOW_MIN_HEIGHT = 336;
const WINDOW_BOTTOM_MARGIN = 16; // 시작 버튼 아래 여백

// 창 윗변부터 화면(작업 표시줄 제외) 아래 끝까지의 높이
function maxHeightOnScreen() {
  const availTop = window.screen.availTop || 0;
  const availBottom = availTop + window.screen.availHeight;
  return Math.max(WINDOW_MIN_HEIGHT, availBottom - window.screenY);
}

function applyWindowSize() {
  // 레이아웃이 확정된 다음 프레임에 측정한다.
  requestAnimationFrame(() => {
    try {
      // 스크롤된 상태여도 문서 기준 위치로 잰다. 스크롤은 body(height:100vh)에서 생긴다.
      const scrolled = document.body.scrollTop || window.scrollY || 0;
      // 맨 아래 요소: 언어 선택(MULTI_LANG_ENABLED 일 때만 보임) 또는 녹음 시작 버튼
      const last = languageSelectWrap && !languageSelectWrap.hidden ? languageSelectWrap : startBtn;
      const bottom = last.getBoundingClientRect().bottom + scrolled;
      const needed = Math.ceil(bottom + WINDOW_BOTTOM_MARGIN);
      const height = Math.min(maxHeightOnScreen(), Math.max(WINDOW_MIN_HEIGHT, needed));

      window.electronAPI.setWindowConstraints({
        resizable: true,
        minWidth: WINDOW_WIDTH,
        maxWidth: WINDOW_WIDTH,
        width: WINDOW_WIDTH,
        minHeight: WINDOW_MIN_HEIGHT,
        maxHeight: height,
        height: height,
      });
    } catch (error) {
      console.log(`Window resize failed: ${error.message}`);
    }
  });
}

// SystemOnly는 사용자가 가장 헷갈리는 모드라 별도 안내를 띄운다.
// (Zoom 출력이 다른 스피커로 가 있으면 무음이 녹음되는데, 원인을 찾기 어렵다)
function updateModeHint() {
  if (!modeHint) return;
  if (getCaptureMode() === "SystemOnly") {
    modeHint.textContent = window.i18n.t("mic_test.system_only_hint");
    modeHint.hidden = false;
  } else {
    modeHint.hidden = true;
    modeHint.textContent = "";
  }
  // 안내 문구 유무에 따라 전체 높이가 달라지므로 창 크기를 다시 맞춘다.
  applyWindowSize();
}

// 사용자 동작 로그 (로그 서버 category:"user_action")
function logAction(action, context) {
  try { window.developerAPI.logAction(action, context); } catch (_) {}
}

function selectedMicName() {
  const option = micSelect.selectedOptions && micSelect.selectedOptions[0];
  return option ? option.textContent : "";
}

function updateStartButtonState() {
  const micSelected = Boolean(micSelect.value);
  const agreed = Boolean(checkAgree && checkAgree.checked);
  startBtn.disabled = !(micSelected && agreed);
  if(agreed) {
    textToggleOff();
  } else {
    textToggleOn();
  }
}

minimizeBtn.addEventListener("click", () => {
  window.windowAPI.minimizeWindow();
});
closeBtn.addEventListener("click", () => {
  window.windowAPI.closeWindow();
});

// recording Module Init
async function initRecordingModule() {
  window.developerAPI.sendInfo("recording Module Init...");
  console.log("recording Module Init...");
  try {
    const result = await window.electronAPI.startAudioHelper();

    if (result.success) {
      window.developerAPI.sendInfo("Audio Helper Started.");
      console.log("Audio Helper Started.");
      
      await requestDeviceList();
      
    } else {
      throw new Error(result.error);
    }

  } catch (error) {
    window.developerAPI.sendInfo(`Audio Helper Start Failed: ${error.message}`);
    console.log(`Audio Helper Start Failed: ${error.message}`);
  }
}

function setupTooltips() {
  const helpIcons = document.querySelectorAll('.help-icon');
  const hideTimers = new WeakMap();

  function position(icon) {
    const tooltip = icon.querySelector('.tooltip');
    if (!tooltip) return;
    const rect = icon.getBoundingClientRect();
    // 아이콘 위로 10px 간격 두고 배치
    const top = Math.round(rect.top - (tooltip.offsetHeight || 82) - 7);
    tooltip.style.top = `${top}px`;

    // 꼬리 좌우 오프셋: 툴팁 중앙(뷰포트 50%) 대비 아이콘 중심 X의 차이
    const iconCenterX = rect.left + rect.width / 2;
    const viewportCenterX = window.innerWidth / 2;
    const offset = Math.round(iconCenterX - viewportCenterX);
    tooltip.style.setProperty('--arrow-offset', `${offset}px`);
  }

  function open(icon) {
    const tooltip = icon.querySelector('.tooltip');
    if (!tooltip) return;
    position(icon);
    icon.setAttribute('data-open', 'true');
    tooltip.setAttribute('aria-hidden', 'false');
    clearClose(icon);
  }

  function close(icon) {
    const tooltip = icon.querySelector('.tooltip');
    if (!tooltip) return;
    clearClose(icon);
    icon.removeAttribute('data-open');
    tooltip.setAttribute('aria-hidden', 'true');
    // 클릭으로 인해 포커스가 남아있으면 CSS :focus 규칙으로 계속 보일 수 있으므로 포커스를 제거
    if (document.activeElement === icon) {
      icon.blur();
    }
  }

  function scheduleClose(icon, delayMs = 500) {
    clearClose(icon);
    const timer = setTimeout(() => close(icon), delayMs);
    hideTimers.set(icon, timer);
  }

  function clearClose(icon) {
    const timer = hideTimers.get(icon);
    if (timer) {
      clearTimeout(timer);
      hideTimers.delete(icon);
    }
  }

  helpIcons.forEach((icon) => {
    icon.addEventListener('mouseenter', () => open(icon));
    icon.addEventListener('focus', () => open(icon));
    icon.addEventListener('mousedown', () => scheduleClose(icon, 500));
    icon.addEventListener('mouseleave', () => scheduleClose(icon, 500));
    icon.addEventListener('blur', () => scheduleClose(icon, 500));
  });

  window.addEventListener('resize', () => {
    document.querySelectorAll('.help-icon[data-open="true"]').forEach((icon) => position(icon));
  });
  window.addEventListener('scroll', () => {
    document.querySelectorAll('.help-icon[data-open="true"]').forEach((icon) => position(icon));
  }, { passive: true });
}

// 초기 창 크기는 실제 콘텐츠를 측정해 맞춘다(applyWindowSize).
// 모드 선택 행/안내 문구처럼 콘텐츠가 늘어나도 하단 버튼이 잘리지 않는다.
function initWindow() {
  logAction("mic_test_opened");
  applyWindowSize();
  initRecordingModule();
  setupTooltips();
  showUserName();
}

// 로그인한 사용자 이름을 타이틀에 붙인다. 이름을 모르면(내 정보 조회 실패 등) 앱 이름만 둔다.
async function showUserName() {
  const titleText = document.getElementById("titleText");
  titleText.textContent = window.i18n.t("common.app_title");
  try {
    const status = await window.authAPI.getStatus();
    const name = status && status.profile && status.profile.name;
    if (name) titleText.textContent = window.i18n.t("common.app_title_with_name", { name });
  } catch (_) {}
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initWindow);
} else {
  // 이미 DOM이 준비된 상태
  initWindow();
}

// 장치 목록 가져오기
async function requestDeviceList() {
  try {
    const command = { cmd: "list_devices" };
    const result = await window.electronAPI.sendHelperCommand(command);
    if (result.success) {
      window.developerAPI.sendInfo("Device List Requested.");
      console.log("Device List Requested.ggo");
    } else {
      throw new Error(result.error);
    }
    return { success: true };
  } catch (error) {
    window.developerAPI.sendInfo(`Device List Request Failed: ${error.message}`);
    console.log(`Device List Request Failed: ${error.message}`);
    return { success: false };
  }
}

// 오디오 레벨 Listener
window.electronAPI.onHelperEvent( (event) => {
  switch (event.ev) {
    case "level":
      updateLevelMeter(event.source, event.rms);
      break;
    case "test_started":
      console.log("테스트가 시작되었습니다");
      isTestStarted = true;
      break;
    case "test_stopped":
      console.log("테스트가 중지되었습니다");
      isTestStarted = false;
      if(deviceChanged) {
        changeDeviceEvent(event);
        deviceChanged = false;
      }
      break;
    case "devices":
      updateDeviceList(event.devices, event.renderDevices);
      break;
    
    case "audio_device_change":
      deviceChanged = true;
      console.log("마이크 장치 변경으로 장치 목록 갱신")
      window.electronAPI.sendHelperCommand({
        cmd: "stop_test",
      });
      requestDeviceList();
      break;

    case "error":
      console.log(`헬퍼 오류: ${event.message}, code: ${event.code}`, event);
      switch (event.code) {
        case "MIC_DEVICE_CHANGED":
          console.log("마이크 장치 변경으로 장치 목록 갱신")
          requestDeviceList();
      }
    case "waveform":
      
      break;

    default:
      console.log('📡 Helper Event:', event);
      break;
  }

});

// 장치 변경 알림 이벤트
async function changeDeviceEvent(event) {
  console.log(`장치 ${event.change_type}: ${event.device_type}`);
  await requestDeviceList();

  if(event.change_type === "added") {
    console.log("장치 추가 알림");
  }else if(event.change_type === "removed") {
    console.log("장치 제거 알림");
  }
}


// 출력(스피커) 장치 목록 갱신.
// Windows Helper만 renderDevices를 보고한다. 목록이 오지 않으면(=macOS) 행을 감춘 채
// "default"로 동작하며, 이는 ScreenCaptureKit이 시스템 믹스를 통째로 잡는 동작과 일치한다.
let lastRenderDevices = null; // 언어가 바뀌면 "기본 출력 장치"·"(기본)" 글자를 다시 그리려고 남겨 둔다
function updateRenderDeviceList(renderDevices) {
  lastRenderDevices = renderDevices;
  if (!Array.isArray(renderDevices) || renderDevices.length === 0) {
    renderGroup.hidden = true;
    return;
  }

  const saved = getRenderDeviceId();
  renderSelect.innerHTML = '';

  const defaultOption = document.createElement("option");
  defaultOption.value = "default";
  defaultOption.textContent = window.i18n.t("mic_test.default_output");
  renderSelect.appendChild(defaultOption);

  renderDevices.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.id;
    option.textContent = device.isDefault ? window.i18n.t("mic_test.device_default", { name: device.name }) : device.name;
    renderSelect.appendChild(option);
  });

  // 저장된 장치가 사라졌을 수 있으므로 존재할 때만 복원한다.
  const exists = renderDevices.some((d) => d.id === saved);
  renderSelect.value = exists ? saved : "default";
  if (!exists && saved !== "default") {
    localStorage.setItem("render", "default");
  }

  renderGroup.hidden = false;
}

async function updateDeviceList(devices, renderDevices) {
  console.log("Device List Requested.!");
  console.log("Device List:", devices);
  micSelect.innerHTML = '';
  // micSelect.innerHTML = '<option value="default">기본값 - 마이크 배열(디지털)</option>';

  try {
    devices.forEach((device) => {
      const option = document.createElement("option");
      option.value = device.id;
      option.textContent = device.name;
      micSelect.appendChild(option);
    });
  } catch (error) {
    window.developerAPI.sendInfo(
      `Device List Processing Failed: ${error.message}`
    );
    console.log(`Device List Processing Failed: ${error.message}`);
  }

  updateRenderDeviceList(renderDevices);

  console.log("isTestStarted", isTestStarted);
  if(!isTestStarted) {
    await window.electronAPI.sendHelperCommand({
      cmd: 'start_test',
      mode: getCaptureMode(),
      mic: devices[0].id,
      render: getRenderDeviceId(),
    });

    localStorage.setItem("mic", devices[0].id);
  }
  updateStartButtonState();
}

// Helper 무음 임계값과 일치하도록 UI 레벨미터 하한을 맞춘다
const HELPER_SILENCE_THRESHOLD = 0.02; // RMS 기준 (~ -34 dBFS)

// 레벨 미터 업데이트 함수
function updateLevelMeter(source, rms) {
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


// 레벨 미터 박스 업데이트 함수
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

// 마이크/모드 변경 시 테스트를 현재 설정으로 다시 시작한다.
// Helper는 모드를 start_test 시점에만 읽으므로 반드시 stop → start 순서를 지켜야 한다.
async function restartTest() {
  try {
    // stop_test가 완료될 때까지 대기
    if(isTestStarted) {
      await window.electronAPI.sendHelperCommand({
        cmd: "stop_test",
      });

      // Helper가 완전히 중지될 시간 확보
      await new Promise(resolve => setTimeout(resolve, 100));
    }

    // stop_test 완료 후 start_test 실행
    await window.electronAPI.sendHelperCommand({
      cmd: "start_test",
      mode: getCaptureMode(),
      mic: micSelect.value,
      render: getRenderDeviceId(),
    });

  } catch (error) {
    window.developerAPI.sendInfo(`Audio Test Start Failed: ${error.message}`);
  }
  updateStartButtonState();
}

// 마이크 선택 시 오디오 테스트 모듈 호출
micSelect.addEventListener("change", async () => {
  localStorage.setItem("mic", micSelect.value);
  logAction("mic_selected", { micName: selectedMicName() });
  await restartTest();
});

// 녹음 대상(캡처 모드) 변경
modeSelect.addEventListener("change", async () => {
  const mode = VALID_CAPTURE_MODES.includes(modeSelect.value)
    ? modeSelect.value
    : DEFAULT_CAPTURE_MODE;
  localStorage.setItem("captureMode", mode);
  modeSelect.value = mode;
  logAction("capture_mode_changed", { captureMode: mode });
  updateModeHint();
  await restartTest();
});

// 캡처할 출력(스피커) 장치 변경 — Windows에서만 노출된다.
renderSelect.addEventListener("change", async () => {
  localStorage.setItem("render", renderSelect.value || "default");
  const renderOption = renderSelect.selectedOptions && renderSelect.selectedOptions[0];
  logAction("render_device_changed", { renderName: renderOption ? renderOption.textContent : "" });
  await restartTest();
});

// 언어 선택 상자(languageSelect.js)로 바뀌면 스크립트가 그린 글자를 다시 그린다(나머지는 preload 가 바꿈)
window.i18n.onChange(() => {
  updateModeHint(); // 창 크기도 다시 맞춘다
  showUserName();
  if (lastRenderDevices) updateRenderDeviceList(lastRenderDevices);
});

// 저장된 캡처 모드 복원 (스크립트는 body 끝에서 로드되므로 엘리먼트는 이미 존재)
modeSelect.value = getCaptureMode();
updateModeHint();

// 체크박스 변경 시 버튼 상태 업데이트

checkAgree.addEventListener("change", () => {
  logAction("notice_agreed", { checked: checkAgree.checked });
  updateStartButtonState();
});


checkCloseBtn.addEventListener("click", () => {
  if(checkIsClosed) {
    textToggleOff();
  } else {
    textToggleOn();
  }
});

startBtn.addEventListener("click", async () => {
  await window.electronAPI.sendHelperCommand({
    cmd: "stop_test",
  });

  // Helper가 완전히 중지될 시간 확보
  await new Promise(resolve => setTimeout(resolve, 200));

  if(!startBtn.disabled) {
    logAction("recording_screen_opened", { micName: selectedMicName(), captureMode: getCaptureMode() });
    // 녹음 화면으로 전환 전에 창 크기 설정
    // 녹음 화면 크기 (recording.js 의 RECORDING_WINDOW_* 와 같게)
    window.electronAPI.setWindowConstraints({
      resizable: false,
      minWidth: 360,
      minHeight: 320,
      maxWidth: 360,
      maxHeight: 320,
      width: 360,
      height: 320
    });
    window.location.href = "./pages/recordingWindow.html";
  }
});

function textToggleOn() {
  checkTextDetail.classList.remove("hidden");
  checkCloseBtnImg.src = "./assets/icons/arrow_top.svg";

  // 펼친 상태의 실제 콘텐츠 높이에 맞춰 확장
  applyWindowSize();

  checkIsClosed = !checkIsClosed;
}

function textToggleOff() {
  checkTextDetail.classList.add("hidden");
  checkCloseBtnImg.src = "./assets/icons/arrow_bottom.svg";

  // 접힌 상태의 실제 콘텐츠 높이에 맞춰 축소
  applyWindowSize();

  checkIsClosed = !checkIsClosed;
}