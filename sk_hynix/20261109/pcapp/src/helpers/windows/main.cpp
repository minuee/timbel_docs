#include "AudioHelper.h"
#include "versioninfo.h"
#include <iostream>
#include <memory>
#include <io.h>
#include <fcntl.h>

int main() {
    // Force UTF-8 bytes on pipes (no CRuntime recoding)
    _setmode(_fileno(stdout), _O_BINARY);
    _setmode(_fileno(stderr), _O_BINARY);
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);
    
    try {
        auto audioHelper = std::make_unique<AudioHelper>();
        
        // Helper 버전 정보 전송 (WebRTC AEC 포함)
        std::cout << "{\"ev\":\"helper_info\",\"utf8\":true,\"version\":\"" << AUDIOHELPER_VERSION_SHORT 
                  << "\",\"webrtc_aec\":" << (AUDIOHELPER_HAS_WEBRTC_AEC ? "true" : "false") 
                  << ",\"build_date\":\"" << AUDIOHELPER_BUILD_DATE << "\"}\n";
        
        if (!audioHelper->Initialize()) {
            std::cerr << "Failed to initialize AudioHelper" << std::endl;
            return -1;
        }
        
        // JSON 硫붿떆吏 ?湲?諛?泥섎━
        audioHelper->Run();
        
    } catch (const std::exception& e) {
        std::cerr << "Exception in main: " << e.what() << std::endl;
        return -1;
    }
    
    return 0;
}