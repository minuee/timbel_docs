// AI 요약 준비하기 (업로드 팝업)
// - 제목(선택), 요약 언어, 발화자수, 템플릿을 골라 업로드를 요청한다.
// - 템플릿 목록: 저장해 둔 목록을 먼저 보여주고, 서버에서 다시 받으면 바꿔 그린다(templateAPI).
//   화면에는 name, 업로드 때 templateId 로 code 를 보낸다. code 가 빈 "기본형"은 templateId 를 보내지 않는다.

const closeBtn = document.getElementById('closeBtn');
const uploadBtn = document.getElementById('uploadBtn');
const titleInput = document.getElementById('titleInput');
const templateList = document.getElementById('templateList');

let isError;
let isLimitDurationStopped;
window.electronAPI.onApplySummarizeWindow((options) => {
  isError = options.isError;
  isLimitDurationStopped = options.isLimitDurationStopped;
});

// 사용자 동작 로그 (로그 서버 category:"user_action")
function logAction(action, context) {
  try { window.developerAPI.logAction(action, context); } catch (_) {}
}

function selectedTemplateCode() {
  const checked = templateList.querySelector('input[name="template"]:checked');
  return checked ? checked.value : null;
}

// 고르던 템플릿은 다시 그려도 유지한다. 없으면 첫 번째.
function renderTemplates(templates) {
  if (!Array.isArray(templates) || templates.length === 0) return;
  const previous = selectedTemplateCode();
  templateList.innerHTML = '';
  templates.forEach((template, index) => {
    const row = document.createElement('div');
    const input = document.createElement('input');
    input.type = 'radio';
    input.name = 'template';
    input.id = `template${index}`;
    input.value = template.code;
    const label = document.createElement('label');
    label.htmlFor = input.id;
    label.textContent = template.name;
    row.append(input, label);
    templateList.appendChild(row);
  });
  const keep = templateList.querySelector(`input[name="template"][value="${CSS.escape(previous || '')}"]`);
  (previous !== null && keep ? keep : templateList.querySelector('input[name="template"]')).checked = true;
}

async function loadTemplates() {
  try { renderTemplates(await window.templateAPI.getCached()); } catch (_) {}
  try { renderTemplates(await window.templateAPI.refresh()); } catch (_) {}
}
loadTemplates();
titleInput.focus();

closeBtn.addEventListener('click', () => {
  logAction('upload_option_closed');
  window.windowAPI.closeWindow();
});

uploadBtn.addEventListener('click', () => {
  const langInput = document.querySelector('input[name="language"]:checked');
  const speakerInput = document.querySelector('input[name="speaker"]:checked');
  if (!langInput || !speakerInput) {
    alert('언어와 발화자수를 선택해주세요');
    return;
  }

  if (!isError && !isLimitDurationStopped) {
    window.electronAPI.sendHelperCommand({
      cmd: "stop",
    });
  }

  const lang = langInput.value;
  const attendeeNum = speakerInput.value;
  const title = titleInput.value.trim();
  const templateId = selectedTemplateCode() || '';
  logAction('upload_requested', { lang, attendeeNum, templateId, hasTitle: !!title, afterError: !!isError, byMaxDuration: !!isLimitDurationStopped });

  window.electronAPI.requestUpload({
    lang,
    attendeeNum,
    title,
    templateId,
  });
  window.windowAPI.closeWindow();
});
