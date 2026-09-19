"""OpenAPI 3.0 document for the /v1/merge endpoints, plus the Swagger UI page.

Built as a plain dict rather than through a framework: recog has no pip
dependencies and the air-gapped deployment cannot reach a CDN, so the UI assets
are vendored under ``static/`` and served from this process.
"""

from __future__ import annotations

import json
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"

#: Assets vendored from swagger-ui-dist. Kept to the two files the page needs.
SWAGGER_ASSETS = {
    "swagger-ui.css": "text/css; charset=utf-8",
    "swagger-ui-bundle.js": "application/javascript; charset=utf-8",
}

_ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "example": "E4001"},
                "message": {"type": "string"},
                "participantId": {"type": "string"},
            },
        }
    },
}

_MERGE_FILE = {
    "type": "object",
    "required": ["participantId", "getUrl"],
    "properties": {
        "participantId": {
            "type": "string",
            "description": "참가자 식별자. 중복 불가.",
            "example": "p1",
        },
        "getUrl": {
            "type": "string",
            "description": "다운로드용 presigned GET URL.",
            "example": "http://timblo-minio:9000/default.timblo.io/kms/key?X-Amz-Algorithm=...",
        },
        "startedAt": {
            "type": "string",
            "format": "date-time",
            "description": (
                "녹음 시작 시각(ISO8601, 밀리초). align=timestamp 일 때 필수. "
                "초 단위로 주면 실제 오차(수백 ms)보다 거칠어 오히려 나빠질 수 있다."
            ),
            "example": "2026-09-19T14:30:52.104Z",
        },
        "fileName": {
            "type": "string",
            "description": "원본 파일명. 로그 가독성 용도.",
            "example": "A.Biz_m_rec_20260919_143052.flac",
        },
    },
}

_ALIGNMENT = {
    "type": "object",
    "properties": {
        "mode": {"type": "string", "enum": ["none", "timestamp"]},
        "reference": {"type": "string", "description": "가장 이른 트랙의 participantId."},
        "tracks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "participantId": {"type": "string"},
                    "offsetMs": {"type": "integer"},
                    "fallback": {
                        "type": "boolean",
                        "description": "offset이 이상값 가드를 넘겨 0으로 되돌려진 트랙.",
                    },
                },
            },
        },
    },
}

_JOB_STATUS = {
    "type": "object",
    "properties": {
        "jobId": {"type": "string", "example": "mrg_e2b7d3a662394c418669"},
        "roomNo": {"type": "string"},
        "status": {"type": "string", "enum": ["WAITING", "RUNNING", "DONE", "ERROR"]},
        "stage": {
            "type": "string",
            "nullable": True,
            "enum": ["DOWNLOADING", "NORMALIZING", "MIXING", "UPLOADING", None],
        },
        "progress": {"type": "integer", "minimum": 0, "maximum": 100},
        "retryAfterMs": {
            "type": "integer",
            "description": "다음 폴링까지 권장 대기 시간. 완료·실패 시에는 빠진다.",
        },
        "acceptedAt": {"type": "string", "format": "date-time"},
        "startedAt": {"type": "string", "format": "date-time", "nullable": True},
        "finishedAt": {"type": "string", "format": "date-time", "nullable": True},
        "output": {
            "type": "object",
            "properties": {
                "format": {"type": "string"},
                "sampleRate": {"type": "integer", "example": 16000},
                "channels": {"type": "integer", "example": 1},
                "durationMs": {"type": "integer"},
                "sizeBytes": {"type": "integer"},
                "originalname": {"type": "string"},
            },
        },
        "alignment": _ALIGNMENT,
        "timing": {
            "type": "object",
            "properties": {
                "downloadMs": {"type": "integer"},
                "processMs": {"type": "integer"},
                "uploadMs": {"type": "integer"},
                "totalMs": {"type": "integer"},
            },
        },
        "error": _ERROR_SCHEMA["properties"]["error"],
    },
}


