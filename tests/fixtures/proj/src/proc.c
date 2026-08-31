#include "common.h"

static int g_buf[4];

static void reset(void)
{
    g_buf[0] = 0;
    g_flag = 0;
}

static int dispatch(handler_fn fn, int v)
{
    return fn(v); /* 함수 포인터 호출: 콜리를 특정할 수 없다 */
}

int process_frame(int v)
{
    static int retry_cnt; /* 함수 내 static: 스코프만 좁은 숨은 상태 */

    retry_cnt++;
    g_flag += v;
    reset();
    sink(&g_flag);
    sink(g_buf); /* 배열 감쇠 */
    return ext_lib(v) + g_cfg + clamp(v, 10) + dispatch(0, v) + g_buf[retry_cnt];
}
