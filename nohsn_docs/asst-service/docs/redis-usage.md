# Redis 클라이언트 및 모니터링 사용법

이 문서는 asst-service에서 Redis 클라이언트와 동적 채널 모니터링 기능을 사용하는 방법을 설명합니다.

## 환경 설정

### 1. 환경 변수 설정

`.env` 파일에 다음 Redis 설정을 추가하세요:

```env
# Redis 설정
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0
REDIS_HEALTH_CHECK_INTERVAL=30000  # Health check interval (밀리초, 기본값: 30000ms = 30초)
```

### 2. Redis 서버 실행

Redis 서버가 실행 중인지 확인하세요:

```bash
# Docker를 사용하는 경우
docker run -d --name redis -p 6379:6379 redis:latest

# 또는 로컬에 Redis가 설치된 경우
redis-server
```

## 기본 사용법

### 1. RedisService 사용

RedisService는 기본적인 Redis 작업을 위한 서비스입니다.

```typescript
import { Injectable } from '@nestjs/common';
import { RedisService } from '@app/common/services/redis.service';

@Injectable()
export class YourService {
  constructor(private readonly redisService: RedisService) {}

  // 메시지 발행
  async publishMessage() {
    const success = await this.redisService.publish(
      'test-channel',
      'Hello World!',
    );
    console.log('메시지 발행:', success);
  }

  // 채널 구독
  async subscribeToChannel() {
    const success = await this.redisService.subscribe(
      'test-channel',
      (message) => {
        console.log('메시지 수신:', message);
      },
    );
    console.log('구독 성공:', success);
  }

  // 구독 해제
  async unsubscribeFromChannel() {
    const success = await this.redisService.unsubscribe('test-channel');
    console.log('구독 해제:', success);
  }

  // 구독 중인 채널 목록
  getSubscribedChannels() {
    const channels = this.redisService.getSubscribedChannels();
    console.log('구독 중인 채널:', channels);
  }

  // 연결 상태 확인
  isConnected() {
    return this.redisService.isConnectedToRedis();
  }
}
```

### 2. RedisMonitorService 사용

RedisMonitorService는 여러 채널을 동적으로 모니터링하는 고급 기능을 제공합니다.

```typescript
import { Injectable, OnModuleInit } from '@nestjs/common';
import {
  RedisMonitorService,
  MonitorConfig,
} from '@app/common/services/redis-monitor.service';

@Injectable()
export class YourMonitorService implements OnModuleInit {
  constructor(private readonly redisMonitorService: RedisMonitorService) {}

  async onModuleInit() {
    // 모니터링 시작
    const config: MonitorConfig = {
      channels: ['channel1', 'channel2', 'channel3'],
      autoReconnect: true,
      reconnectInterval: 5000,
      maxReconnectAttempts: 10,
    };

    await this.redisMonitorService.startMonitoring(config);

    // 헬스 체크 시작
    this.redisMonitorService.startHealthCheck();
  }

  // 동적으로 채널 추가
  async addNewChannel(channelName: string) {
    const success = await this.redisMonitorService.addChannel(channelName);
    console.log('채널 추가:', success);
  }

  // 채널 제거
  async removeChannel(channelName: string) {
    const success = await this.redisMonitorService.removeChannel(channelName);
    console.log('채널 제거:', success);
  }

  // 모니터링 통계 조회
  getStats() {
    const status = this.redisMonitorService.getMonitoringStatus();
    console.log('모니터링 상태:', status);

    const channelStats = this.redisMonitorService.getChannelStats();
    console.log('채널별 통계:', channelStats);
  }

  // 통계 리셋
  resetStats() {
    this.redisMonitorService.resetChannelStats();
    console.log('통계 리셋 완료');
  }
}
```

## API 엔드포인트

### 실시간 모니터링 API (redis-monitor)

- `POST /redis-monitor/subscribe/:channel` - 특정 채널 모니터링 시작
- `DELETE /redis-monitor/unsubscribe/:channel` - 특정 채널 모니터링 중지
- `GET /redis-monitor/channels` - 모니터링 중인 채널 목록
- `GET /redis-monitor/status` - Redis 모니터링 상태
- `DELETE /redis-monitor/unsubscribe-all` - 모든 채널 모니터링 중지

