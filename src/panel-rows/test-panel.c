#include "panel.c"

static GtkContainer *test_root(wbcffi_module *module) { return GTK_CONTAINER(module); }

static void settle(void) {
    for (int i = 0; i < 40; i++) {
        int iterations = 0;
        while (gtk_events_pending()) {
            g_assert_cmpint(++iterations, <, 2000);
            gtk_main_iteration();
        }
        g_usleep(5000);
    }
}

static void cancel_hover_timer(Panel *p) {
    if (p->hover_source) g_source_remove(p->hover_source);
    p->hover_source = 0;
}

static void animate_for(int milliseconds) {
    gint64 end = g_get_monotonic_time() + milliseconds * 1000;
    do {
        int iterations = 0;
        while (gtk_events_pending()) {
            g_assert_cmpint(++iterations, <, 2000);
            gtk_main_iteration();
        }
        g_usleep(1000);
    } while (g_get_monotonic_time() < end);
}

static void test_motion(Panel *p) {
    g_assert_false(p->animations);
    enable_motion(p);
    configure_controls(p);
    animate_for(MNWS_MOTION_DURATION_US / 1000 + 80);
    MnwsMotion *left = (MnwsMotion *)p->previous_motion;
    MnwsMotion *lyrics = (MnwsMotion *)gtk_widget_get_parent(p->box);
    g_assert_cmpfloat(left->width, ==, 0.);
    g_assert_cmpuint(left->tick, ==, 0);
    show_controls(p, TRUE);
    cancel_hover_timer(p);
    animate_for(65);
    g_assert_cmpuint(left->tick, >, 0);
    g_assert_cmpfloat(left->width, >, 0.);
    g_assert_cmpfloat(left->width, <, left->target_width);
    g_assert_cmpfloat(gtk_widget_get_opacity(p->previous_button), >, 0.);
    g_assert_cmpfloat(gtk_widget_get_opacity(p->previous_button), <, 1.);
    // Reverse in flight without snapping to either endpoint.
    double visible_width = left->width;
    show_controls(p, FALSE);
    g_assert_cmpfloat(left->width, >=, visible_width);
    animate_for(65);
    g_assert_cmpfloat(left->width, <, visible_width);
    show_controls(p, TRUE);
    animate_for(MNWS_MOTION_DURATION_US / 1000 + 80);
    g_assert_cmpuint(left->tick, ==, 0);
    g_assert_cmpfloat(left->width, ==, left->target_width);
    GdkPixbuf *animated_shot = gtk_offscreen_window_get_pixbuf(GTK_OFFSCREEN_WINDOW(gtk_widget_get_toplevel(p->event_box)));
    gdk_pixbuf_save(animated_shot, "/tmp/mnws-animated-controls.png", "png", NULL, NULL);
    g_object_unref(animated_shot);
    double old_width = lyrics->width;
    update(p, "{\"primary\":\"Short\",\"secondary\":\"\"}");
    animate_for(65);
    g_assert_cmpfloat(lyrics->width, <, old_width);
    g_assert_cmpfloat(lyrics->width, >, lyrics->target_width);
    animate_for(MNWS_MOTION_DURATION_US / 1000 + 80);
    g_assert_cmpuint(lyrics->tick, ==, 0);
    g_assert_cmpfloat(lyrics->width, ==, lyrics->target_width);
    GdkRectangle bounds = {0, 0, 400, 36};
    g_assert_false(hover_step(p, &bounds, 200, 18, FALSE));
    cancel_hover_timer(p);
    animate_for(MNWS_MOTION_DURATION_US / 1000 + 80);
    g_assert_cmpuint(left->tick, ==, 0);
    g_assert_cmpfloat(left->width, ==, 0.);
    g_assert_false(gtk_widget_get_visible(p->previous_button));
    g_assert_false(gtk_widget_get_visible(p->next_button));
    // System-wide reduced motion still takes precedence over this opt-in.
    GtkSettings *settings = gtk_widget_get_settings(p->event_box);
    gboolean was_enabled;
    g_object_get(settings, "gtk-enable-animations", &was_enabled, NULL);
    g_object_set(settings, "gtk-enable-animations", FALSE, NULL);
    show_controls(p, TRUE);
    g_assert_cmpuint(left->tick, ==, 0);
    g_assert_cmpfloat(left->width, ==, left->target_width);
    show_controls(p, FALSE);
    g_assert_false(gtk_widget_get_visible(p->previous_button));
    g_object_set(settings, "gtk-enable-animations", was_enabled, NULL);
    // Unmapping midway through a transition must cancel its frame callback.
    show_controls(p, TRUE);
    gtk_widget_hide(p->event_box);
    g_assert_cmpuint(left->tick, ==, 0);
    g_print("Animation checks passed (fade, resize, reversal, leave, reduced motion, cleanup)\n");
}

