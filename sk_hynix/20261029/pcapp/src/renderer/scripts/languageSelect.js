// 화면 아래 언어 선택 상자 (로그인·마이크 테스트 화면). 녹음 화면은 설정 메뉴 "언어"를 쓴다.
// - MULTI_LANG_ENABLED 가 false 면 숨긴다(항상 한국어).
// - 고르면 메인이 저장하고 열린 창에 알린다. 이 화면 글자는 preload(data-i18n)와 각 화면의 i18n.onChange 가 다시 그린다.
// - 이 화면들에는 녹음이 없으므로 막는 조건이 없다.
(function setupLanguageSelect() {
  const wrap = document.getElementById("languageSelectWrap");
  const select = document.getElementById("languageSelect");
  if (!wrap || !select || !window.i18n) return;

  wrap.hidden = !window.i18n.enabled();
  if (wrap.hidden) return;

  window.i18n.languages().forEach((language) => {
    const option = document.createElement("option");
    option.value = language.code;
    option.textContent = language.name;
    select.appendChild(option);
  });
  select.value = window.i18n.lang();

  select.addEventListener("change", async () => {
    const lang = select.value;
    const from = window.i18n.lang();
    try { window.developerAPI.logAction("language_clicked", { lang, from, screen: wrap.dataset.screen || "", blocked: false }); } catch (_) {}
    if (lang === from) return;
    try {
      const res = await window.i18n.setLang(lang);
      if (!res || !res.success) select.value = window.i18n.lang();
    } catch (_) {
      select.value = window.i18n.lang();
    }
  });

  // 다른 창(녹음 화면 설정 메뉴 등)에서 바뀌어도 맞춘다
  window.i18n.onChange((lang) => { select.value = lang; });
})();
