/* Real GTK style changes; replace only the Wayland exclusive-zone operation. */
#define SPACE_TEST
#include "../integration/waybar-space.c"
static int releases;
static void release_zone(GtkWindow *window) { (void)window; releases++; }
static GtkWidget *root;
static GtkContainer *get_root(wbcffi_module *obj) { (void)obj; return GTK_CONTAINER(root); }
static void drain(int ms) {
    gint64 until = g_get_monotonic_time() + ms * 1000;
    do {
        while (g_main_context_iteration(NULL, FALSE));
        g_usleep(1000);
    } while (g_get_monotonic_time() < until);
}
int main(int argc, char **argv) {
    gtk_init(&argc, &argv);
    GtkWidget *window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_container_add(GTK_CONTAINER(window), box);
    gtk_container_add(GTK_CONTAINER(box), gtk_label_new("Test"));
    root = gtk_event_box_new();
    gtk_container_add(GTK_CONTAINER(box), root);
    GtkCssProvider *css = gtk_css_provider_new();
    gtk_css_provider_load_from_data(css, "window > box { opacity: 1; transition: opacity 220ms ease-in-out; } window.mode-invisible > box { opacity: 0; }", -1, NULL);
    gtk_style_context_add_provider_for_screen(gtk_widget_get_screen(window), GTK_STYLE_PROVIDER(css), 800);
    wbcffi_init_info info = { .get_root_widget = get_root };
    Space *self = wbcffi_init(&info, NULL, 0);
    gtk_widget_show_all(window);
    drain(50);
    g_assert_false(gtk_widget_get_visible(root));
    GtkStyleContext *style = gtk_widget_get_style_context(window);
    gtk_style_context_add_class(style, "mode-invisible");
    drain(100);
    g_assert_cmpint(releases, ==, 0);
    g_assert_cmpuint(self->release, >, 0);
    gtk_style_context_remove_class(style, "mode-invisible");
    drain(300);
    g_assert_cmpint(releases, ==, 0);
    g_assert_cmpuint(self->release, ==, 0);
    gtk_style_context_add_class(style, "mode-invisible");
    drain(300);
    g_assert_cmpint(releases, ==, 1);
    drain(100);
    g_assert_cmpuint(self->sync, ==, 0);
    g_assert_cmpuint(self->release, ==, 0);
    wbcffi_deinit(self);
    /* Starting hidden must not leave an empty reserved strip. */
    self = wbcffi_init(&info, NULL, 0);
    drain(40);
    g_assert_cmpint(releases, ==, 2);
    gtk_style_context_remove_class(style, "mode-invisible");
    drain(40);
    gtk_style_context_add_class(style, "mode-invisible");
    drain(40);
    wbcffi_deinit(self);
    drain(300);
    g_assert_cmpint(releases, ==, 2);
    gtk_style_context_remove_class(style,"mode-invisible");
    wbcffi_config_entry entries[]={{"panel_mode","auto"},{"split_panel","true"},{"position","bottom"}};
    self=wbcffi_init(&info,entries,3);
    drain(50);
    g_assert_true(gtk_style_context_has_class(style,"adws-split"));
    g_assert_false(gtk_style_context_has_class(style,"adws-docked"));
    gtk_style_context_add_class(style,"adws-has-windows");drain(50);
    g_assert_true(gtk_style_context_has_class(style,"adws-docked"));
    gtk_style_context_remove_class(style,"adws-has-windows");drain(50);
    g_assert_false(gtk_style_context_has_class(style,"adws-docked"));
    g_assert_cmpuint(self->sync,==,0);
    wbcffi_deinit(self);
    gtk_widget_destroy(window);
    g_print("PASS: deferred release, reversal, hidden startup, teardown, idle cleanup\n");
}
