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
let isSucceeded = false;
let isLost = false; // 업로드 실패 중 유실(누락 조각이 PC 에 없음) → [확인]은 닫기만
let isWaitingForResponse = false;

// 진행률 보간 상태
let displayedPercent = 0;
let targetPercent = 0;
let animRafId = null;
let lastAnimTs = 0;
const MAX_PERCENT_PER_SEC = 80; // 초당 최대 50% 상승 속도

// 앱 종료 처리 플래그
let isAppClosing = false;

// 화면 문구 (src/locales/*.json). 제목·내용은 팝업을 여는 쪽이 이미 바꾼 문구를 넘긴다.
const t = (key, params) => window.i18n.t(key, params);

// 사용자 동작 로그 (로그 서버 category:"user_action"). 팝업 종류(type)로 어떤 선택인지 구분한다.
// 예) type=cancel 확인 = 녹음 삭제, type=complete 확인 = 업로드 진행, type=upload-progress 확인 = 업로드 재시도
function logAction(action, context) {
  try { window.developerAPI.logAction(action, context); } catch (_) {}
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
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
      popupTitle.textContent = t('popup.upload_finishing_title');
      popupSubtitle.textContent = t('popup.upload_finishing_subtitle');
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
  // 버튼 기본 문구. 아래 종류별로 바꾼다(팝업 창을 다시 쓸 때 앞 종류의 문구가 남지 않게 매번 되돌린다)
  cancelBtn.textContent = t('common.cancel');
  confirmBtn.textContent = t('common.ok');
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
      isSucceeded = false;
      isLost = false;
      displayedPercent = 0;
      targetPercent = 0;
      if (animRafId) { try { cancelAnimationFrame(animRafId); } catch (_) {} animRafId = null; }
      lastAnimTs = 0;
      updateDisplayedPercent(0);
      // HTML 의 자리표시 문구("5.3MB/초") 대신 빈 속도로 시작 — 첫 진행 이벤트에서 채워진다
      progressText.textContent = t('popup.upload_speed', { speed: '' });
      break;
    }
    case 'recovery-result': {
      // 복구 결과 안내: 버튼 라벨을 두 가지 선택지로 변경
      confirmBtn.textContent = t('popup.btn_upload_list');
      cancelBtn.textContent = t('common.close');
      popupWarning.classList.remove('hidden');
      cancelBtn.classList.remove('hidden');
      confirmBtn.classList.remove('hidden');
      try { progressArea.classList.add('hidden'); } catch (_) {}
      break;
    }
    case 'confirm-retry-multi': {
      // 다건 재시도 확인 팝업
      confirmBtn.textContent = t('common.ok');
      cancelBtn.textContent = t('common.cancel');
      cancelBtn.classList.remove('hidden');
      confirmBtn.classList.remove('hidden');
      try { progressArea.classList.add('hidden'); } catch (_) {}
      break;
    }
    case 'app-close-recording': {
      cancelBtn.textContent = t('popup.btn_delete_recording');
      confirmBtn.textContent = t('popup.btn_upload_file');
      break;
    }

    case 'max_duration_stopped': {
      cancelBtn.textContent = t('popup.btn_cancel_recording');
      confirmBtn.textContent = t('popup.btn_upload_file');
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

      // 업로드 완료·유실 안내의 [확인] → 닫기 (유실은 다시 올려도 같은 결과라 재시도하지 않는다)
      if ((isSucceeded || isLost) && !isAppClosing) {
        window.windowAPI.closeWindow();
        return;
      }

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

    case 'logout': {
      confirmBtn.disabled = true;
      window.authAPI.logout().then((res) => {
        if (res && res.success) {
          window.windowAPI.closeWindow();
          return;
        }
        // 업로드 중이라 막힘 → 안내로 바꾸고 [확인] 은 닫기
        popupType = 'error-alert';
        popupTitle.textContent = t('popup.logout_blocked_title');
        popupSubtitle.textContent = t('popup.logout_blocked_subtitle');
        cancelBtn.classList.add('hidden');
        confirmBtn.disabled = false;
      }).catch(() => {
        window.windowAPI.closeWindow();
      });
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
  if (popupType !== 'upload-progress' || isFailed || isSucceeded) return; // 실패/완료 이후 업데이트 무시
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
  progressText.textContent = t('popup.upload_speed', { speed: speedText });
  popupSubtitle.textContent = t('popup.upload_eta', { eta: etaText });

});

