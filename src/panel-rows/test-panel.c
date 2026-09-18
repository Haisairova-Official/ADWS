#include "panel.c"

static GtkContainer *test_root(wbcffi_module *module) { return GTK_CONTAINER(module); }

static void settle(void) {
    for (int i = 0; i < 40; i++) {
        while (gtk_events_pending()) gtk_main_iteration();
        g_usleep(5000);
    }
}

int main(int argc, char **argv) {
    gtk_init(&argc, &argv);
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
    gtk_style_context_remove_provider_for_screen(gdk_screen_get_default(), GTK_STYLE_PROVIDER(palette));
    g_object_unref(palette);
    wbcffi_deinit(p);
    settle();
    gtk_widget_destroy(window);
    g_object_unref(css);
    g_print("Native panel checks passed\n");
    return 0;
}
