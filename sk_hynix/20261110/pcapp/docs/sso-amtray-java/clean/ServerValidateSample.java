// 서버 샘플 — 인가토큰 검증 (원본: auth.java). 백엔드 참고용 (Spring)

public String checkAmTokenSampleAPI(@RequestBody String paramStr) throws Exception {   // [정리] 원본: checkAmTokenSampleaAPI
    if (StringUtils.isEmpty(paramStr)) {
        throw new Exception("잘못된 파라미터정보입니다");
    }

    // API 에 사용할 시스템아이디와 인가토큰 셋팅
    Map<String, Object> paramMap = new HashMap<>();          // [정리] 원본: MAP / flashMap
    paramMap.put("SystemID", "printChaser");                 // 시스템ID 고정값 — 샘플은 다른 시스템(printChaser) 값
    paramMap.put("authzToken", paramStr);

    try {
        RestTemplate restTemplate = getSSLRestTemplate();    // SslRestTemplate.java
        restTemplate.getMessageConverters().add(new StringHttpMessageConverter());
        restTemplate.getMessageConverters().add(new FormHttpMessageConverter());
        restTemplate.getMessageConverters().add(new ByteArrayHttpMessageConverter());

        ObjectMapper om = new ObjectMapper();

        // API Header 정보 셋팅
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(new MediaType("application", "json", StandardCharsets.UTF_8));
        HttpEntity<byte[]> request = new HttpEntity<>(om.writeValueAsBytes(paramMap), headers);
        // [정리] 원본: new HttpEntity<byte[]>.com.write.ValueAsBytes(paramMap).headers

        // [정리] 원본에 호출 줄이 빠져 있음 → 아래처럼 보임 [?]
        ResponseEntity<String> result = restTemplate.postForEntity(VALIDATE_TOKEN_URL, request, String.class);

        if (result.getStatusCode().equals(HttpStatus.NO_CONTENT)) {
            throw new Exception("잘못된 요청");
        }

        // 결과값 JsonNode 로 셋팅 → Map 으로 치환
        JsonNode node = om.readValue(result.getBody(), JsonNode.class);   // [정리] 원본: am.readValue(..., JsonNodeclass)
        Map<String, Object> responseMap = JsonConvertUtils.jsonStr2Map(node.toString());

        // attr 정보 중 RESULTID, USERID 조회
        Map<String, Object> attrMap = (Map<String, Object>) responseMap.get("attr");
        String res    = StringUtils.toStr(attrMap.get("RESULTID"));
        String userId = StringUtils.toStr(attrMap.get("USERID"));

        // 결과값에 따른 처리
        if ("SUCCESS".equals(res) && StringUtils.isNotEmpty(userId)) {   // [정리] 원본: "SUCCES"
            return userId;
        } else if ("SYSTEMID_INVALID".equals(res)) {
            throw new Exception("시스템 아이디 검증실패");
        } else if ("TOKEN_INVALID".equals(res)) {
            throw new Exception("유효하지 않은 인가토큰 정보");
        } else {
            throw new Exception("인가토큰 검증 API 통신 실패");
        }
    } catch (Exception e) {
        log.error("Failed call auth", e);                    // [정리] 원본: "Failed call aht"
    }
    return "";
}
