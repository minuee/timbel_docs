// 공통 navigation — 각 페이지의 body 첫 줄에 nav 삽입.
// 사용:  <script src="config.js"></script><script src="nav.js"></script>
(function () {
  const pages = [
    { href: "index.html", label: "Locus-KMS", brand: true },
    { href: "upload.html", label: "업로드" },
    { href: "library.html", label: "라이브러리" },
    { href: "search.html", label: "검색/RAG" },
    { href: "repository-groups.html", label: "저장소 그룹" },
    { href: "_swagger", label: "Swagger", external: true },
  ];

  function build() {
    const path = window.location.pathname.split("/").pop() || "index.html";
    const apiBase = window.LUCAS_API_BASE || "";
    const nav = document.createElement("nav");
    nav.style.cssText = "border-bottom:1px solid #e0e0e0;padding:10px 0;margin-bottom:24px;font-size:13px;display:flex;align-items:center;gap:6px;flex-wrap:wrap;";
    pages.forEach((p, i) => {
      const a = document.createElement("a");
      const href = p.href === "_swagger" ? (apiBase + "/docs") : p.href;
      a.href = href;
      a.textContent = p.label;
      a.style.cssText = "color:#4a90e2;text-decoration:none;padding:4px 10px;border-radius:4px;";
      if (p.external) a.target = "_blank";
      if (p.brand) a.style.cssText += "font-weight:700;color:#1a1a1a;font-size:15px;margin-right:8px;padding-left:0;";
      if (path === p.href) {
        a.style.background = "#e8f0ff";
        a.style.fontWeight = "600";
      }
      a.onmouseover = () => { if (path !== p.href && !p.brand) a.style.background = "#f0f4ff"; };
      a.onmouseout = () => { if (path !== p.href && !p.brand) a.style.background = ""; };
      nav.appendChild(a);
      if (i > 0 && i < pages.length - 1) {
        const sep = document.createElement("span");
        sep.textContent = "·";
        sep.style.cssText = "color:#ccc;";
        nav.appendChild(sep);
      }
    });
    // 우측 — tenant 표시
    const meta = document.createElement("span");
    meta.style.cssText = "margin-left:auto;color:#999;font-size:11px;font-family:ui-monospace,monospace;";
    meta.textContent = "tenant: " + (window.LUCAS_TENANT_ID || "").slice(0, 8);
    nav.appendChild(meta);
    return nav;
  }

  function inject() {
    const nav = build();
    const body = document.body;
    body.insertBefore(nav, body.firstChild);
    // 기존 "← 메인" back link 제거 (중복)
    document.querySelectorAll("a.back").forEach(a => a.remove());
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", inject);
  } else {
    inject();
  }
})();
