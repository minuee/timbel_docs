# auth-api — `X-Device-Timezone` 헤더로 국가 판별 (서버 담당자용)

> 작성일: 2026-10-29
> 목적: 나라별로 확인해야 하는 동의서가 달라서, 서버가 요청을 보낸 기기의 국가를 알아야 한다.
> 방식: 앱과 웹이 기기 시간대를 `X-Device-Timezone` 헤더로 보내고, 서버가 시간대 이름을 국가 코드로 바꾼다.
> 파이썬과 노드 중 어느 쪽 서버든 쓸 수 있게 두 가지로 만들었다. 둘 다 **추가 패키지 없이** 기본 기능만 쓴다.

## 1. 폴더 구성

| 파일 | 내용 |
|---|---|
| `zone.tab` | 시간대 이름 → 국가 코드 공식 대응표 (시간대 데이터 2026e판, 418개) |
| `zone_country.py` | 파이썬용. `country_from_timezone(값)` |
| `zoneCountry.js` | 노드용. `countryFromTimezone(값)` |

세 파일을 서버 소스의 같은 폴더에 넣는다. `zone.tab`을 다른 곳에 두려면 환경 변수 `ZONE_TAB_PATH`로 경로를 지정한다.

## 2. 헤더 규격

| 항목 | 내용 |
|---|---|
| 헤더 이름 | `X-Device-Timezone` |
| 값 | 시간대 이름. 예: `Asia/Seoul`, `Asia/Tokyo`, `America/New_York` |
| 보내는 곳 | 앱과 웹의 모든 API 요청 (공통 헤더) |

### 앱·웹 담당자에게 전달할 내용 (이것만 요청하면 된다)

- **웹**: `Intl.DateTimeFormat().resolvedOptions().timeZone` 값을 `X-Device-Timezone` 헤더에 넣는다.
- **앱(Flutter)**: `flutter_timezone` 패키지의 `FlutterTimezone.getLocalTimezone()` 값을 Dio 공통 헤더(`_setHeaders()`)에 넣는다. 기본 기능인 `DateTime.now().timeZoneName`은 `KST` 같은 약어만 줘서 쓸 수 없다.

## 3. 결과 예시

미국은 도시별이 아니라 **시간대별 대표 도시 이름**으로 온다. 샌프란시스코에 있어도 `America/Los_Angeles`로 온다. 미국에만 이름이 29개 있으며, 대응표에서 모두 `US`로 묶인다.

| 헤더 값 | 결과 |
|---|---|
| `Asia/Seoul` | `KR` |
| `Asia/Tokyo` | `JP` |
| `America/New_York`, `America/Chicago`, `America/Phoenix`, `America/Los_Angeles`, `Pacific/Honolulu` | `US` |
| `America/Indiana/Indianapolis` | `US` |
| `Asia/Shanghai` | `CN` |
| `Asia/Hong_Kong` | `HK` (중국과 따로 나온다) |
| `US/Eastern`, `Asia/Calcutta`, `Europe/Kiev` (옛 이름) | `US`, `IN`, `UA` (보정표로 처리) |
| `UTC`, `Etc/GMT`, 헤더 없음, 형식이 이상한 값 | 없음 (`None` / `null`) |

위 표는 두 구현에 똑같이 넣어 돌려 보았고, 결과가 서로 같은 것을 확인했다.

## 4. 서버에 붙이는 방법

### 파이썬

```python
from zone_country import HEADER_NAME, country_from_timezone

# Flask
country = country_from_timezone(request.headers.get(HEADER_NAME))

# FastAPI
country = country_from_timezone(request.headers.get(HEADER_NAME))
```

### 노드 (Express)

```js
const { countryFromTimezone } = require('./zoneCountry');

app.use((req, res, next) => {
  req.deviceCountry = countryFromTimezone(req.get('X-Device-Timezone'));
  next();
});
```

노드 기본 `http` 모듈을 쓴다면 `req.headers['x-device-timezone']`으로 읽는다. 노드는 헤더 이름을 소문자로 바꿔서 준다.

## 5. 꼭 처리할 것

1. **국가를 알 수 없을 때의 기본값을 정한다.** 결과가 없을 때 어떤 동의서를 보여 줄지 정책을 하나 정해 둔다. 예를 들면 한국 동의서를 보여 주거나, 사용자에게 국가를 고르게 하는 방식이다.
2. **CORS 허용 헤더에 추가한다.** 웹이 다른 도메인에서 API를 부르면, 응답의 `Access-Control-Allow-Headers`에 `X-Device-Timezone`이 있어야 한다. 없으면 브라우저가 요청을 막는다.
3. **동의 기록에 근거를 남긴다.** 동의를 저장할 때 판별된 국가와 받은 헤더 값을 함께 저장한다.
4. **대응표를 가끔 갱신한다.** 시간대 이름은 1년에 몇 번 바뀔 수 있다. 서버를 다시 빌드할 때 최신 `zone.tab`으로 바꾸면 된다. 리눅스에는 `/usr/share/zoneinfo/zone.tab`에 있다.

## 6. 알아 둘 한계

- 기기 시간대는 사용자가 바꿀 수 있다. 출장을 가서 현지 시간으로 바뀌면 국가도 바뀐다.
- 서버는 헤더 값만 보고 판단하므로, 마음먹고 값을 바꿔 보내는 것까지는 막지 못한다.
