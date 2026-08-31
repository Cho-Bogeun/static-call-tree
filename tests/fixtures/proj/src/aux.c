#include "common.h"

static int reset_count;

/* proc.c 의 reset 과 이름이 같다. USR 에 파일 경로가 들어가므로 뭉치지 않는다. */
static void reset(void)
{
    reset_count = 1;
}

void aux_barrier(void)
{
    /* 인라인 asm: 안에서 무엇을 부르는지 알 수 없는 지점 */
    __asm__ volatile("" ::: "memory");
}

int aux_entry(int v)
{
    reset();
    return clamp(v, 8) + reset_count;
}
