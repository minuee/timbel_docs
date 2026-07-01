// Locus-KMS frontend 설정.
// API base URL — staging 5201 default. window.LUCAS_API_BASE 로 override 가능.
(function () {
  const params = new URLSearchParams(window.location.search);

  // 1. URL ?api= 파라미터 우선 (즉석 변경)
  const apiParam = params.get("api");
  // 2. localStorage 영속
  const apiStored = localStorage.getItem("LUCAS_API_BASE");
  // 3. 기본 — same-origin. nginx 컨테이너가 /api 를 백엔드로 프록시하므로 host:port 그대로.
  //    (정적 서버로 단독 서빙 시엔 ?api=http://host:5101 로 override)
  const apiDefault = `${window.location.protocol}//${window.location.host}`;

  window.LUCAS_API_BASE = apiParam || apiStored || apiDefault;
  if (apiParam) localStorage.setItem("LUCAS_API_BASE", apiParam);

  // ?tenant_id= URL 파라미터로 즉석 변경 가능. localStorage 에 영속.
  // 기본값: 00000000-0000-0000-0000-000000000001 (서버 alembic 082 자동 시드 테넌트).
  // 로컬 테스트 시 ?tenant_id=00000000-0000-0000-0000-000000000000 으로 override.
  const tenantParam = params.get("tenant_id");
  const tenantStored = localStorage.getItem("LUCAS_TENANT_ID");
  window.LUCAS_TENANT_ID = tenantParam || tenantStored || "00000000-0000-0000-0000-000000000001";
  if (tenantParam) localStorage.setItem("LUCAS_TENANT_ID", tenantParam);
})();
