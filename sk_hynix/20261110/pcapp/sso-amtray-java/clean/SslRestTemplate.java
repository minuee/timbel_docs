// 서버 샘플 — SSL RestTemplate (원본: restTemplate.java). 백엔드 참고용
// ⚠️ 모든 인증서를 믿는다(trust all) + 호스트 이름 검증을 바꾼다 → 사내 인증서 때문으로 보임.
//    운영에서 그대로 쓸지는 백엔드·보안 판단 필요 (사내 CA 를 truststore 에 넣는 쪽이 안전).

private static RestTemplate getSSLRestTemplate() {
    RestTemplate restTemplate;
    try {
        TrustStrategy acceptingTrustStrategy = (java.security.cert.X509Certificate[] chain, String authType) -> true;
        SSLContext sslContext = SSLContextBuilder.create()            // [정리] 원본: SSLContextsBuilder
                .loadTrustMaterial(null, acceptingTrustStrategy)
                .build();

        SSLConnectionSocketFactory csf = new SSLConnectionSocketFactory(sslContext, new CustomHostnameVerifier());
        // [?] CustomHostnameVerifier 내용은 원본에 없음

        CloseableHttpClient httpClient = HttpClients.custom()
                .setSSLSocketFactory(csf)
                .build();

        HttpComponentsClientHttpRequestFactory requestFactory = new HttpComponentsClientHttpRequestFactory();
        requestFactory.setHttpClient(httpClient);
        restTemplate = new RestTemplate(requestFactory);

    } catch (Exception e) {
        logger.error("Error creating SSL RestTemplate", e);
        restTemplate = new RestTemplate();
    }
    return restTemplate;
}
