#include "common.h"
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

/* Strict finite wire grammar: exact field count, no signs, overflow or trailing data. */
bool fields(const char *line, const char *verb, char values[][FIELD], size_t count) {
    size_t n = strnlen(verb, FIELD);
    if (n == FIELD || strncmp(line, verb, n) || line[n] != ' ') return false;
    const char *p = line + n + 1;
    for (size_t i = 0; i < count; i++) {
        size_t j = 0;
        while (*p && *p != ' ') {
            if (j + 1 == FIELD || !token_ok((char[]){*p, 0})) return false;
            values[i][j++] = *p++;
        }
        values[i][j] = 0;
        if (!j) return false;
        if (i + 1 < count) { if (*p++ != ' ') return false; }
        else if (*p) return false;
    }
    return true;
}
bool decimal(const char *text, uint32_t maximum, uint32_t *value) {
    size_t n = strnlen(text, FIELD);
    if (!n || n == FIELD) return false;
    uint32_t v = 0;
    for (size_t i = 0; i < n; i++) {
        if (text[i] < '0' || text[i] > '9') return false;
        uint32_t digit = (uint32_t)(text[i] - '0');
        if (digit > maximum || v > (maximum - digit) / 10) return false;
        v = v * 10 + digit;
    }
    *value = v; return true;
}
bool formatted(char *buffer, size_t capacity, int length) {
    if (length < 0 || (size_t)length >= capacity) { if (capacity) buffer[0] = 0; return false; }
    return true;
}
void write_formatted(FILE *stream, const char *buffer, size_t capacity, int length) {
    if (length < 0 || (size_t)length >= capacity || fwrite(buffer, 1, (size_t)length, stream) != (size_t)length) _exit(74);
}

bool token_ok(const char *s) {
    size_t n = strnlen(s, FIELD);
    if (!n || n >= FIELD) return false;
    for (size_t i = 0; i < n; i++)
        if (!isalnum((unsigned char)s[i]) && s[i] != '_' && s[i] != '-' && s[i] != '.') return false;
    return true;
}
bool peer_token(int fd, audit_token_t *token) {
    socklen_t size = sizeof(*token);
    return getsockopt(fd, SOL_LOCAL, LOCAL_PEERTOKEN, token, &size) == 0 && size == sizeof(*token);
}
SecRequirementRef requirement_file(const char *path) {
    char data[4096];
    int fd = open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    struct stat st;
    if (fd < 0) return NULL;
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_uid != 0 || (st.st_mode & 0022)) { close(fd); return NULL; }
    FILE *f = fdopen(fd, "r");
    if (!f) { close(fd); return NULL; }
    size_t n = fread(data, 1, sizeof(data), f);
    bool ok = !ferror(f) && feof(f) && n > 0 && n < sizeof(data) && !memchr(data, 0, n);
    fclose(f);
    if (!ok) return NULL;
    CFStringRef text = CFStringCreateWithBytes(NULL, (const UInt8 *)data, n, kCFStringEncodingUTF8, false);
    SecRequirementRef requirement = NULL;
    if (text) { SecRequirementCreateWithString(text, kSecCSDefaultFlags, &requirement); CFRelease(text); }
    return requirement;
}
bool signed_code(const audit_token_t *token, SecRequirementRef requirement) {
    if (!requirement) return false;
    SecCodeRef code = NULL;
    OSStatus result;
    if (token) {
        CFDataRef value = CFDataCreate(NULL, (const UInt8 *)token, sizeof(*token));
        const void *keys[] = { kSecGuestAttributeAudit }, *values[] = { value };
        CFDictionaryRef attrs = CFDictionaryCreate(NULL, keys, values, 1, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
        result = SecCodeCopyGuestWithAttributes(NULL, attrs, kSecCSDefaultFlags, &code);
        CFRelease(attrs); CFRelease(value);
    } else result = SecCodeCopySelf(kSecCSDefaultFlags, &code);
    if (result != errSecSuccess || !code) return false;
    CFDictionaryRef info = NULL;
    uint32_t flags = kSecCodeSignatureAdhoc;
    bool valid = SecCodeCheckValidity(code, kSecCSDefaultFlags, requirement) == errSecSuccess &&
        SecCodeCopySigningInformation(code, kSecCSSigningInformation, &info) == errSecSuccess;
    if (valid) {
        CFNumberRef value = CFDictionaryGetValue(info, kSecCodeInfoFlags);
        valid = value && CFNumberGetValue(value, kCFNumberSInt32Type, &flags) && !(flags & kSecCodeSignatureAdhoc);
    }
    if (info) CFRelease(info);
    CFRelease(code);
    return valid;
}
void json_token(FILE *out, audit_token_t t) {
    output(out, "[%u,%u,%u,%u,%u,%u,%u,%u]", t.val[0], t.val[1], t.val[2], t.val[3], t.val[4], t.val[5], t.val[6], t.val[7]);
}
int socket_connect(const char *path) {
    struct sockaddr_un addr = { .sun_family = AF_UNIX };
    if (strnlen(path, sizeof(addr.sun_path)) >= sizeof(addr.sun_path)) return -1;
    strlcpy(addr.sun_path, path, sizeof(addr.sun_path));
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    fcntl(fd, F_SETFD, FD_CLOEXEC);
    int one = 1;
    if (setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof(one))) { close(fd); return -1; }
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr))) { close(fd); return -1; }
    return fd;
}
bool write_all(int fd, const char *s) {
    size_t size = strnlen(s, FRAME);
    if (size == FRAME) return false;
    while (size) {
        ssize_t n = write(fd, s, size);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return false;
        s += n; size -= (size_t)n;
    }
    return true;
}
int read_line(int fd, char *buffer, size_t capacity) {
    for (size_t i = 0; i + 1 < capacity; i++) {
        char c;
        ssize_t n;
        do { n = read(fd, &c, 1); } while (n < 0 && errno == EINTR);
        if (n <= 0 || c == 0) return -1;
        if (c == '\n') { buffer[i] = 0; return (int)i; }
        buffer[i] = c;
    }
    return -1;
}

