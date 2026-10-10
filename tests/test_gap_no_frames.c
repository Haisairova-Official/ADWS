#define SPACE_TEST
#include "../src/niri-desktop-layer/integration/waybar-space.c"
static void release_zone(GtkWindow *window) {(void)window;}
int main(void) {
 Space s={0}; s.duration=80;s.from_gap=8;s.gap=8;s.target_gap=0;s.animation_start=g_get_monotonic_time();
 s.animation=g_timeout_add(16,animate_gap,&s);
 gint64 deadline=g_get_monotonic_time()+1000000;
 while(s.animation && g_get_monotonic_time()<deadline) g_main_context_iteration(NULL,TRUE);
 g_assert_cmpfloat(s.gap,==,0);g_assert_cmpuint(s.animation,==,0);
 s.from_gap=0;s.target_gap=8;s.animation_start=g_get_monotonic_time();s.animation=g_timeout_add(16,animate_gap,&s);
 while(s.animation && g_get_monotonic_time()<deadline) g_main_context_iteration(NULL,TRUE);
 g_assert_cmpfloat(s.gap,==,8);
 s.animation=g_timeout_add(16,animate_gap,&s);stop_animation(&s);g_assert_cmpuint(s.animation,==,0);
 return 0;
}
