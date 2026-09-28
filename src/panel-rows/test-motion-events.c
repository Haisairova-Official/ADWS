/* Real crossing-event regression, run only on an isolated Xvfb display. */
#include "panel.c"

static GtkContainer *test_root(wbcffi_module *module) { return GTK_CONTAINER(module); }

static void pump(int ms) {
    gint64 end = g_get_monotonic_time() + ms * 1000;
    do {
        int count = 0;
        while (gtk_events_pending()) {
            g_assert_cmpint(++count, <, 2000);
            gtk_main_iteration();
        }
        g_usleep(1000);
    } while (g_get_monotonic_time() < end);
}

static void pointer_at(GtkWidget *window, int x, int y) {
    GdkDisplay *display = gtk_widget_get_display(window);
    GdkDevice *pointer = gdk_seat_get_pointer(gdk_display_get_default_seat(display));
    int ox, oy;
    gdk_window_get_origin(gtk_widget_get_window(window), &ox, &oy);
    G_GNUC_BEGIN_IGNORE_DEPRECATIONS
    gdk_device_warp(pointer, gtk_widget_get_screen(window), ox + x, oy + y);
    G_GNUC_END_IGNORE_DEPRECATIONS
    gdk_display_sync(display);
    pump(400);
}

static void test_crossing(gboolean animated, int width) {
    GtkWidget *window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_move(GTK_WINDOW(window), 100, 100);
    GtkWidget *root = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_container_add(GTK_CONTAINER(window), root);
    wbcffi_init_info info = {.obj = (wbcffi_module *)root, .get_root_widget = test_root};
    gchar *width_json = g_strdup_printf("%d\n", width);
    wbcffi_config_entry entries[] = {
        {"exec", "\"/usr/bin/sleep 30\"\n"},
        {"widget_name", "\"animated-crossing-test\"\n"},
        {"width", width_json},
        {"animations", animated ? "true\n" : "false\n"},
        {"previous_command", "\"true\"\n"},
        {"next_command", "\"true\"\n"},
    };
    Panel *p = wbcffi_init(&info, entries, G_N_ELEMENTS(entries));
    g_free(width_json);
    g_assert_cmpint(p->animations, ==, animated);
    update(p, "{\"primary\":\"Pointer crossing regression test\",\"secondary\":\"\"}");
    gtk_widget_set_size_request(window, -1, 36);
    gtk_widget_show_all(window);
    pump(300);
    pointer_at(window, 20, -30);
    g_assert_false(p->controls_visible);
    pointer_at(window, gtk_widget_get_allocated_width(window)/2, 18);
    g_assert_true(p->controls_visible);
    g_assert_true(gtk_widget_get_visible(p->previous_button));
    g_assert_true(gtk_widget_get_visible(p->next_button));
    g_assert_cmpfloat(gtk_widget_get_opacity(p->previous_button), ==, 1.);
    GtkWidget *buttons[] = {p->previous_button, p->next_button};
    for (guint i = 0; i < G_N_ELEMENTS(buttons); i++) {
        int x, y;
        g_assert_true(gtk_widget_translate_coordinates(buttons[i], window,
            gtk_widget_get_allocated_width(buttons[i])/2, 18, &x, &y));
        pointer_at(window, x, y);
        g_assert_true(p->controls_visible);
    }
    pointer_at(window, 20, -30);
    g_assert_false(p->controls_visible);
    g_assert_false(gtk_widget_get_visible(p->previous_button));
    g_assert_false(gtk_widget_get_visible(p->next_button));
    wbcffi_deinit(p);
    gtk_widget_destroy(window);
    g_print("Real crossing events passed (animation=%d width=%d)\n", animated, width);
}

/* Assert real allocations and the moving left edge, not just interpolated fields. */
static void check_width_transition(Panel *p, int before, gboolean growing, int edge) {
    int last = before, steps = 0;
    for (int i = 0; i < 40; i++) {
        pump(10);
        int width = gtk_widget_get_allocated_width(p->event_box);
        int x, y;
        gtk_widget_translate_coordinates(p->event_box, gtk_widget_get_toplevel(p->event_box), 0, 0, &x, &y);
        g_assert_cmpint(ABS(x + width - edge), <=, 1);
        if (growing) g_assert_cmpint(width, >=, last);
        else g_assert_cmpint(width, <=, last);
        if (width != last) steps++;
        last = width;
    }
    g_assert_cmpint(steps, >=, 5);
    g_assert_cmpint(last, !=, before);
    g_print("Actual width transition: %d -> %d in %d rendered steps\n", before, last, steps);
}

static void test_width_allocations(void) {
    GtkWidget *window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_default_size(GTK_WINDOW(window), 1200, 36);
    GtkWidget *bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_container_add(GTK_CONTAINER(window), bar);
    GtkWidget *root = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_box_pack_end(GTK_BOX(bar), root, FALSE, FALSE, 0);
    gtk_box_set_center_widget(GTK_BOX(bar), gtk_label_new("center"));
    Panel *p = create_widgets(GTK_CONTAINER(root), "width-transition-test", 0);
    p->previous_command = g_strdup("true");
    p->next_command = g_strdup("true");
    enable_motion(p);
    configure_controls(p);
    update(p, "{\"primary\":\"Short\"}");
    gtk_widget_show_all(window);
    pump(400);
    int initial = gtk_widget_get_allocated_width(p->event_box);
    int x, y;
    gtk_widget_translate_coordinates(p->event_box, window, 0, 0, &x, &y);
    int edge = x + initial;
    update(p, "{\"primary\":\"A substantially longer line of lyrics to test the actual width\"}");
    check_width_transition(p, initial, TRUE, edge);
    int wide = gtk_widget_get_allocated_width(p->event_box);
    update(p, "{\"primary\":\"Short\"}");
    check_width_transition(p, wide, FALSE, edge);
    g_assert_cmpint(gtk_widget_get_allocated_width(p->event_box), ==, initial);
    show_controls(p, TRUE);
    check_width_transition(p, initial, TRUE, edge);
    wide = gtk_widget_get_allocated_width(p->event_box);
    show_controls(p, FALSE);
    check_width_transition(p, wide, FALSE, edge);
    g_assert_cmpint(gtk_widget_get_allocated_width(p->event_box), ==, initial);
    g_assert_cmpfloat(motion_ease(0.), ==, 0.);
    g_assert_cmpfloat(motion_ease(1.), ==, 1.);
    g_assert_cmpfloat(motion_ease(16667. / ADWS_MOTION_DURATION_US), <, .03);
    wbcffi_deinit(p);
    gtk_widget_destroy(window);
}

int main(int argc, char **argv) {
    gtk_init(&argc, &argv);
    g_assert_true(config_boolean("true"));
    g_assert_true(config_boolean(" \ntrue\r\n\t"));
    g_assert_false(config_boolean("false\n"));
    g_assert_false(config_boolean("\"true\"\n"));
    g_assert_false(config_boolean("1\n"));
    g_assert_false(config_boolean("null\n"));
    g_assert_false(config_boolean("invalid"));
    test_width_allocations();
    test_crossing(TRUE, 0);
    test_crossing(TRUE, 420);
    test_crossing(FALSE, 0);
    test_crossing(FALSE, 420);
    return 0;
}