def build_document(*, server_url: str = "/") -> dict:
    """Assemble the OpenAPI document. ``server_url`` lets the UI target this host."""
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "recog — 음성 병합 API",
            "version": "1.0.0",
            "description": (
                "참가자별 녹음 파일을 하나로 **겹쳐서** 합치는 API.\n\n"
                "5명이 1시간 회의했으면 결과물도 1시간이다(이어붙이기가 아니다).\n\n"
                "병합 엔드포인트는 인증이 없다 — 같은 도커 네트워크 내부 통신을 전제로 한다.\n"
                "이 문서 화면(`/docs`, `/openapi.json`)만 Basic 인증으로 보호된다.\n\n"
                "### 두 가지 입력 경로\n"
                "- `POST /v1/merge` — master-api 연동용. presigned URL로 주고받는다.\n"
                "- `POST /v1/merge/upload` — **테스트용**. 파일을 직접 올린다(Postman 등). "
                "스토리지 없이 병합 동작을 확인할 수 있고, 결과는 "
                "`GET /v1/merge/{jobId}/download` 로 내려받는다.\n\n"
                "자세한 배경은 `newDocs/MERGE_API_SPEC.md` 참조."
            ),
        },
        "servers": [{"url": server_url}],
        "tags": [
            {"name": "merge", "description": "음성 병합 (master-api 연동)"},
            {"name": "merge-test", "description": "파일 직접 업로드 테스트"},
            {"name": "ops", "description": "헬스체크·메트릭"},
        ],
        "paths": {
            "/v1/merge": {
                "post": {
                    "tags": ["merge"],
                    "summary": "병합 작업 접수",
                    "description": (
                        "즉시 202로 반환하고 백그라운드에서 처리한다.\n\n"
                        "`output.originalname`은 **퍼센트 인코딩된 ASCII**여야 하며, "
                        "master-api가 `putUrl` 서명에 넣은 값과 완전히 같아야 한다."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["roomNo", "files", "output"],
                                    "properties": {
                                        "roomNo": {"type": "string", "example": "R-20260919-001"},
                                        "files": {
                                            "type": "array",
                                            "minItems": 1,
                                            "maxItems": 5,
                                            "items": _MERGE_FILE,
                                        },
                                        "output": {
                                            "type": "object",
                                            "required": ["putUrl", "originalname"],
                                            "properties": {
                                                "putUrl": {"type": "string"},
                                                "originalname": {
                                                    "type": "string",
                                                    "description": "퍼센트 인코딩된 ASCII (encodeURIComponent).",
                                                    "example": "%ED%9A%8C%EC%9D%98%EB%A1%9D_merged.flac",
                                                },
                                                "format": {
                                                    "type": "string",
                                                    "enum": ["flac", "wav"],
                                                    "default": "flac",
                                                },
                                            },
                                        },
                                        "options": {
                                            "type": "object",
                                            "properties": {
                                                "align": {
                                                    "type": "string",
                                                    "enum": ["none", "timestamp"],
                                                    "default": "none",
                                                }
                                            },
                                        },
                                    },
                                },
                                "example": {
                                    "roomNo": "R-20260919-001",
                                    "files": [
                                        {
                                            "participantId": "p1",
                                            "startedAt": "2026-09-19T14:30:52.104Z",
                                            "getUrl": "http://timblo-minio:9000/default.timblo.io/k/p1?X-Amz-Algorithm=...",
                                        },
                                        {
                                            "participantId": "p2",
                                            "startedAt": "2026-09-19T14:30:52.371Z",
                                            "getUrl": "http://timblo-minio:9000/default.timblo.io/k/p2?X-Amz-Algorithm=...",
                                        },
                                    ],
                                    "output": {
                                        "putUrl": "http://timblo-minio:9000/default.timblo.io/k/merged?X-Amz-Algorithm=...",
                                        "originalname": "R-20260919-001_merged.flac",
                                        "format": "flac",
                                    },
                                    "options": {"align": "none"},
                                },
                            }
                        },
                    },
                    "responses": {
                        "202": {
                            "description": "접수됨. 큐에서 대기한다.",
                            "content": {
                                "application/json": {
                                    "example": {
                                        "jobId": "mrg_e2b7d3a662394c418669",
                                        "roomNo": "R-20260919-001",
                                        "status": "WAITING",
                                        "fileCount": 2,
                                        "acceptedAt": "2026-09-19T14:35:00.000Z",
                                        "retryAfterMs": 10000,
                                    }
                                }
                            },
                        },
                        "400": {
                            "description": "검증 실패 (E4001~E4007)",
                            "content": {"application/json": {"schema": _ERROR_SCHEMA}},
                        },
                        "409": {
                            "description": "같은 roomNo 작업이 진행 중 (E4090)",
                            "content": {"application/json": {"schema": _ERROR_SCHEMA}},
                        },
                    },
                }
            },
            "/v1/merge/upload": {
                "post": {
                    "tags": ["merge-test"],
                    "summary": "파일을 직접 올려서 병합 (테스트용)",
                    "description": (
                        "스토리지 없이 병합을 확인하기 위한 경로.\n\n"
                        "`files` 필드에 오디오 파일을 **2개 이상** 첨부한다. "
                        "`POST /v1/merge`와 동일한 큐·워커·믹싱 코드를 타므로 "
                        "실제 동작을 그대로 검증할 수 있다.\n\n"
                        "결과는 업로드하지 않고 서버에 보관하며 "
                        "`GET /v1/merge/{jobId}/download`로 받는다."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "required": ["files"],
                                    "properties": {
                                        "files": {
                                            "type": "array",
                                            "items": {"type": "string", "format": "binary"},
                                            "description": "병합할 오디오 파일 (1~5개)",
                                        },
                                        "align": {
                                            "type": "string",
                                            "enum": ["none", "timestamp"],
                                            "default": "none",
                                        },
                                        "startedAt": {
                                            "type": "string",
                                            "description": (
                                                "align=timestamp일 때, 파일 순서대로 콤마로 구분한 "
                                                "ISO8601 목록. "
                                                "예: 2026-09-19T14:30:52.000Z,2026-09-19T14:30:52.267Z"
                                            ),
                                        },
                                        "format": {
                                            "type": "string",
                                            "enum": ["flac", "wav"],
                                            "default": "flac",
                                        },
                                        "roomNo": {"type": "string"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "202": {"description": "접수됨. jobId로 폴링한다."},
                        "400": {
                            "description": "검증 실패",
                            "content": {"application/json": {"schema": _ERROR_SCHEMA}},
                        },
                    },
                }
            },
            "/v1/merge/{jobId}/retry": {
                "post": {
                    "tags": ["merge"],
                    "summary": "재작업 — 저장된 요청으로 다시 실행",
                    "description": (
                        "끝난 작업(DONE·ERROR)을 저장된 요청 그대로 다시 실행한다.\n\n"
                        "**새 jobId가 발급되고** 원래 작업은 `retriedFrom`으로 연결된다. "
                        "두 시도가 모두 이력에 남는다.\n\n"
                        "본문은 생략 가능하다. presigned URL이 만료돼서 실패한 경우가 "
                        "대부분이므로, 새 URL만 실어 보내면 나머지(참가자·정렬 모드·"
                        "파일명)는 원래 요청을 그대로 재사용한다.\n\n"
                        "진행 중인 작업은 `E4091`, 업로드 테스트 경로 작업은 `E4092`로 거부한다."
                    ),
                    "parameters": [
                        {
                            "name": "jobId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "files": {
                                            "type": "array",
                                            "description": "갱신할 presigned GET URL. 지정한 participantId만 바뀐다.",
                                            "items": {
                                                "type": "object",
                                                "required": ["participantId", "getUrl"],
                                                "properties": {
                                                    "participantId": {"type": "string"},
                                                    "getUrl": {"type": "string"},
                                                },
                                            },
                                        },
                                        "output": {
                                            "type": "object",
                                            "properties": {"putUrl": {"type": "string"}},
                                        },
                                    },
                                },
                                "example": {
                                    "files": [
                                        {"participantId": "p1", "getUrl": "http://timblo-minio:9000/...새URL"},
                                        {"participantId": "p2", "getUrl": "http://timblo-minio:9000/...새URL"},
                                    ],
                                    "output": {"putUrl": "http://timblo-minio:9000/...새URL"},
                                },
                            }
                        },
                    },
                    "responses": {
                        "202": {
                            "description": "재작업 접수됨",
                            "content": {
                                "application/json": {
                                    "example": {
                                        "jobId": "mrg_6c3e8a67eb2e4489a832",
                                        "retriedFrom": "mrg_cb39cf8ababe4c588a8e",
                                        "roomNo": "R-20260919-001",
                                        "status": "WAITING",
                                        "retryAfterMs": 10000,
                                    }
                                }
                            },
                        },
                        "400": {
                            "description": "override 형식 오류 (E4001)",
                            "content": {"application/json": {"schema": _ERROR_SCHEMA}},
                        },
                        "404": {
                            "description": "jobId 없음 (E4040)",
                            "content": {"application/json": {"schema": _ERROR_SCHEMA}},
                        },
                        "409": {
                            "description": "진행 중(E4091) / 업로드 경로(E4092) / roomNo 중복(E4090)",
                            "content": {"application/json": {"schema": _ERROR_SCHEMA}},
                        },
                    },
                }
            },
            "/v1/merge/{jobId}": {
                "get": {
                    "tags": ["merge"],
                    "summary": "작업 상태 조회 (폴링)",
                    "description": (
                        "**작업이 실패해도 HTTP는 200이다.** 조회 자체는 성공했기 때문. "
                        "`status` 필드로 판별한다. 404는 jobId가 없을 때만.\n\n"
                        "완료된 작업은 **90일** 동안 조회 가능하다(SQLite 기록). "
                        "서버가 재시작돼도 유지되며, 중단됐던 작업은 자동으로 다시 큐에 들어간다."
                    ),
                    "parameters": [
                        {
                            "name": "jobId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                            "example": "mrg_e2b7d3a662394c418669",
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "작업 상태 (WAITING / RUNNING / DONE / ERROR)",
                            "content": {"application/json": {"schema": _JOB_STATUS}},
                        },
                        "404": {
                            "description": "jobId 없음 (E4040)",
                            "content": {"application/json": {"schema": _ERROR_SCHEMA}},
                        },
                    },
                }
            },
            "/v1/merge/{jobId}/download": {
                "get": {
                    "tags": ["merge-test"],
                    "summary": "병합 결과 내려받기 (업로드 경로 전용)",
                    "description": (
                        "`POST /v1/merge/upload`로 만든 작업의 결과 파일을 반환한다.\n\n"
                        "presigned 경로(`POST /v1/merge`)로 만든 작업은 결과를 "
                        "스토리지에 올리고 로컬에서 지우므로 404가 난다."
                    ),
                    "parameters": [
                        {
                            "name": "jobId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "병합된 오디오 파일",
                            "content": {"audio/flac": {"schema": {"type": "string", "format": "binary"}}},
                        },
                        "404": {"description": "결과 없음 (미완료·실패·presigned 경로)"},
                    },
                }
            },
            "/v1/merge": {
                "get": {
                    "tags": ["merge"],
                    "summary": "병합 이력 조회",
                    "description": (
                        "SQLite에 보관된 기록을 최신순으로 반환한다(기본 90일 보존).\n\n"
                        "서버를 거치지 않고 직접 조회할 수도 있다:\n"
                        "`sqlite3 runtime/merge.db \"SELECT room_no, status FROM merge_jobs\"`"
                    ),
                    "parameters": [
                        {
                            "name": "roomNo",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string"},
                            "description": "특정 회의룸으로 좁힌다.",
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "default": 50, "maximum": 500},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "최신순 기록 목록",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "count": {"type": "integer"},
                                            "jobs": {"type": "array", "items": {"type": "object"}},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/health": {
                "get": {
                    "tags": ["ops"],
                    "summary": "헬스체크",
                    "responses": {"200": {"description": "정상"}},
                }
            },
            "/metrics": {
                "get": {
                    "tags": ["ops"],
                    "summary": "메트릭",
                    "responses": {"200": {"description": "메트릭 값"}},
                }
            },
        },
    }


