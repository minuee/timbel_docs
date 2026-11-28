# vendor — npm 설치 없이 쓰는 외부 라이브러리

회사 PC 는 망분리라 `npm install` 을 할 수 없다. 새로 필요한 라이브러리는
의존성까지 **JS 파일 하나로 묶어서** 소스에 넣는다. git 으로 함께 옮겨지고,
`package.json` 의존성에는 넣지 않는다(넣으면 회사에서 빌드할 때 node_modules 에 없어서 실패).

| 파일 | 원본 | 버전 | 쓰는 곳 |
|---|---|---|---|
| `electron-updater.js` | npm `electron-updater` + 의존성 8개 | 6.3.9 | `services/updateService.js` |

번들 안에 남은 `require` 는 node 기본 모듈과 `electron` 뿐이다. 라이선스 문구는 파일 끝에 있다.

## 다시 만들기 (인터넷 되는 PC 에서)

```bash
npm install --no-save electron-updater@6.3.9
npx -y esbuild@0.23.1 node_modules/electron-updater/out/main.js \
  --bundle --platform=node --format=cjs --target=node20 \
  --external:electron --legal-comments=eof \
  --outfile=src/main/vendor/electron-updater.js
```
버전을 바꿨으면 위 표도 고친다.
