# aicm-service — MinIO 파일 스토리지

> 버킷 구조, 업로드 흐름, Lifecycle Rule, DB 저장값 vs API 응답값 분리

---

## 1. 버킷 구조

```
aicm/                                    ← 단일 버킷
├── temp/                                # 에디터 인라인 업로드 (Lifecycle Rule: 24시간 TTL)
│   └── {session_id}/
│       ├── {uuid}.original.{ext}
│       └── {uuid}.thumb.{ext}
│
├── originals/                           # 대용량 문서 원본 (Lifecycle Rule: 7일 TTL)
│   └── {document_id}/
│       └── {upload_id}.{ext}            # 업로드된 PDF, DOCX 등
│
├── documents/                           # 확정 파일 (영구 보관)
│   └── {document_id}/
│       ├── images/                      # 이미지 블록의 원본 + 썸네일
│       │   ├── {block_id}.original.{ext}
│       │   └── {block_id}.thumb.{ext}
│       ├── files/                       # 파일 블록의 원본 + 썸네일
│       │   ├── {block_id}.original.{ext}
│       │   └── {block_id}.thumb.{ext}
│       └── attachments/                 # 문서 단위 첨부파일 (DocumentAttachment)
│           └── {attachment_id}.{ext}
│
├── exports/                             # 내보내기 임시 파일
└── templates/                           # 템플릿 첨부 리소스
```

---

## 2. 파일 업로드 흐름 (임시 → 확정)

```mermaid
flowchart TD
    A["사용자가 에디터에서<br/>이미지/파일 삽입"] --> B["프론트 → POST /api/files/upload<br/>바이너리 전송"]
    B --> C["백엔드 → MinIO temp/{sessionId}/ 에 저장<br/>+ 썸네일 생성"]
    C --> D["오브젝트 키 반환<br/>temp/{sessionId}/{uuid}.original.png"]
    D --> E["프론트 → 에디터에 블록 삽입<br/>(오브젝트 키를 content_raw.attrs.src에 세팅)"]
    E --> F["자동 저장 (debounce)<br/>PATCH /api/blocks/:id"]
    F --> G["백엔드 → temp → documents 경로로 이동<br/>content_raw.attrs.src 업데이트"]
    G --> H["블록 DB 저장 완료<br/>(확정 오브젝트 키 저장)"]

    C -.->|"24시간 후<br/>Lifecycle Rule"| X["자동 삭제<br/>(미확정 고아 파일 정리)"]
```

---

## 3. DB 저장값과 API 응답값 분리

| 구분 | 값 | 예시 |
|------|-----|------|
| **DB 저장** (content_raw.attrs.src) | 오브젝트 키 (영구, 만료 없음) | `documents/abc/images/block1.original.png` |
| **API 응답** (프론트에 전달) | Presigned URL (TTL 부여) | `https://minio.../aicm/documents/abc/images/block1.original.png?X-Amz-Expires=3600&X-Amz-Signature=...` |

> **Presigned URL은 DB에 저장하지 않는다.** 만료되면 깨지기 때문이다. DB에는 오브젝트 키만 저장하고, API 응답 시 백엔드가 presigned URL을 생성하여 프론트에 전달한다. 프론트는 presigned URL로 MinIO에 직접 접근하므로 파일 트래픽이 백엔드를 경유하지 않는다.

---

## 4. 대용량 문서 업로드 흐름 (파싱 후 원본 삭제)

```mermaid
flowchart TD
    A["사용자가 PDF/DOCX 업로드"] --> B["백엔드 → MinIO originals/{docId}/ 에 저장"]
    B --> C["parser-service에 파싱 요청<br/>(originals 오브젝트 키 전달)"]
    C --> D["parser-service가 원본 파싱<br/>→ ParsedBlock 반환<br/>→ aicm이 Block 엔티티 생성<br/>→ 추출 이미지는 documents/ 에 저장"]
    D --> E{"파싱 + 임베딩 완료?"}
    E -->|"성공"| F["originals/{docId}/ 즉시 삭제"]
    E -->|"실패"| G["원본 유지 (7일 내 재시도 가능)"]
    G -.->|"7일 후<br/>Lifecycle Rule"| H["자동 삭제 (최종 안전망)"]
```

> **원본 파일은 영구 보관하지 않는다.** 파싱이 완료되면 모든 콘텐츠는 Block 엔티티(content_raw, content_text)와 추출 파일(documents/)에 존재한다. 원본 PDF/DOCX는 파싱 + 임베딩 완료 시점에 즉시 삭제하며, 실패 시에도 Lifecycle Rule(7일)이 최종 안전망으로 동작한다.

---

## 5. Lifecycle Rule 설정

```json
{
  "Rules": [
    {
      "ID": "cleanup-temp-uploads",
      "Filter": { "Prefix": "temp/" },
      "Status": "Enabled",
      "Expiration": { "Days": 1 }
    },
    {
      "ID": "cleanup-originals",
      "Filter": { "Prefix": "originals/" },
      "Status": "Enabled",
      "Expiration": { "Days": 7 }
    }
  ]
}
```

| prefix | 용도 | TTL | 삭제 시점 |
|--------|------|-----|----------|
| `temp/` | 에디터 인라인 업로드 (이미지/파일) | 24시간 | 블록 저장 시 `documents/`로 이동, 미이동 시 자동 삭제 |
| `originals/` | 대용량 문서 원본 (PDF/DOCX) | 7일 | 파싱+임베딩 완료 시 즉시 삭제, 미삭제 시 자동 삭제 |
| `documents/` | 확정 파일 (블록 이미지/파일/첨부) | 영구 | Lifecycle Rule 없음 |

---

**관련 문서**
- [전체 개요](../README.md)
- [RDB 엔티티](./rdb.md) — DocumentAttachment, Block.content_raw
- [parser/README.md](../parser/README.md) — parser-service의 MinIO 접근 패턴