def document_json(*, server_url: str = "/") -> bytes:
    return json.dumps(build_document(server_url=server_url), ensure_ascii=False).encode("utf-8")


def swagger_page(*, spec_url: str = "/openapi.json", asset_base: str = "/docs") -> bytes:
    """Swagger UI shell pointing at the vendored assets (no CDN, no network)."""
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>recog 음성 병합 API</title>
  <link rel="stylesheet" href="{asset_base}/swagger-ui.css">
  <style>
    body {{ margin: 0; background: #fafafa; }}
    .topbar {{ display: none; }}
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="{asset_base}/swagger-ui-bundle.js"></script>
  <script>
    window.ui = SwaggerUIBundle({{
      url: "{spec_url}",
      dom_id: "#swagger-ui",
      deepLinking: true,
      docExpansion: "list",
      defaultModelsExpandDepth: -1,
      tryItOutEnabled: true
    }});
  </script>
</body>
</html>
"""
    return html.encode("utf-8")


def read_asset(name: str) -> tuple[bytes, str] | None:
    """Return (bytes, content-type) for a vendored asset, or None if unknown."""
    content_type = SWAGGER_ASSETS.get(name)
    if content_type is None:
        return None
    path = STATIC_DIR / name
    if not path.is_file():
        return None
    return path.read_bytes(), content_type
