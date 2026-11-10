// 공통 영역
const popupTitle = document.querySelector('.popup-title');
const popupSubtitle = document.querySelector('.popup-subtitle');
const popupWarning = document.querySelector('.popup-warning');

// 버튼 영역
const cancelBtn = document.querySelector('#cancelBtn');
const confirmBtn = document.querySelector('#confirmBtn');

// 프로그레스 바 영역
const progressArea = document.querySelector('.progress-area');
const progressBar = document.querySelector('.progress-bar');
const progressBarPercent = document.querySelector('.progress-bar-percent');
const progressText = document.querySelector('.progress-text');


let popupType;
let dir;
let job;
let data;
let isFailed = false;
let isWaitingForResponse = false;

// 진행률 보간 상태
let displayedPercent = 0;
let targetPercent = 0;
let animRafId = null;
let lastAnimTs = 0;
const MAX_PERCENT_PER_SEC = 80; // 초당 최대 50% 상승 속도

// 앱 종료 처리 플래그
let isAppClosing = false;

// 사용자 동작 로그 (로그 서버 category:"user_action"). 팝업 종류(type)로 어떤 선택인지 구분한다.
// 예) type=cancel 확인 = 녹음 삭제, type=complete 확인 = 업로드 진행, type=upload-progress 확인 = 업로드 재시도
function logAction(action, context) {
  try { window.developerAPI.logAction(action, context); } catch (_) {}
}

function updateDisplayedPercent(p) {
  const rounded = Math.max(0, Math.min(100, Math.round(p)));
  progressBar.style.width = `${rounded}%`;
  progressBarPercent.textContent = `${rounded}%`;
}

function animStep(ts) {
  if (isFailed) {
    try { cancelAnimationFrame(animRafId); } catch (_) {}
    animRafId = null;
    return;
  }
  if (!lastAnimTs) lastAnimTs = ts;
  const dt = Math.max(0, (ts - lastAnimTs) / 1000);
  lastAnimTs = ts;

  if (targetPercent > displayedPercent) {
    const increment = MAX_PERCENT_PER_SEC * dt;
    displayedPercent = Math.min(targetPercent, displayedPercent + increment);
    updateDisplayedPercent(displayedPercent);
  }

  // 100% 도달 시점에 안내/애니메이션 전환 (서버 응답 대기)
  if (targetPercent >= 100 && displayedPercent >= 100 && !isWaitingForResponse) {
    isWaitingForResponse = true;
    try {
      popupTitle.textContent = '업로드 마무리 중';
      popupSubtitle.textContent = '서버에서 파일을 확인하고 있습니다...';
      progressArea.classList.add('indeterminate');
      progressBarPercent.textContent = '100%';
    } catch (_) {}
  }

  // 목표 도달했고 대기 상태가 아니면 루프 중지하여 CPU 절약
  const shouldStop = displayedPercent >= targetPercent && !(targetPercent >= 100 && !isWaitingForResponse);
  if (shouldStop) {
    try { cancelAnimationFrame(animRafId); } catch (_) {}
    animRafId = null;
    lastAnimTs = 0;
    return;
  }
  animRafId = requestAnimationFrame(animStep);
}

