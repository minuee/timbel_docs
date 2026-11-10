const uploadListBody = document.querySelector('.upload-list-body');
const uploadListItem = document.querySelector('.upload-list-item');
const closeButton = document.getElementById('closeButton');

let jobs = [];

// 화면 문구 (src/locales/*.json)
const t = (key, params) => window.i18n.t(key, params);

// 회의명(file_name)은 사용자가 입력한 값이라 HTML 로 해석되지 않게 바꿔 넣는다
function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// 언어가 바뀌면 목록을 다시 그린다(제목·머리글은 preload 가 바꿈)
window.i18n.onChange(() => renderJobs());

window.electronAPI.onUploadListOpen((data) => {
  console.log('onUploadListOpen : ', data);
  jobs = data;
  renderJobs();
});

window.dbAPI.onJobsUpdated((data) => {
  console.log('onJobsUpdated : ', data);
  jobs = data;
  renderJobs();
})


function renderJobs() {
  uploadListBody.innerHTML = '';
  if(jobs.length < 1) {
    const item = document.createElement('div');
    item.innerHTML = `
      <div class="item-title">${escapeHtml(t('upload_list.empty'))}</div>
    `;
    uploadListBody.appendChild(item);
    return;
  }

  jobs.forEach((job) => {
    const item = document.createElement('div');
    item.classList.add('upload-list-item');
    item.dataset.id = job.job_id;
    item.innerHTML = `
      <div class="item-status-icon">${job.is_uploading ? 
        `<span class="spinner" aria-label="${escapeHtml(t('upload_list.loading'))}" role="status"></span>` : 
        '<img src="../assets/icons/upload_fail_icon.svg" alt="">'}
      </div>
      <div class="item-title">${escapeHtml(job.file_name)}</div>
      <div class="item-time">${job.recording_created_at.slice(0, 16)}</div>
      <div class="item-status">${job.is_uploading ? `<span class="uploading">${escapeHtml(t('upload_list.uploading'))}<span class="ellipsis" aria-hidden="true"></span></span>` : 
        `<button class="retry-btn" data-action="retry">${escapeHtml(t('upload_list.retry'))}</button>`}
      </div>
      <div class="item-delete">
          <button class="item-delete" data-action="delete" aria-label="${escapeHtml(t('common.delete'))}">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>
              <path d="M10 11v6"></path>
              <path d="M14 11v6"></path>
              <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path>
            </svg>
          </button>
      </div>
    `;
    
    uploadListBody.appendChild(item);
  });
}

// 닫기 버튼 클릭
// (클릭이 들어왔는지 로그 서버에서 보려고 로그를 남긴다 — upload_list_close_clicked)
closeButton.addEventListener('click', () => {
  try { window.developerAPI.logAction('upload_list_close_clicked', {}); } catch (_) {}
  window.windowAPI.closeWindow();
});

// 업로드 리스트 아이템 버튼 클릭
uploadListBody.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-action]');
  if (!btn || !uploadListBody.contains(btn)) return;

  // 눌린 버튼이 속한 아이템 찾기
  const itemEl = btn.closest('.upload-list-item');
  const jobId = itemEl?.dataset.id;
  if (!jobId) return;

  const action = btn.dataset.action; // 'retry' | 'delete'
  const job = jobs.find(j => String(j.job_id) === jobId);
  // 사용자 동작 로그 (로그 서버 category:"user_action"). 확인/취소 선택은 팝업에서 남긴다.
  try { window.developerAPI.logAction('upload_list_item_clicked', { itemAction: action, jobId }); } catch (_) {}

  if (action === 'retry') {
    console.log('재시도 클릭', { jobId, job });
    // 다건 재시도 기획: 확인 팝업 후 백그라운드 업로드
    window.electronAPI.openPopupWindow({
      width: 360,
      height: 200,
      type: 'confirm-retry-multi',
      title: t('upload_list.retry_title'),
      subtitle: t('upload_list.retry_subtitle'),
      data: [job],
    });

  } else if (action === 'delete') {
    console.log('삭제 클릭', { jobId, job });
    // 기존 즉시 삭제에서 팝업 확인 흐름으로 변경
    window.electronAPI.openPopupWindow({
      width: 360,
      height: 200,
      type: 'remove-job',
      title: t('upload_list.delete_title'),
      subtitle: t('upload_list.delete_subtitle'),
      job,
    });
  }
});