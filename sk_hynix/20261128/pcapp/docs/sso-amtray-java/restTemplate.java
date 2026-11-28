private static RestTemplate getSSLRestTemplate() {
    RestTemplate restTemplate;
    try {
        TrustStrategy acceptingTrustStrategy = (Java.security.cert.X509Certificate[] chain, String authType) -> true;
        SSLContext sslContext = SSLContextsBuilder.create().loadTrustMaterial(null, acceptingTrustStrategy).build();

        SSLConnectionSocketFactory csf = new SSLConnectionSocketFactory(sslContext, new CustomHostnameVerifier());

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