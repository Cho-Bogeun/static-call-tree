#ifndef COMMON_H
#define COMMON_H

/* 정의는 cfg.c 에 있다. 선언과 정의의 USR 이 같으므로 병합되어야 한다. */
extern int g_flag;
extern const int g_cfg;

/* 어느 TU 에서도 정의를 보지 못하는 함수. 콜트리에서 리프로 확정된다. */
int ext_lib(int v);
void sink(int *p);

/* 헤더에 정의된 static inline. TU 마다 중복 등장하므로 dedupe 대상이다. */
static inline int clamp(int v, int hi)
{
    return v > hi ? hi : v;
}

typedef int (*handler_fn)(int);

#endif /* COMMON_H */
