// 자동 업데이트 화면(pages/update.html) 진행 상태 표시
// (CSP 때문에 인라인 <script> 대신 파일로 분리)
const heading = document.getElementById("updateHeading");
const desc = document.getElementById("updateDesc");
const fill = document.getElementById("updateBarFill");
const percentText = document.getElementById("updatePercent");
const t = (key, params) => window.i18n.t(key, params);

// 첫 화면 문구(상태가 오기 전)
heading.textContent = t("update.preparing");
desc.textContent = t("update.downloading_desc");

window.updateAPI.onStatus((status) => {
  if (!status) return;
  const version = status.version ? `v${status.version}` : t("update.new_version");
  if (status.stage === "downloading") {
    heading.textContent = t("update.downloading", { version });
    desc.textContent = t("update.downloading_desc");
    desc.classList.remove("error");
  } else if (status.stage === "installing") {
    heading.textContent = t("update.installing", { version });
    desc.textContent = t("update.installing_desc");
  } else if (status.stage === "failed") {
    heading.textContent = t("update.failed");
    desc.textContent = t("update.failed_desc");
    desc.classList.add("error");
  }
  const percent = Math.max(0, Math.min(100, Number(status.percent) || 0));
  fill.style.width = `${percent}%`;
  percentText.textContent = `${percent}%`;
});
