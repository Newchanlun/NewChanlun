/* Pure framing rejection tests: no ES, signing operation, kernel peer fixture, or business child. */
#include "common.h"
#include <assert.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
int main(void) {
    assert(token_ok("action-1.a"));
    assert(!token_ok("")); assert(!token_ok("x\ny")); assert(!token_ok("/path"));
    assert(!signed_code(NULL, NULL));
    int pair[2]; char line[32];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(write_all(pair[0], "REGISTER x\n"));
    assert(read_line(pair[1], line, sizeof(line)) == 10 && !strcmp(line, "REGISTER x"));
    assert(write(pair[0], "bad\0\n", 5) == 5);
    assert(read_line(pair[1], line, sizeof(line)) == -1);
    close(pair[0]); close(pair[1]);
    puts("native framing: passed (no peer authentication asserted)");
    return 0;
}