// 업로드 실패 이벤트 수신: 팝업 UI를 실패 상태로 전환
window.electronAPI.onUploadFailed((payload) => {
  if (popupType !== 'upload-progress') return;
  isFailed = true;
  isWaitingForResponse = false;
  isAppClosing = payload?.isAppClosing ?? false;

  try { progressArea.classList.remove('indeterminate'); } catch (_) {}
  popupTitle.textContent = t('popup.upload_failed_title');
  // 실패 사유(payload.message)는 서버/네트워크 오류 원문이라 번역하지 않는다
  const reason = (payload && payload.message) ? String(payload.message) : t('popup.upload_failed_default_reason');

  // 유실: 앱에서 다시 올릴 수 없다 → 웹 미완성 회의록에서 재업로드 안내
  if (payload && payload.kind === 'lost') {
    isLost = true;
    popupSubtitle.innerHTML = `
      <span>${escapeHtml(t('popup.upload_failed'))}</span><br>
      <span>${escapeHtml(t('popup.upload_lost', { name: payload.uploadName || '' }))}</span>
    `;
    document.querySelector('.progress-bar').style.background = '#EF4444';
    document.querySelector('.progress-bar-percent').style.color = '#EF4444';
    cancelBtn.classList.add('hidden');
    confirmBtn.textContent = t('common.ok');
    confirmBtn.classList.remove('hidden');
    return;
  }

  if(isAppClosing) {
    popupSubtitle.innerHTML = `
      <span>${escapeHtml(t('popup.upload_failed'))}</span><br>
      <span>${escapeHtml(t('popup.upload_failed_quit', { reason }))}</span>
    `;
    confirmBtn.textContent = t('common.ok');
    confirmBtn.classList.remove('hidden');
  }else {
    popupSubtitle.innerHTML = `
      <span>${escapeHtml(t('popup.upload_failed'))}</span><br>
      <span>${escapeHtml(t('popup.upload_failed_retry', { reason }))}</span>
    `
    // 바/퍼센트 유지하되 색상/스타일을 경고로 전환하고 버튼 노출
    document.querySelector('.progress-bar').style.background = '#EF4444';
    document.querySelector('.progress-bar-percent').style.color = '#EF4444';
    
    // 버튼 노출
    confirmBtn.classList.remove('hidden');
    cancelBtn.classList.remove('hidden');
    confirmBtn.textContent = t('popup.btn_retry');
  }
});

// 업로드 성공 이벤트 수신: 팝업 UI를 "업로드 완료" 안내로 전환
window.electronAPI.onUploadSucceeded((payload) => {
  if (popupType !== 'upload-progress') return;
  isSucceeded = true;
  isWaitingForResponse = false;
  if (animRafId) { try { cancelAnimationFrame(animRafId); } catch (_) {} animRafId = null; }
  logAction('popup_shown', { popupType: 'upload-succeeded' });

  try { progressArea.classList.add('hidden'); } catch (_) {}
  popupTitle.textContent = t('popup.upload_done_title');
  const nextStep = payload && payload.goHome ? t('popup.upload_done_go_home') : t('popup.upload_done_continue');
  popupSubtitle.innerHTML = `<span>${escapeHtml(t('popup.upload_done'))}</span><br><span>${escapeHtml(nextStep)}</span>`;
  cancelBtn.classList.add('hidden');
  confirmBtn.textContent = t('common.ok');
  confirmBtn.classList.remove('hidden');
});