window.electronAPI.onApplyPopupWindow((options) => {
  
  popupType = options.type;
  dir = options.dir || '';
  job = options.job || null;
  data = options.data || null;
  popupTitle.innerHTML = options?.title ?? '';
  popupSubtitle.innerHTML = options?.subtitle ?? '';
  popupWarning.textContent = options?.warning ?? '';
  logAction('popup_shown', { popupType });
  switch (popupType) {
    case 'error-alert': {
      cancelBtn.classList.add('hidden');
      break;
    }
    case 'error-alert-warning': {
      cancelBtn.classList.add('hidden');
      popupWarning.classList.remove('hidden');
      break;
    }
    case 'disk-space-low-stop': {
      cancelBtn.classList.add('hidden');
      popupWarning.classList.remove('hidden');
      break;
    }

    case 'upload-progress': {
      cancelBtn.classList.add('hidden');
      confirmBtn.classList.add('hidden');
      progressArea.classList.remove('hidden');
      // 초기화: 대기 상태 해제 및 애니메이션 제거
      isWaitingForResponse = false;
      try { progressArea.classList.remove('indeterminate'); } catch (_) {}
      // 진행률 보간 초기화
      isFailed = false;
      displayedPercent = 0;
      targetPercent = 0;
      if (animRafId) { try { cancelAnimationFrame(animRafId); } catch (_) {} animRafId = null; }
      lastAnimTs = 0;
      updateDisplayedPercent(0);
      break;
    }
    case 'recovery-result': {
      // 복구 결과 안내: 버튼 라벨을 두 가지 선택지로 변경
      confirmBtn.textContent = '업로드 리스트';
      cancelBtn.textContent = '닫기';
      popupWarning.classList.remove('hidden');
      cancelBtn.classList.remove('hidden');
      confirmBtn.classList.remove('hidden');
      try { progressArea.classList.add('hidden'); } catch (_) {}
      break;
    }
    case 'confirm-retry-multi': {
      // 다건 재시도 확인 팝업
      confirmBtn.textContent = '확인';
      cancelBtn.textContent = '취소';
      cancelBtn.classList.remove('hidden');
      confirmBtn.classList.remove('hidden');
      try { progressArea.classList.add('hidden'); } catch (_) {}
      break;
    }
    case 'app-close-recording': {
      cancelBtn.textContent = '녹음 삭제';
      confirmBtn.textContent = '파일 업로드';
      break;
    }

    case 'max_duration_stopped': {
      cancelBtn.textContent = '녹음 취소';
      confirmBtn.textContent = '파일 업로드';
      break;
    }

    case 'device_change': {
      cancelBtn.classList.add('hidden');
    }

    default: {
      break;
    }
  }
});

// 취소 버튼 클릭
cancelBtn.addEventListener('click', (e) => {
  logAction('popup_cancel_clicked', { popupType });
  switch (popupType) {
    case 'recovery-result': {
      window.electronAPI.sendRecoveryAction('close');
      break;
    }
    case 'app-close-recording': {
      window.windowAPI.sendAppCloseRecording({
        cmd: 'select_stop_type',
        stopType: 'cancel',
      });
      window.windowAPI.closeWindow();
      break;
    }

    case 'max_duration_stopped': {
      window.windowAPI.sendMaxDurationStopped({
        cmd: 'select_stop_type',
        stopType: 'cancel',
      });
      window.windowAPI.closeWindow();
      break;
    }

    default: {
      window.windowAPI.closeWindow();
      break;
    }
  }
});

// 확인 버튼 클릭
confirmBtn.addEventListener('click', (e) => {
  logAction('popup_confirm_clicked', { popupType, isFailed });
  switch (popupType) {
    case 'complete': {
      window.windowAPI.closeWindow();

      window.electronAPI.openSummarize({
        width: 670,
        height: 615,
      });
      break;
    }

    case 'error_complete': {
      window.windowAPI.closeWindow();

      window.electronAPI.openSummarize({
        width: 670,
        height: 615,
        isError: true,
      });

      break;
    }

    case 'cancel': {
      window.electronAPI.sendHelperCommand({
        cmd: "stop",
      });

      window.windowAPI.closeWindow();
      break;
    }

    case 'error_cancel': {
      window.electronAPI.deleteRecording(dir);
      window.windowAPI.closeWindow();
      break;
    }
    
    case 'remove-job': {
      if (job) {
        window.dbAPI.removeJob(job).then((res) => {
          // 메인에서 브로드캐스트하도록 수정되면, 여기서는 단순 닫기만
          window.windowAPI.closeWindow();
        }).catch(() => {
          window.windowAPI.closeWindow();
        });
      } else {
        window.windowAPI.closeWindow();
      }
      break;
    }
    case 'disk-space-low-stop': {
      window.windowAPI.closeWindow();
      
      break;
    }

    case 'app-close': {
      if(data?.isRecording) {
        // 녹음 중일때
        window.windowAPI.sendAppCloseRecording({
          cmd: 'confirm_app_close_recording',
        });
      }else {
        // 녹음 중이 아닐때
        window.windowAPI.appQuit();
      }
      break;
    }
    case 'app-close-recording': {
      window.windowAPI.closeWindow();
      window.windowAPI.sendAppCloseRecording({
        cmd: 'select_stop_type',
        stopType: 'complete',
      })
      window.electronAPI.openSummarize({
        width: 670,
        height: 615,
      });
      break;
    }
    
    case 'max_duration_stopped': {
      window.windowAPI.closeWindow();
      window.windowAPI.sendMaxDurationStopped({
        cmd: 'select_stop_type',
        stopType: 'complete',
      });
      window.electronAPI.openSummarize({
        width: 670,
        height: 615,
        isLimitDurationStopped: true,
      });
      break;
    }

    case 'recovery-result': {
      // 업로드 리스트 열기 선택
      window.electronAPI.sendRecoveryAction('open-upload-list');
      window.windowAPI.closeWindow();
      break;
    }
    case 'confirm-retry-multi': {
      // 메인 프로세스에 확인 선택 알림(선택 아이템은 열기 시 options.data로 전달)
      const items = Array.isArray(data) ? data : (data ? [data] : []);
      window.serviceAPI.retryServerUploads(items);
      window.windowAPI.closeWindow();
      break;
    }
    // case 'error-alert': {
    //   window.windowAPI.closeWindow();
    //   break;
    // }

    case 'upload-progress': {

      if(isAppClosing) {
        window.windowAPI.appQuit();
        return;
      }
      
      const retryData = { 
        recording_id: data?.recordId,
        file_path: data?.filePath,
        file_name: data?.fileName,
        job_id: data?.jobId,
      }
      window.serviceAPI.retryServerUpload(retryData);

      break;
    }
    
    case 'device_change': {
      // 초기화면으로 이동
      window.windowAPI.goHome();
      break;
    }

    default: {
      window.windowAPI.closeWindow();
      break;
    }
  }
});

