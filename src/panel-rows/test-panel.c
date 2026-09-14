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
