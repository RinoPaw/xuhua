#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <cstdint>
#include <vector>
#include <sys/file.h>
#include <fcntl.h>
#include <unistd.h>
#include "aikit_biz_api.h"
#include "aikit_constant.h"
#include "aikit_biz_config.h"

using namespace AIKIT;
static const char* ABILITY = "e867a88f2";
static FILE* events;
static std::mutex event_mutex;

static void error(const char* stage, int code) {
    std::lock_guard<std::mutex> guard(event_mutex);
    fprintf(events, "{\"type\":\"error\",\"stage\":\"%s\",\"code\":%d}\n", stage, code);
    fflush(events);
}
static void output(AIKIT_HANDLE*, const AIKIT_OutputData* data) {
    if (!data) return;
    std::lock_guard<std::mutex> guard(event_mutex);
    for (auto* node = data->node; node; node = node->next) {
        if (!node->value || node->len <= 0) continue;
        const char* raw = static_cast<const char*>(node->value);
        int size = node->len;
        while (size && !raw[size - 1]) --size;
        fprintf(events, "{\"type\":\"wake\",\"result\":%.*s}\n", size, raw);
    }
    fflush(events);
}
static void event(AIKIT_HANDLE*, AIKIT_EVENT, const AIKIT_OutputEvent*) {}
static void on_error(AIKIT_HANDLE*, int32_t code, const char*) { error("callback", code); }

int main() {
    int lock = open("/var/lib/xfyun-wake/engine.lock", O_CREAT | O_RDWR, 0600);
    if (lock < 0 || flock(lock, LOCK_EX | LOCK_NB)) return 2;
    // Keep vendor diagnostics off the JSON protocol and away from browser clients.
    events = fdopen(dup(STDOUT_FILENO), "w");
    if (!events || !freopen("/dev/null", "w", stdout)) return 1;
    const char* app = getenv("XF_APP_ID");
    const char* key = getenv("XF_API_KEY");
    const char* secret = getenv("XF_API_SECRET");
    if (!app || !key || !secret) { error("credentials", -1); return 1; }
    AIKIT_Configurator::builder().app().appID(app).apiKey(key).apiSecret(secret)
        .workDir("/var/lib/xfyun-wake").auth().authType(0).ability(ABILITY)
        .log().logLevel(LOG_LVL_OFF).logMode(LOG_FILE).logPath("/var/lib/xfyun-wake/sdk.log");
    AIKIT_Callbacks callbacks = {output, event, on_error};
    AIKIT_RegisterAbilityCallback(ABILITY, callbacks);
    int code = AIKIT_Init();
    if (code) { error("init", code); return 1; }
    code = AIKIT_EngineInit(ABILITY, nullptr);
    if (code) { error("engine_init", code); AIKIT_UnInit(); return 1; }
    const char* keyword_path = "/var/lib/xfyun-wake/keywords.txt";
    AIKIT_CustomData custom = {};
    custom.key = "key_word";
    custom.index = 0;
    custom.from = AIKIT_DATA_PTR_PATH;
    custom.value = const_cast<char*>(keyword_path);
    custom.len = strlen(keyword_path);
    code = AIKIT_LoadData(ABILITY, &custom);
    if (code) { error("load_keywords", code); AIKIT_EngineUnInit(ABILITY); AIKIT_UnInit(); return 1; }
    int indexes[] = {0};
    code = AIKIT_SpecifyDataSet(ABILITY, "key_word", indexes, 1);
    auto* params = AIKIT_ParamBuilder::create();
    const char* thresholds = getenv("WAKE_THRESHOLDS");
    if (!thresholds) thresholds = "0 0:1000|0 1:1000";
    params->param("wdec_param_nCmThreshold", thresholds, strlen(thresholds));
    params->param("gramLoad", true);
    AIKIT_HANDLE* handle = nullptr;
    if (!code) code = AIKIT_Start(ABILITY, AIKIT_Builder::build(params), nullptr, &handle);
    if (code) error("start", code);
    else {
        fprintf(events, "{\"type\":\"ready\",\"sample_rate\":16000}\n");
        fflush(events);
        auto* builder = AIKIT_DataBuilder::create();
        std::vector<char> pending;
        unsigned char header[4];
        while (fread(header, 1, 4, stdin) == 4) {
            uint32_t length = uint32_t(header[0]) | (uint32_t(header[1]) << 8)
                | (uint32_t(header[2]) << 16) | (uint32_t(header[3]) << 24);
            if (!length) {
                AIKIT_End(handle);
                handle = nullptr;
                pending.clear();
                code = AIKIT_SpecifyDataSet(ABILITY, "key_word", indexes, 1);
                if (!code) code = AIKIT_Start(ABILITY, AIKIT_Builder::build(params), nullptr, &handle);
                if (code) { error("reset", code); break; }
                fprintf(events, "{\"type\":\"ready\",\"sample_rate\":16000}\n");
                fflush(events);
                continue;
            }
            if (length > 6400 || length % 2) { error("frame", -1); break; }
            std::vector<char> frame(length);
            if (fread(frame.data(), 1, length, stdin) != length) break;
            pending.insert(pending.end(), frame.begin(), frame.end());
            size_t offset = 0;
            while (pending.size() - offset >= 320) {
                builder->clear();
                builder->payload(AiAudio::get("wav")->data(pending.data() + offset, 320)->valid());
                code = AIKIT_Write(handle, AIKIT_Builder::build(builder));
                offset += 320;
                if (code) break;
            }
            pending.erase(pending.begin(), pending.begin() + offset);
            if (code) { error("write", code); break; }
        }
        if (handle) AIKIT_End(handle);
        delete builder;
    }
    delete params;
    AIKIT_UnLoadData(ABILITY, "key_word", 0);
    AIKIT_EngineUnInit(ABILITY);
    AIKIT_UnInit();
    fclose(events);
    return code ? 1 : 0;
}
