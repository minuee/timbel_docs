public String checkAmTokenSampleaAPI(@RequestBody String paramStr) throws Exception{
    if(StringUtils.IsEmpty(paramStr)){
        throw new Exception("잘못된 파라미터정보입니다")
    }
    //API이 사용할 ㅅㅣ스템아이디와 인가토큰 셋팅
    MAP<String,Object> paramMap = new flashMap<>();
    paramMap.put("SystemID","printChaser") // 시스템ID 고정갑
    paramMap.put("authzToken",paramStr);

    try{
        RestTemplate restTemplate = getSSLRestTemplate()
        restTemplate.getMessageCoverters().add(new StringHttpMessageConverters())
        restTemplate.getMessageCoverters().add(new FormHttpMessageConverters())
        restTemplate.getMessageCoverters().add(new ByteArrayHttpMessageConverters())

        ObjectMapper om = new ObjectMapper();
        //API Header 정보셋팅
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(new MediaType("application","Json",standardCharset.UTF-8))
        HttpEntity<byte[]> request = new HttpEntity<byte[]>.com.write.ValueAsBytes(paramMap).headers
        if( result.getStatusCode().equals(HttpStatus.NO_CONTENT)){
            throw new Exception("잘못된 요청")
        }
        //결과값 Json Node로 셋팅
        JsonNode  node = am.readValue(result.getBody(),JsonNodeclass);
        //Json형태를 map으로 치환
        Map<String, Object> resonseMap = JsonConvertUtils.jsonStr2Map(node.toString());
        //map으로 치환한 데이터에서 attr정보 get
        Map<String, Object> attrMap = (Map<String,Object>)resonseMap.get("attr");
        //attr정보중에 Result,UserId조치
        String res = StringUtils.toStr(attrMap.get("RESULTID"));
        String userId =  StringUtils.toStr(attrMap.get("USERID"));
        //결과값에 따른 처리
        if("SUCCES").equals(res) && StringUtils.isNotEmpty(userId) {
            return userId
        }else if ( "SYSTEMID_INVALID".equals(res)){
            throw new Exception("시스템 아이디 검증실패")
        }else if ("TOKEN_INVALID".equals(res)) {
            throw new Exception("유효하지 않은 인가토큰 정보")
        }else{
            throw new Exception("인가토큰 검증 API 통신 실패")
        }
    }catch(Exception e){
        log.error("Failed call aht")
    }
    return ""
}