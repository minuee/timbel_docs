# System Overview

## 1. 목적
Audio Sync Capture Platform의 전체 구성 요소와 역할을 요약한다.

## 2. 구성요소
### Mobile Recording App
- room create/join
- ready
- host start
- baseline recorder
- metadata capture
- anchor
- upload

### Session / Control Server
- room lifecycle
- participant readiness
- start / stop control
- metadata persistence
- policy validation

### Processing Engine
- canonicalization
- metadata prior
- anchor detection
- audio fine alignment
- drift correction
- loudness normalization
- mix/export

## 3. 출력
- aligned tracks
- listening mix
- canonical manifest
- compat manifest
- STT input
- listening review packet

## 4. 핵심 원칙
- 앱이 capture truth를 만든다
- 서버가 session truth를 만든다
- backend가 audio truth를 맞춘다