static void crossing_during_map(GtkWidget *widget, GParamSpec *spec, gpointer data) {
    (void)widget; (void)spec;
    Panel *p = data;
    // Mapping/unmapping a child can synchronously emit leave/enter on its parent.
    GdkEventCrossing event = { .type = GDK_LEAVE_NOTIFY, .detail = GDK_NOTIFY_NONLINEAR };
    panel_crossing(p->event_box, &event, p);
    event.type = GDK_ENTER_NOTIFY;
    panel_crossing(p->event_box, &event, p);
}

static void test_hover_enter(Panel *p) {
    GdkEventCrossing event = { .type = GDK_ENTER_NOTIFY, .detail = GDK_NOTIFY_NONLINEAR };
    gboolean before = p->controls_visible;
    panel_crossing(p->event_box, &event, p);
    g_assert_cmpint(p->controls_visible, ==, before);
    g_assert_cmpuint(p->hover_source, >, 0);
    GdkRectangle bounds = {0, 0, 400, 36};
    hover_step(p, &bounds, 200, 18, TRUE);
    cancel_hover_timer(p);
    settle();
    g_assert_true(p->controls_visible);
}

static void test_hover_leave(Panel *p) {
    GdkEventCrossing event = { .type = GDK_LEAVE_NOTIFY, .detail = GDK_NOTIFY_NONLINEAR };
    panel_crossing(p->event_box, &event, p);
    g_assert_true(p->controls_visible);
    GdkRectangle moved = {100, 0, 500, 36};
    // Width changes must not dismiss the controls under a stationary pointer.
    g_assert_true(hover_step(p, &moved, 20, 18, TRUE));
    g_assert_true(p->controls_visible);
    g_assert_true(hover_step(p, &moved, -100, -100, TRUE));
    g_assert_false(hover_step(p, &moved, -100, -100, TRUE));
    cancel_hover_timer(p);
    settle();
    g_assert_false(p->controls_visible);
}

