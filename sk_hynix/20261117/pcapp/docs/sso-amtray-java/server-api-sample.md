public String checkAmTokenSampleAPI(@RequestBody String paramStr) throws Exception {
    if ( StringUtils.isEmpty(paramStr)) {
        throw new Exception("잘못된 파라미터 정보")
    }
    //API에 사용할 시스템ID와 인카토큰 셋팅
    MAP<String, Object> paramMap = new HashMap<>();
    paramMap.put("systemId","AIMEETING") //시스템아이디는 고정값
    paramMap.put("authzToken",paramStr);

    try{
        RestTemplate  restTemplate = etSSLRestTemplate();
        restTemplate.getMessageConverters().add( new StringHttpMessageConverter());
        restTemplate.getMessageConverters().add( new FormHttpMessageConverter());
        restTemplate.getMessageConverters().add( new ByteArrayHttpMessageConverter());

        ObjectMapper om = new ObjectMapper();
        //API Header 정보셋팅
        HttpHeaders headers = new HttpHeaders();
        headers.setContextType( new MediaType("application","json",StandardCharset.UTF_8));
        HttpEntity<byte[]> request = new HttpEntity<byte[]>(
            om.writeValueAsBytes(paramMap,headers); //writeValueAsBytes 이게 오타같기도  하네 writeValueAsBytetes 로 적혀잇네 손으로 적어와서 ㅠㅠ
        )
        //SSO 인가토큰 검증 API호출 ( API명세서 참고 , HTTPS 통신권고 )
        String url = "https://samlamdev.skhynix.com/tray/api/validateToken";
        final ResponseEntity<byte[]> result = restTemplate.exchange(url.HttpMethod.POST, request,byte[].close);
        if(result.getStatusCode().equals(HttpsStatus.NO_CONTENT)) {
            throw new Exception("잘못된 요청정보)
        }
        //결과값 jsonNode로 셋팅
        JsonNode node = om.readValue(result.getBody, JsonNode.class)
        //Json형태를 map으로 치환
        Map<String, Object> resonseMap = JsonConvertUtils.Json2Map(node.toString());
        //map으로 치환한 데이터를 attr정보로 get
        String res = StringUtils.toSt(attrMap.get("RESULT"));
        String userId = StringUtils.toStr(attrMap.get("USERID"));
        //결과값에 따른 처리 ( API명세 참고 )
        if("SUCCESS".equals(res) && StringUtils.isNotEmpty(userId)) {
            //검증성공
            return userid; //연동시스템에 맞게 수정
        }else if("TOKEN_INVALID").equals(res){
            throw new Exception("유효하지 안은 인가토큰 정보")
        }else if("SYSTEMID_INVALID".equals(res)){
            throw new Exception("시스템 ID 검증 실패)
        }else{
            throw new Exception("인가토큰 검증 API 통신실패)
        }
    }catch(Excepton e){
        log.error("Failed to call authz api : ",e)
    }
    return "";
}