## 사용 예시

### Redis Monitor 사용법

```bash
# 특정 채널 모니터링 시작
curl -X POST http://localhost:3000/redis-monitor/subscribe/test-channel

# 모니터링 중인 채널 목록 조회
curl http://localhost:3000/redis-monitor/channels

# 모니터링 상태 확인
curl http://localhost:3000/redis-monitor/status
```

### 4. 실시간 모니터링 API 사용

```bash
# 특정 채널 모니터링 시작
curl -X POST http://localhost:3000/redis-monitor/subscribe/test-channel

# 모니터링 중인 채널 목록 조회
curl http://localhost:3000/redis-monitor/channels

# 모니터링 상태 확인
curl http://localhost:3000/redis-monitor/status

# 특정 채널 모니터링 중지
curl -X DELETE http://localhost:3000/redis-monitor/unsubscribe/test-channel

# 모든 채널 모니터링 중지
curl -X DELETE http://localhost:3000/redis-monitor/unsubscribe-all
```

## 고급 사용법

### 1. 커스텀 메시지 처리

RedisMonitorService의 `processMessage` 메서드를 오버라이드하여 특별한 메시지 처리 로직을 구현할 수 있습니다:

```typescript
// redis-monitor.service.ts에서 processMessage 메서드 수정
private processMessage(message: RedisMessage): void {
  // 특정 패턴의 메시지만 처리
  if (message.channel.startsWith('notification-')) {
    this.handleNotification(message);
  }

  // JSON 메시지 파싱
  try {
    const data = JSON.parse(message.message);
    this.processStructuredData(data, message.channel);
  } catch (error) {
    // 원본 메시지 처리
    this.processRawMessage(message.message, message.channel);
  }
}
```

### 2. 에러 처리 및 재연결

Redis 연결이 끊어졌을 때 자동으로 재연결을 시도합니다:

```typescript
const config: MonitorConfig = {
  channels: ['important-channel'],
  autoReconnect: true, // 자동 재연결 활성화
  reconnectInterval: 5000, // 5초마다 재연결 시도
  maxReconnectAttempts: 10, // 최대 10회 시도
};
```

### 3. 성능 모니터링

채널별 통계를 통해 성능을 모니터링할 수 있습니다:

```typescript
const stats = this.redisMonitorService.getChannelStats();
stats.forEach((stat) => {
  console.log(`채널: ${stat.channel}`);
  console.log(`메시지 수: ${stat.messageCount}`);
  console.log(`마지막 메시지: ${stat.lastMessageTime}`);
  console.log(`활성 상태: ${stat.isActive}`);
  console.log(`에러 수: ${stat.errorCount}`);
});
```

## 주의사항

1. **메모리 사용량**: 많은 채널을 구독할 경우 메모리 사용량이 증가할 수 있습니다.
2. **연결 관리**: Redis 연결이 끊어지면 자동으로 재연결을 시도하지만, 네트워크 문제가 지속되면 모니터링이 중단될 수 있습니다.
3. **메시지 처리**: 메시지 처리 중 오류가 발생하면 해당 메시지는 건너뛰고 다음 메시지를 처리합니다.
4. **스레드 안전성**: Redis 클라이언트는 스레드 안전하지만, 구독 콜백에서 비동기 작업을 수행할 때는 주의가 필요합니다.

## 문제 해결

### 1. 연결 실패

```bash
# Redis 서버 상태 확인
redis-cli ping

# 포트 확인
netstat -an | grep 6379
```

### 2. 메시지 수신 안됨

- 채널명이 정확한지 확인
- 구독 상태 확인: `GET /redis-monitor/channels`
- Redis 연결 상태 확인: `GET /redis-monitor/status`

### 3. 성능 문제

- 구독 중인 채널 수 확인
- 메시지 처리 로직 최적화
- 모니터링 중인 채널 정리: `DELETE /redis-monitor/unsubscribe-all`
