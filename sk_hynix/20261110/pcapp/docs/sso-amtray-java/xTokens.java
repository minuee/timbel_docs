public native Strung GetSystemTokenIT (
    String ssoKey, String sid, String systemID
)

public native boolean ShowSSOLoingUI(char * sid)

public native boolean SSOLogout(char * sid)

Bool GetReturnMessage(char * code, char * locale)