int main(int argc, char **argv) {
    gtk_init(&argc, &argv);
    if (g_getenv("MNWS_TEST_STYLE")) {
        GtkCssProvider *live = gtk_css_provider_new();
        GError *error = NULL;
        g_assert_true(gtk_css_provider_load_from_path(live, g_getenv("MNWS_TEST_STYLE"), &error));
        gtk_style_context_add_provider_for_screen(gdk_screen_get_default(), GTK_STYLE_PROVIDER(live), GTK_STYLE_PROVIDER_PRIORITY_USER);
        g_object_unref(live);
    }
    MnwsStart *image_start = g_object_new(mnws_start_get_type(), NULL);
    g_object_ref_sink(image_start);
    image_start->normal = gdk_pixbuf_new(GDK_COLORSPACE_RGB, TRUE, 8, 400, 100);
    image_start->hover = gdk_pixbuf_new(GDK_COLORSPACE_RGB, TRUE, 8, 400, 100);
    image_start->label = g_strdup("Apps");
    int image_width, image_height;
    start_metrics(GTK_WIDGET(image_start), 40, &image_width, &image_height);
    g_assert_cmpint(image_width, ==, image_height * 4);
    start_metrics(GTK_WIDGET(image_start), 80, &image_width, &image_height);
    g_assert_cmpint(image_width, ==, image_height * 4);
    GdkEventCrossing crossing = { .type = GDK_ENTER_NOTIFY };
    start_crossing(GTK_WIDGET(image_start), &crossing);
    g_assert_true(image_start->inside);
    crossing.type = GDK_LEAVE_NOTIFY;
    start_crossing(GTK_WIDGET(image_start), &crossing);
    g_assert_false(image_start->inside);
    gdk_pixbuf_fill(image_start->normal, 0xff0000ff);
    gdk_pixbuf_fill(image_start->hover, 0x0000ffff);
    GtkWidget *start_window = gtk_offscreen_window_new();
    gtk_widget_set_size_request(start_window, -1, 40);
    gtk_container_add(GTK_CONTAINER(start_window), GTK_WIDGET(image_start));
    gtk_widget_show_all(start_window);
    settle();
    GdkPixbuf *shot = gtk_offscreen_window_get_pixbuf(GTK_OFFSCREEN_WINDOW(start_window));
    g_assert_nonnull(shot);
    guchar *pixel = gdk_pixbuf_get_pixels(shot) + gdk_pixbuf_get_height(shot)/2 * gdk_pixbuf_get_rowstride(shot)
        + gdk_pixbuf_get_width(shot)/2 * gdk_pixbuf_get_n_channels(shot);
    g_assert_cmpint(pixel[0], ==, 255);
    g_object_unref(shot);
    crossing.type = GDK_ENTER_NOTIFY;
    start_crossing(GTK_WIDGET(image_start), &crossing);
    settle();
    shot = gtk_offscreen_window_get_pixbuf(GTK_OFFSCREEN_WINDOW(start_window));
    pixel = gdk_pixbuf_get_pixels(shot) + gdk_pixbuf_get_height(shot)/2 * gdk_pixbuf_get_rowstride(shot)
        + gdk_pixbuf_get_width(shot)/2 * gdk_pixbuf_get_n_channels(shot);
    g_assert_cmpint(pixel[2], ==, 255);
    g_assert_cmpint(pixel[0], ==, 0);
    g_object_unref(shot);
    g_assert_true(gtk_widget_get_events(GTK_WIDGET(image_start)) & GDK_BUTTON_PRESS_MASK);
    gchar *click_dir = g_dir_make_tmp("mnws-click-XXXXXX", NULL);
    gchar *click_file = g_build_filename(click_dir, "activated", NULL);
    gchar *quoted = g_shell_quote(click_file);
    image_start->command = g_strdup_printf("printf x >> %s", quoted);
    g_free(quoted);
    GdkEvent *click = gdk_event_new(GDK_BUTTON_PRESS);
    click->button.window = g_object_ref(gtk_widget_get_window(GTK_WIDGET(image_start)));
    click->button.button = 1; click->button.x = 5; click->button.y = 5;
    gtk_widget_event(GTK_WIDGET(image_start), click);
    click->type = GDK_BUTTON_RELEASE;
    gtk_widget_event(GTK_WIDGET(image_start), click);
    settle();
    gchar *activated = NULL;
    g_assert_true(g_file_get_contents(click_file, &activated, NULL, NULL));
    g_assert_cmpstr(activated, ==, "x");
    g_free(activated);
    // A stray release, or dragging outside after pressing, must not launch again.
    gtk_widget_event(GTK_WIDGET(image_start), click);
    click->type = GDK_BUTTON_PRESS;
    gtk_widget_event(GTK_WIDGET(image_start), click);
    click->type = GDK_BUTTON_RELEASE; click->button.x = -5;
    gtk_widget_event(GTK_WIDGET(image_start), click);
    settle();
    g_assert_true(g_file_get_contents(click_file, &activated, NULL, NULL));
    g_assert_cmpstr(activated, ==, "x");
    g_free(activated);
    // Image mode must run the configured right-click action, not an invented menu.
    quoted = g_shell_quote(click_file);
    image_start->right_command = g_strdup_printf("printf r >> %s", quoted);
    image_start->middle_command = g_strdup_printf("printf m >> %s", quoted);
    g_free(quoted);
    for (guint button = 3; button >= 2; button--) {
        click->type = GDK_BUTTON_PRESS; click->button.button = button; click->button.x = 5;
        g_assert_true(gtk_widget_event(GTK_WIDGET(image_start), click));
        click->type = GDK_BUTTON_RELEASE;
        gtk_widget_event(GTK_WIDGET(image_start), click);
        settle();
    }
    g_assert_true(g_file_get_contents(click_file, &activated, NULL, NULL));
    g_assert_cmpstr(activated, ==, "xrm");
    g_free(activated); gdk_event_free(click);
    unlink(click_file); rmdir(click_dir); g_free(click_file); g_free(click_dir);
    gtk_widget_destroy(start_window);
    g_clear_object(&image_start->normal);
    image_start->normal = gdk_pixbuf_new(GDK_COLORSPACE_RGB, TRUE, 8, 1, 100);
    start_metrics(GTK_WIDGET(image_start), 40, &image_width, &image_height);
    g_assert_cmpint(image_width, >, 1);
    g_object_unref(image_start);
    gchar *decoded = config_string("\"/usr/bin/python3 '/path with spaces/main.py' --output-json\"");
    gchar **parsed = NULL;
    g_assert(g_shell_parse_argv(decoded, NULL, &parsed, NULL));
    g_assert_cmpstr(parsed[0], ==, "/usr/bin/python3");
    g_assert_cmpstr(parsed[1], ==, "/path with spaces/main.py");
    g_strfreev(parsed);
    g_free(decoded);
    GtkCssProvider *css = gtk_css_provider_new();
    GError *error = NULL;
    g_assert(gtk_css_provider_load_from_path(css, "../../config/waybar/style-bottom.css", &error));
    gtk_style_context_add_provider_for_screen(gdk_screen_get_default(), GTK_STYLE_PROVIDER(css), GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
    GtkWidget *window = gtk_offscreen_window_new();
    GtkWidget *root = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_container_add(GTK_CONTAINER(window), root);
    wbcffi_init_info info = {.obj = (wbcffi_module *)root, .get_root_widget = test_root};
    wbcffi_config_entry entries[] = {
        {"exec", "\"/usr/bin/sleep 30\""},
        {"widget_name", "\"custom-mnws-org-mnws-neteaselyrics\""},
        {"width", "420"}, {"font_family", "\"Sans\""},
        {"primary_color", "\"#ff0000\""}, {"secondary_color", "\"#00ff00\""},
        {"separator_color", "\"#0000ff\""},
    };
    Panel *p = wbcffi_init(&info, entries, G_N_ELEMENTS(entries));
    g_assert_cmpstr(p->font_family, ==, "Sans");
    g_assert(p->has_color[0] && p->has_color[1]);
    gtk_widget_set_size_request(window, -1, 36);
    gtk_widget_show_all(window);
    g_assert_true(gtk_widget_get_events(p->event_box) & GDK_BUTTON_RELEASE_MASK);
    gchar *settings_dir = g_dir_make_tmp("mnws-settings-click-XXXXXX", NULL);
    gchar *settings_file = g_build_filename(settings_dir, "opened", NULL);
    gchar *settings_quoted = g_shell_quote(settings_file);
    p->right_command = g_strdup_printf("touch %s", settings_quoted);
    g_free(settings_quoted);
    GdkEvent *settings_click = gdk_event_new(GDK_BUTTON_PRESS);
    settings_click->button.window = g_object_ref(gtk_widget_get_window(p->event_box));
    settings_click->button.button = 3;
    settings_click->button.x = settings_click->button.y = 5;
    g_assert_true(gtk_widget_event(p->event_box, settings_click));
    settings_click->type = GDK_BUTTON_RELEASE;
    g_assert_true(gtk_widget_event(p->event_box, settings_click));
    settle();
    g_assert_true(g_file_test(settings_file, G_FILE_TEST_EXISTS));
    gdk_event_free(settings_click);
    unlink(settings_file); rmdir(settings_dir);
    g_free(settings_file); g_free(settings_dir);
    gchar *control_dir = g_dir_make_tmp("mnws-controls-XXXXXX", NULL);
    gchar *pause_file = g_build_filename(control_dir, "pause", NULL);
    gchar *previous_file = g_build_filename(control_dir, "previous", NULL);
    gchar *next_file = g_build_filename(control_dir, "next", NULL);
    gchar *pause_quoted = g_shell_quote(pause_file);
    gchar *previous_quoted = g_shell_quote(previous_file);
    gchar *next_quoted = g_shell_quote(next_file);
    p->left_command = g_strdup_printf("touch %s", pause_quoted);
    p->previous_command = g_strdup_printf("touch %s", previous_quoted);
    p->next_command = g_strdup_printf("touch %s", next_quoted);
    g_free(pause_quoted); g_free(previous_quoted); g_free(next_quoted);
    configure_controls(p);
    g_signal_connect(p->previous_button, "notify::visible", G_CALLBACK(crossing_during_map), p);
    test_hover_enter(p);
    gtk_button_clicked(GTK_BUTTON(p->previous_button));
    gtk_button_clicked(GTK_BUTTON(p->next_button));
    GdkEvent *pause_click = gdk_event_new(GDK_BUTTON_PRESS);
    pause_click->button.window = g_object_ref(gtk_widget_get_window(p->event_box));
    pause_click->button.button = 1;
    pause_click->button.x = pause_click->button.y = 5;
    g_assert_true(gtk_widget_event(p->event_box, pause_click));
    pause_click->type = GDK_BUTTON_RELEASE;
    g_assert_true(gtk_widget_event(p->event_box, pause_click));
    settle();
    g_assert_true(g_file_test(pause_file, G_FILE_TEST_EXISTS));
    g_assert_true(g_file_test(previous_file, G_FILE_TEST_EXISTS));
    g_assert_true(g_file_test(next_file, G_FILE_TEST_EXISTS));
    test_hover_leave(p);
    gdk_event_free(pause_click);
    unlink(pause_file); unlink(previous_file); unlink(next_file); rmdir(control_dir);
    g_free(pause_file); g_free(previous_file); g_free(next_file); g_free(control_dir);
    update(p, "{\"primary\":\"原文の歌詞がここに表示されます\",\"secondary\":\"这里显示对应的中文翻译\",\"class\":\"ready\"}");
    settle();
    int width = gtk_widget_get_allocated_width(window);
    int height = gtk_widget_get_allocated_height(window);
    g_print("Bilingual size: %d x %d; rows: %d / %d; separator visible: %d\n", width, height,
        gtk_widget_get_allocated_height(p->primary), gtk_widget_get_allocated_height(p->secondary), gtk_widget_get_visible(p->separator));
    g_assert_cmpint(height, <=, 36);
    g_assert(gtk_widget_get_visible(p->separator));
    update(p, "{\"primary\":\"Plugin failed\",\"secondary\":\"\",\"class\":\"error\"}");
    g_assert_cmpstr(gtk_label_get_text(GTK_LABEL(p->primary)), ==, "原文の歌詞がここに表示されます");
    g_assert(gtk_widget_get_visible(p->secondary));
    g_assert(gtk_widget_get_visible(p->separator));
    g_assert_cmpfloat(gtk_label_get_xalign(GTK_LABEL(p->primary)), ==, 0.5);
    g_assert_cmpfloat(gtk_label_get_xalign(GTK_LABEL(p->secondary)), ==, 0.5);
    PangoAttrIterator *attrs = pango_attr_list_get_iterator(gtk_label_get_attributes(GTK_LABEL(p->primary)));
    PangoAttrColor *foreground = (PangoAttrColor *)pango_attr_iterator_get(attrs, PANGO_ATTR_FOREGROUND);
    g_assert(foreground && foreground->color.red == 65535 && foreground->color.green == 0);
    pango_attr_iterator_destroy(attrs);
    GdkPixbuf *image = gtk_offscreen_window_get_pixbuf(GTK_OFFSCREEN_WINDOW(window));
    gdk_pixbuf_save(image, "/tmp/mnws-bilingual-preview.png", "png", NULL, NULL);
    g_object_unref(image);
    int previous_unit = p->font_unit;
    int heights[] = {54, 72, 30, 36};
    for (guint i = 0; i < G_N_ELEMENTS(heights); i++) {
        gtk_widget_set_size_request(window, -1, heights[i]);
        gtk_window_resize(GTK_WINDOW(window), width, heights[i]);
        settle();
        int allocated = gtk_widget_get_allocated_height(window);
        g_print("Resize: height=%d font unit=%d primary=%g secondary=%g\n", allocated,
            p->font_unit, p->font_unit * 3.0 / PANGO_SCALE, p->font_unit * 2.0 / PANGO_SCALE);
        g_assert_cmpint(allocated, ==, heights[i]);
        g_assert_cmpint(gtk_widget_get_allocated_height(p->primary) +
            gtk_widget_get_allocated_height(p->secondary) +
            gtk_widget_get_allocated_height(p->separator), <=, heights[i]);
        if (i < 2) g_assert_cmpint(p->font_unit, >, previous_unit);
        if (i == 2) g_assert_cmpint(p->font_unit, <, previous_unit);
        previous_unit = p->font_unit;
    }
    update(p, "{\"primary\":\"一行だけ\",\"secondary\":\"\",\"class\":\"paused\"}");
    settle();
    g_assert(!gtk_widget_get_visible(p->separator));
    g_assert(!gtk_widget_get_visible(p->secondary));
    g_assert_cmpint(gtk_widget_get_allocated_width(window), ==, width);
    update(p, "{\"primary\":\"This is a very long original lyric that must ellipsize instead of expanding the panel beyond its fixed width\",\"secondary\":\"这是一句很长很长很长很长很长很长很长很长很长的翻译文本，不应该让任务栏变宽\"}");
    settle();
    g_assert_cmpint(gtk_widget_get_allocated_width(window), ==, width);
    g_assert_cmpint(gtk_widget_get_allocated_height(window), <=, 36);
    GtkWidget *dynamic_window = gtk_offscreen_window_new();
    GtkWidget *dynamic_root = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_container_add(GTK_CONTAINER(dynamic_window), dynamic_root);
    Panel *dynamic = create_widgets(GTK_CONTAINER(dynamic_root), "dynamic-plugin", 0);
    gtk_widget_set_size_request(dynamic_window, -1, 36);
    gtk_widget_show_all(dynamic_window);
    update(dynamic, "{\"primary\":\"短\",\"secondary\":\"\"}");
    settle();
    int short_width = gtk_widget_get_allocated_width(dynamic_window);
    update(dynamic, "{\"primary\":\"Width follows the current lyrics\",\"secondary\":\"\"}");
    settle();
    g_assert_cmpint(gtk_widget_get_allocated_width(dynamic_window), >, short_width);
    int lyrics_width = gtk_widget_get_allocated_width(dynamic_window);
    dynamic->previous_command = g_strdup("true");
    dynamic->next_command = g_strdup("true");
    configure_controls(dynamic);
    test_hover_enter(dynamic);
    g_assert_cmpint(gtk_widget_get_allocated_width(dynamic_window), >, lyrics_width);
    g_assert_false(gtk_widget_compute_expand(dynamic->event_box, GTK_ORIENTATION_HORIZONTAL));
    GtkAllocation previous, middle, next;
    gtk_widget_get_allocation(dynamic->previous_button, &previous);
    gtk_widget_get_allocation(dynamic->box, &middle);
    gtk_widget_get_allocation(dynamic->next_button, &next);
    g_assert_cmpint(previous.x + previous.width, <=, middle.x);
    g_assert_cmpint(middle.x + middle.width, <=, next.x);
    g_assert_cmpint(gtk_widget_get_allocated_width(dynamic_window), ==,
                   lyrics_width + previous.width + next.width);
    g_assert_cmpint(gtk_widget_get_allocated_height(dynamic_window), ==, 36);
    GdkPixbuf *controls_shot = gtk_offscreen_window_get_pixbuf(GTK_OFFSCREEN_WINDOW(dynamic_window));
    gdk_pixbuf_save(controls_shot, "/tmp/mnws-hover-symbols.png", "png", NULL, NULL);
    g_object_unref(controls_shot);
    test_hover_leave(dynamic);
    test_hover_enter(dynamic);
    GdkRectangle stale_bounds = {0, 0, 400, 36};
    // Leaving the Wayland surface may retain exactly the last hover coordinates.
    g_assert_false(hover_step(dynamic, &stale_bounds, 200, 18, FALSE));
    g_assert_false(dynamic->controls_visible);
    g_assert_false(dynamic->hover_anchor_valid);
    cancel_hover_timer(dynamic);
    settle();
    // Offscreen windows can retain their last allocation; requisition must shrink.
    int minimum, natural;
    gtk_widget_get_preferred_width(dynamic->event_box, &minimum, &natural);
    g_assert_cmpint(natural, ==, lyrics_width);
    test_motion(dynamic);
    dynamic->disposed = TRUE;
    ((MnwsRows *)dynamic->box)->panel = NULL;
    gtk_widget_destroy(dynamic_window);
    panel_unref(dynamic);
    p->has_color[0] = p->has_color[1] = FALSE;
    p->has_separator_color = FALSE;
    const char *palettes[] = {
        "@define-color theme_bg_color #181818; @define-color accent_color #80bfff; .mnws-rows {color: #eeeeee;}",
        "@define-color theme_bg_color #ffffff; @define-color accent_color #2255aa; .mnws-rows {color: #111111;}",
        "@define-color theme_bg_color #ffffff; @define-color accent_color #111111; .mnws-rows {color: #111111;}"
    };
    GtkCssProvider *palette = gtk_css_provider_new();
    gtk_style_context_add_provider_for_screen(gdk_screen_get_default(), GTK_STYLE_PROVIDER(palette), GTK_STYLE_PROVIDER_PRIORITY_USER + 1);
    for (guint i=0; i<G_N_ELEMENTS(palettes); i++) {
        gtk_css_provider_load_from_data(palette, palettes[i], -1, NULL);
        settle();
        GdkRGBA first = theme_color(p, 0), second = theme_color(p, 1), line = theme_color(p, 2);
        g_assert_cmpfloat(color_distance(first, second), >, .01);
        g_assert_cmpfloat(color_distance(second, line), >, .01);
        PangoAttrIterator *it = pango_attr_list_get_iterator(gtk_label_get_attributes(GTK_LABEL(p->primary)));
        PangoAttrColor *actual = (PangoAttrColor *)pango_attr_iterator_get(it, PANGO_ATTR_FOREGROUND);
        g_assert(actual != NULL);
        g_assert_cmpint(actual->color.red, ==, (guint16)(first.red*65535));
        pango_attr_iterator_destroy(it);
    }
    // Named palette changes can leave the parent's computed foreground unchanged.
    const char *named_palettes[] = {
        "@define-color surface_container_high #101820; @define-color primary #55bbdd; @define-color outline #777777; .mnws-rows {color: #eeeeee;}",
        "@define-color surface_container_high #101820; @define-color primary #dd9955; @define-color outline #669977; .mnws-rows {color: #eeeeee;}"
    };
    for (guint i=0; i<G_N_ELEMENTS(named_palettes); i++) {
        gtk_css_provider_load_from_data(palette, named_palettes[i], -1, NULL);
        settle();
        GdkRGBA wanted = theme_color(p, 1);
        PangoAttrIterator *it = pango_attr_list_get_iterator(gtk_label_get_attributes(GTK_LABEL(p->secondary)));
        PangoAttrColor *actual = (PangoAttrColor *)pango_attr_iterator_get(it, PANGO_ATTR_FOREGROUND);
        g_assert_cmpint(actual->color.red, ==, (guint16)(wanted.red*65535));
        g_assert_cmpint(actual->color.blue, ==, (guint16)(wanted.blue*65535));
        pango_attr_iterator_destroy(it);
        g_assert_cmpfloat(color_distance(p->separator_color, wanted), >, .04);
        g_assert_cmpuint(p->refresh_source, ==, 0);
    }
    gtk_style_context_remove_provider_for_screen(gdk_screen_get_default(), GTK_STYLE_PROVIDER(palette));
    g_object_unref(palette);
    enable_motion(p);
    configure_controls(p);
    animate_for(MNWS_MOTION_DURATION_US / 1000 + 80);
    for (int i = 0; i < 20; i++) {
        show_controls(p, i % 2 == 0);
        cancel_hover_timer(p);
        animate_for(8);
    }
    show_controls(p, FALSE);
    animate_for(MNWS_MOTION_DURATION_US / 1000 + 80);
    gtk_widget_get_preferred_width(p->event_box, &minimum, &natural);
    g_assert_cmpint(natural, ==, 420);
    g_assert_cmpuint(((MnwsMotion *)p->previous_motion)->tick, ==, 0);
    g_assert_cmpuint(((MnwsMotion *)p->next_motion)->tick, ==, 0);
    g_assert_false(gtk_widget_get_visible(p->previous_button));
    g_assert_cmpint(gtk_widget_get_allocated_height(window), ==, 36);
    wbcffi_deinit(p);
    settle();
    gtk_widget_destroy(window);
    g_object_unref(css);
    g_print("Native panel checks passed\n");
    return 0;
}
