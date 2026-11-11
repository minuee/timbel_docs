// 빌드가 끝나면 Windows 설치 파일을 고정 이름으로 하나 더 복사한다.
//   dist/SKHynixRecApp-Setup-0.0.8.exe  →  dist/SKHynixRecApp-Setup-latest.exe
// (설치 파일 이름은 package.json build.nsis.artifactName)
// 버전이 들어간 원본은 자동 업데이트(latest.yml)가 쓰고,
// 고정 이름 복사본은 회의록 웹의 [설치 파일 받기] 링크가 쓴다(배포마다 링크를 바꾸지 않기 위함).
// 업데이트 서버에 올릴 때 둘 다 올린다. 문서: docs/auto-update.md, docs/web-integration/README.md
const fs = require('fs');
const path = require('path');

const LATEST_NAME = 'SKHynixRecApp-Setup-latest.exe';

module.exports = async function afterAllArtifactBuild(buildResult) {
  const setup = (buildResult.artifactPaths || []).find(
    (p) => /\.exe$/i.test(p) && path.basename(p) !== LATEST_NAME
  );
  if (!setup) return [];

  const target = path.join(path.dirname(setup), LATEST_NAME);
  fs.copyFileSync(setup, target);
  console.log(`[afterAllArtifactBuild] ${path.basename(setup)} → ${LATEST_NAME}`);
  // 빈 배열: 복사본을 electron-builder 의 배포 대상(latest.yml 등)에 넣지 않는다.
  return [];
};