// 업로드 진행 이벤트 수신
window.electronAPI.onUploadProgress((payload) => {
  if (popupType !== 'upload-progress' || isFailed) return; // 실패 이후 업데이트 무시
  const percent = Math.max(0, Math.min(100, Number(payload?.percent ?? payload?.progress ?? 0)));
  const speed = payload?.speedReadable || payload?.speed || '';
  const eta = payload?.etaReadable || payload?.etaSeconds || '';
  
  // 목표 퍼센트만 갱신하고, 실제 UI는 보간 루프에서 업데이트
  targetPercent = percent;
  if (!animRafId) {
    animRafId = requestAnimationFrame(animStep);
  }

  const speedText = typeof speed === 'string' ? speed : '';
  const etaText = typeof eta === 'string' ? eta : '';
  progressText.textContent = `전송 속도: ${speedText}`;
  popupSubtitle.textContent = `업로드가 완료될 때까지 기다려 주세요.(약 ${etaText}남음)`;

});

// 업로드 실패 이벤트 수신: 팝업 UI를 실패 상태로 전환
window.electronAPI.onUploadFailed((payload) => {
  if (popupType !== 'upload-progress') return;
  isFailed = true;
  isWaitingForResponse = false;
  isAppClosing = payload?.isAppClosing ?? false;

  try { progressArea.classList.remove('indeterminate'); } catch (_) {}
  popupTitle.textContent = '업로드 실패';

  if(isAppClosing) {
    popupSubtitle.innerHTML = `
      <span>업로드에 실패했습니다.</span><br>
      <span>애플리케이션을 종료합니다.(${(payload && payload.message) ? String(payload.message) : '네트워크 또는 서버 오류가 발생했습니다.'})</span>
    `;
    confirmBtn.textContent = '확인';
    confirmBtn.classList.remove('hidden');
  }else {
    popupSubtitle.innerHTML = `
      <span>업로드에 실패했습니다.</span><br>
      <span>다시 시도해 주세요.(${(payload && payload.message) ? String(payload.message) : '네트워크 또는 서버 오류가 발생했습니다.'})</span>
    `
    // 바/퍼센트 유지하되 색상/스타일을 경고로 전환하고 버튼 노출
    document.querySelector('.progress-bar').style.background = '#EF4444';
    document.querySelector('.progress-bar-percent').style.color = '#EF4444';
    
    // 버튼 노출
    confirmBtn.classList.remove('hidden');
    cancelBtn.classList.remove('hidden');
    confirmBtn.textContent = '재시도';
  }
});

