# ECP 컴포넌트 사용 가이드

MFA(Module Federation) 환경에서 `@timbel-aicc/ecp-ui-kit` 컴포넌트를 자동으로 import하여 사용하는 방법입니다.

## 📁 **프로젝트 구조**

```
ECP-remote-view-main/
├── build/
│   └── auto-import-loader.cjs     # 자동 import 처리기
├── webpack.config.js              # Webpack 설정 (로더 등록)
├── src/
│   ├── main.ts                   # ECP 전역 등록 (MFA는 필요X)
│   ├── App.vue                   # common.scss + global.scss
│   ├── styles/
│   │   └── global.scss           # 커스텀 오버라이드 스타일
│   └── view/
│       └── ecp/
│           └── index.vue         # ECP 컴포넌트 사용 예시
```

## ⚙️ **시스템 작동 원리**

### **1. Auto Import Loader 동작**

```javascript
// build/auto-import-loader.cjs
module.exports = function (source) {
  // 1. Vue 파일에서 ECP 컴포넌트 사용 감지
  // 2. 필요한 경우에만 import 구문 자동 주입
  // 3. 스타일과 컴포넌트를 함께 번들링
};
```

### **2. Webpack 설정**

```javascript
// webpack.config.js
{
  test: /\.vue$/,
  use: [
    'vue-loader',
    {
      loader: path.resolve(__dirname, './build/auto-import-loader.cjs')
    }
  ]
}
```

### **3. MFA 독립 번들링**

```javascript
// Module Federation 설정
shared: {
  vue: { singleton: true, eager: true },
  pinia: { singleton: true, eager: true },
  "vue-router": { singleton: true, eager: true }
  // @timbel-aicc/ecp-ui-kit은 포함하지 않음 (독립 번들링)
}
```

## 🎯 **사용 방법**

### **기본 사용법**

```vue
<template>
  <div class="ecp-container">
    <!-- 별도 import 없이 바로 사용 가능 -->
    <ECPCard header="제목" shadow="always">
      <ECPTypography variant="body1">내용</ECPTypography>
      <ECPButton variant="primary">버튼</ECPButton>
    </ECPCard>
  </div>
</template>

<script setup lang="ts">
// ✨ ECP 컴포넌트는 자동으로 import됩니다!
// 수동 import 불필요:
// import { ECPCard, ECPTypography, ECPButton } from '@timbel-aicc/ecp-ui-kit';
// import '@timbel-aicc/ecp-ui-kit/style.css';

import { ref } from "vue";
const someData = ref("hello");
</script>
```

## 🔧 **새 컴포넌트 추가**

새로운 ECP 컴포넌트를 자동 import 대상에 추가하려면:

1. `build/auto-import-loader.cjs` 파일 열기
2. `componentsToImport` 배열에 추가:

```javascript
const componentsToImport = [
  "ECPButton",
  "ECPModal",
  // ... 기존 컴포넌트들
  "NewECPComponent" // 새 컴포넌트 추가
];
```

## ⚠️ **주의사항**

### **1. scss 수정 금지**

- element.scss, devExtreme.scss, common.scss, layout.scss 파일 등은 타 개발사 솔루션과 공통 적용된 스타일입니다.
- ECP 컴포넌트와 충돌되거나 공통 스타일은 `global.scss` 사용
- 페이지 커스텀 필요시 컴포넌트 내 `<style scoped>` 사용

### **2. ECP 컴포넌트 관리**

- `@timbel-aicc/ecp-ui-kit` 새로운 컴포넌트 추가될 시 새 컴포넌트는 수동 추가 필요
