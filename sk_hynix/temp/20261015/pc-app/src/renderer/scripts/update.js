// 자동 업데이트 화면(pages/update.html) 진행 상태 표시
// (CSP 때문에 인라인 <script> 대신 파일로 분리)
const heading = document.getElementById("updateHeading");
const desc = document.getElementById("updateDesc");
const fill = document.getElementById("updateBarFill");
const percentText = document.getElementById("updatePercent");

window.updateAPI.onStatus((status) => {
  if (!status) return;
  const version = status.version ? `v${status.version}` : "새 버전";
  if (status.stage === "downloading") {
    heading.textContent = `${version} 으로 업데이트 중입니다`;
    desc.textContent = "새 버전을 내려받는 중입니다.\n잠시만 기다려 주세요.";
    desc.classList.remove("error");
  } else if (status.stage === "installing") {
    heading.textContent = `${version} 설치 중입니다`;
    desc.textContent = "앱이 잠시 종료된 뒤 자동으로 다시 실행됩니다.\n관리자 권한 확인 창이 뜨면 '예'를 눌러 주세요.";
  } else if (status.stage === "failed") {
    heading.textContent = "업데이트에 실패했습니다";
    desc.textContent = "지금은 현재 버전으로 계속 사용합니다.\n다음에 앱을 실행할 때 다시 시도합니다.";
    desc.classList.add("error");
  }
  const percent = Math.max(0, Math.min(100, Number(status.percent) || 0));
  fill.style.width = `${percent}%`;
  percentText.textContent = `${percent}%`;
});
