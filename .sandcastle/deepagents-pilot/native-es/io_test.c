/* Deterministic syscall injection, compiled only into this test executable. */
#include "common.h"
#include <assert.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>
static char received[FRAME];
static size_t used;
static unsigned calls;
static bool broken;
ssize_t native_test_write(int fd, const void *data, size_t size) {
    (void)fd;
    calls++;
    if (calls == 1) { errno = EINTR; return -1; }
    if (broken && calls == 3) { errno = EIO; return -1; }
    size_t n = size > 3 ? 3 : size;
    assert(used + n < sizeof(received));
    for (size_t i = 0; i < n; i++) received[used++] = ((const char *)data)[i];
    return (ssize_t)n;
}
int main(void) {
    assert(write_all(123, "0123456789"));
    assert(calls == 5 && used == 10 && !memcmp(received, "0123456789", 10));
    calls = 0; used = 0; broken = true;
    assert(!write_all(123, "0123456789"));
    assert(calls == 3 && used == 3);
    char oversized[FRAME]; memset(oversized, 'x', sizeof(oversized));
    calls = 0;
    assert(!write_all(123, oversized) && calls == 0);
    return 0;
}
