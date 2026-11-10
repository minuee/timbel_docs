// 서버 API 목록. 주소·메서드·파라미터가 바뀌면 이 파일만 고친다.
// (설명서: docs/api-config.md)
//
// 항목별 키
//   method   : 'get' | 'post' | 'put' ...
//   url      : 경로. baseURL 이 없으면 로그인 세션의 서버 주소 뒤에 붙는다.
//   baseURL  : 세션 서버가 아닌 다른 서버로 보내야 할 때만 적는다.
//   auth     : true 면 Authorization: Bearer {accessToken} 을 붙인다.
//   params   : 쿼리스트링 (?a=b)
//   body     : 요청 본문(JSON)
//   pick     : 응답에서 꺼낼 값. { 저장할이름: '응답.안의.경로' }
//
// params / body / url 안의 {empno} {name} {email} 은 호출 시점의 사용자 정보로 바뀐다.
// 값이 비어 있으면 호출하지 않고 로그만 남긴다(빈 사번으로 메일이 나가는 일을 막기 위함).
//
// 기본값은 모바일앱 소스(docs/mobile-app)에서 가져온 것이다. ★ 는 회사에서 확인할 값.

const config = require('../config');

// 부서장 메일처럼 모바일 서버에만 있는 API 를 부를 때 쓰는 주소(.env / app.config.json 의 MOBILE_SERVER_URL).
const MOBILE_SERVER = config.get('MOBILE_SERVER_URL', 'https://aimeeting.mobile.skhynix.com/m');

module.exports = {
  // 1. 내 정보 — 로그인 직후 호출. 이름은 타이틀에 표시된다.
  // ★ 모바일은 GET. 서버가 POST 를 요구하면 method 만 바꾼다.
  userMe: {
    method: 'get',
    url: '/api/auth/user/me',
    auth: true,
    pick: {
      name: 'data.profile.name',
      nickName: 'data.profile.nickName',
      email: 'data.profile.email',
      empno: 'data.profile.company.empno',
      deptName: 'data.profile.company.deptName',
    },
  },

  // 2+3. 부서장 이메일 조회 + 녹음 시작 안내 메일 발송 — 녹음 시작 시 호출.
  // 서버가 사번으로 부서장 메일을 찾아 직접 보낸다(docs/hynix-mobile alert.service.js).
  // 모바일과 같이 사번을 쿼리스트링으로 보내고, 토큰은 붙이지 않는다.
  alertRecording: {
    method: 'post',
    baseURL: MOBILE_SERVER,
    url: '/api/alert/recording',
    auth: false,
    params: { empno: '{empno}' },
  },

  // 4. 워크스페이스 — 로그인 직후 호출. 지금은 세션에 보관하고 로그에만 남긴다.
  // ★ 모바일은 GET.
  workspace: {
    method: 'get',
    url: '/api/auth/workspace/me',
    auth: true,
    pick: {
      workspaceId: 'data.workspace.id',
      workspaceName: 'data.workspace.name',
      workspaceRole: 'data.role',
    },
  },

  // 5. 녹음 파일 업로드 — main.js serverUpload() 가 multipart 로 보낸다.
  // 본문 필드(files, lang, attendeeNum, deviceId, fileName, totalNum, title, templateId)는 main.js 에서 만든다.
  // (docs/content-title.md: title·templateId 는 선택. templateId 를 안 보내면 서버가 DEF-BASIC)
  // 여기서는 경로만 바꿀 수 있다.
  upload: {
    method: 'post',
    url: '/api/contents/upload/encryption/files',
    auth: true,
  },

  // 6. 요약 템플릿 목록 — 업로드 팝업("AI 요약 준비하기")의 템플릿 선택에 쓴다. services/templateService.js
  // 화면에는 name, 업로드 때 templateId 로 code 를 보낸다.
  // ★ 응답 모양은 회사에서 확인: list 는 응답 안의 배열 위치('data' → body.data, 비우면 body 자체가 배열),
  //   codeKey / nameKey 는 배열 항목의 필드 이름.
  templates: {
    method: 'get',
    baseURL: MOBILE_SERVER,
    url: '/api/template',
    auth: true,
    params: { type: 'normal' },
    list: 'data',
    codeKey: 'code',
    nameKey: 'name',
  },
};
