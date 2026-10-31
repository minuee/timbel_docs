// 회의록 웹 → PC 녹음앱 열기 + 설치 여부 판단 (예제)
//
// 사용:
//   const result = await openPcApp({ code, apiHost });
//   if (result === 'not-installed') showInstallGuide();   // [설치 파일 받기] [다시 열기]
//
// - code    : 1회용 연결 code. 지금 "앱 연결"에 쓰는 발급 방식 그대로.
// - apiHost : 앱이 code 를 교환할 API 서버 주소(예: https://aimeeting.example.com). 앱에는 base64 로 넘긴다.
// - 반환    : 'opened'        브라우저가 앱 열기 반응을 보임(설치된 것으로 판단)
//             'not-installed' 정해진 시간 안에 반응 없음(설치 안 된 것으로 판단)
//
// 브라우저는 PC 에 설치된 프로그램을 직접 조회할 수 없다.
// 앱 주소를 열었을 때 페이지가 포커스를 잃는지(앱 열기 확인창이 뜨거나 앱이 앞으로 나옴)로 판단한다.
// 100% 정확하지 않으므로 'not-installed' 안내창에는 [다시 열기] 버튼을 꼭 둔다.

const PC_APP_SCHEME = 'timbloRecApp';

function toBase64Utf8(text) {
  return btoa(unescape(encodeURIComponent(text)));
}

function buildPcAppUrl(code, apiHost) {
  return `${PC_APP_SCHEME}://connect?code=${encodeURIComponent(code)}&host=${encodeURIComponent(toBase64Utf8(apiHost))}`;
}

function openPcApp({ code, apiHost, timeoutMs = 2000 }) {
  return new Promise((resolve) => {
    let done = false;

    const finish = (result) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      window.removeEventListener('blur', onLeave);
      document.removeEventListener('visibilitychange', onVisibility);
      resolve(result);
    };
    const onLeave = () => finish('opened');
    const onVisibility = () => { if (document.hidden) finish('opened'); };

    window.addEventListener('blur', onLeave);
    document.addEventListener('visibilitychange', onVisibility);
    const timer = setTimeout(() => finish('not-installed'), timeoutMs);

    // 페이지 이동이 아니라 앱 호출이라 현재 화면은 그대로 남는다.
    window.location.href = buildPcAppUrl(code, apiHost);
  });
}
