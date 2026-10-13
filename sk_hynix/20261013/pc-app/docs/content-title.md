# 회의록 파일 업로드 제목 추가 


**기존 모바일 암호화 업로드를 그대로** 사용하되 `title`를 추가

- 다파일: `POST /contents/upload/encryption/files`
- 단일(청크): `POST /contents/upload/encryption`

### multipart/form-data 필드

| 필드 | 필수 | 설명 |
|---|---|---|
| `files` (또는 `file`) | ✅ | 암호화된 청크 파일(기존과 동일) |
| `deviceId` | ✅ | 기기 식별자(기존과 동일) |
| `fileName` | ✅ | 폴더/파일명(기존과 동일) |
| `totalNum` | ✅ | 청크 총 개수(기존과 동일). 단일 청크 API는 `num`도 사용 |
| `attendeeNum`, `lang` | 선택 | 기존과 동일 |
| `templateId` | 선택 | 템플릿으로 채택. 미지정 시 병합 때 `DEF-BASIC` |
| `title` | 선택 | 회의록 제목 |

### 응답

기존과 동일