/* Loaded in the scheduler process (not a subprocess): returned token belongs to that scheduler. */
int scheduler_identity(const char *socket_path, const char *collector_requirement, audit_token_t *identity) {
    SecRequirementRef requirement = requirement_file(collector_requirement);
    if (!requirement) return -1;
    int fd = socket_connect(socket_path);
    audit_token_t server;
    bool valid = fd >= 0 && peer_token(fd, &server) && server.val[1] == 0 && signed_code(&server, requirement);
    CFRelease(requirement);
    char line[256], parts[8][FIELD];
    if (valid) valid = write_all(fd, "IDENTITY\n") && read_line(fd, line, sizeof(line)) > 0;
    if (valid) valid = fields(line, "IDENTITY", parts, 8);
    for (size_t i = 0; valid && i < 8; i++) valid = decimal(parts[i], UINT32_MAX, &identity->val[i]);
    if (valid) valid = identity->val[5] == (uint32_t)getpid() && identity->val[1] == (uint32_t)geteuid();
    if (fd >= 0) close(fd);
    return valid ? 0 : -1;
}

/* The caller loads this signed library only after verifying its exact requirement.
 * This descriptor is the authenticated event/command channel, not a fixture pipe. */
int session_connect(const char *socket_path, const char *collector_requirement,
                    const char *resource, const char *nonce, const char *image) {
    if (!token_ok(resource) || !token_ok(nonce) || !token_ok(image)) return -1;
    SecRequirementRef requirement = requirement_file(collector_requirement);
    if (!requirement) return -1;
    int fd = socket_connect(socket_path);
    audit_token_t server;
    bool valid = fd >= 0 && peer_token(fd, &server) && server.val[1] == 0 && signed_code(&server, requirement);
    CFRelease(requirement);
    char frame[1024];
    if (valid) valid = format(frame, sizeof(frame), "SESSION %s %s %s\n", resource, nonce, image) && write_all(fd, frame);
    if (!valid && fd >= 0) close(fd);
    return valid ? fd : -1;
}
