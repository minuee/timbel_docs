; electron-builder NSIS 사용자 스크립트 (build.directories.buildResources 의 installer.nsh 를 자동으로 읽는다)
;
; 설치 화면에 보이는 이름만 고객사 이름으로 바꾼다.
; - PRODUCT_NAME 은 package.json productName(timbloRecApp)으로 넘어온다.
;   설치 프로그램에서는 창 제목·안내 문구(Name, BrandingText, "실행 중" 안내)에만 쓰인다.
; - 설치 폴더(APP_FILENAME)·레지스트리 키(APP_GUID)·앱 데이터 폴더는 그대로 timbloRecApp 이다(내부 이름).
; - 바로가기·프로그램 제거 목록 이름은 package.json nsis.shortcutName / uninstallDisplayName.
!ifdef PRODUCT_NAME
  !undef PRODUCT_NAME
!endif
!define PRODUCT_NAME "SKHynixRecApp"
