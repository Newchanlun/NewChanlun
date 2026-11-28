/* Pure framing rejection tests: no ES, signing operation, kernel peer fixture, or business child. */
#include "common.h"
#include <assert.h>
#include <fcntl.h>
#include <string.h>
#include <signal.h>
#include <sys/wait.h>
#include <sys/socket.h>
#include <unistd.h>
int main(void) {
    assert(token_ok("action-1.a"));
    assert(!token_ok("")); assert(!token_ok("x\ny")); assert(!token_ok("/path"));
    assert(!signed_code(NULL, NULL));
    char values[3][FIELD], small[4]; uint32_t number;
    assert(fields("REGISTER resource nonce helper", "REGISTER", values, 3));
    assert(!fields("REGISTER resource nonce helper garbage", "REGISTER", values, 3));
    assert(!fields("REGISTER resource  helper", "REGISTER", values, 3));
    assert(!fields("REGISTER resource nonce helper\n", "REGISTER", values, 3));
    char long_field[FIELD + 10]; memset(long_field, 'a', sizeof(long_field)); long_field[sizeof(long_field)-1] = 0;
    assert(!token_ok(long_field));
    char oversized[256]; assert(format(oversized, sizeof(oversized), "ARM %s", long_field));
    assert(!fields(oversized, "ARM", values, 1));
    assert(decimal("4294967295", UINT32_MAX, &number) && number == UINT32_MAX);
    assert(!decimal("4294967296", UINT32_MAX, &number));
    assert(!decimal("-1", UINT32_MAX, &number)); assert(!decimal("+1", UINT32_MAX, &number));
    assert(!decimal("12tail", UINT32_MAX, &number)); assert(!decimal("", UINT32_MAX, &number));
    assert(!decimal("256", 255, &number)); assert(decimal("255", 255, &number));
    assert(!format(small, sizeof(small), "%s", "1234") && small[0] == 0);
    assert(format(small, sizeof(small), "%s", "123"));
    pid_t child = fork(); assert(child >= 0);
    if (!child) {
        FILE *readonly = fdopen(open("/dev/null", O_RDONLY | O_CLOEXEC), "r"); assert(readonly);
        setvbuf(readonly, NULL, _IONBF, 0);
        output(readonly, "%s", "cannot write"); _exit(99);
    }
    int status; assert(waitpid(child, &status, 0) == child);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == 74);
    int pair[2]; char line[32];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(write_all(pair[0], "REGISTER x\n"));
    assert(read_line(pair[1], line, sizeof(line)) == 10 && !strcmp(line, "REGISTER x"));
    assert(write(pair[0], "bad\0\n", 5) == 5);
    assert(read_line(pair[1], line, sizeof(line)) == -1);
    close(pair[1]); signal(SIGPIPE, SIG_IGN);
    assert(!write_all(pair[0], "closed peer")); close(pair[0]);
    puts("native framing: passed (no peer authentication asserted)");
    return 0;
}
