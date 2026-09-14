#include <signal.h>
#include "../mnws-i18n.h"
/* Waybar CFFI v2 renderer for panel.rows-v1: primary / separator / secondary. */
#include <gtk/gtk.h>
#include <json-glib/json-glib.h>

typedef struct wbcffi_module wbcffi_module;
typedef struct {
    wbcffi_module *obj;
    const char *waybar_version;
    GtkContainer *(*get_root_widget)(wbcffi_module *);
    void (*queue_update)(wbcffi_module *);
} wbcffi_init_info;
typedef struct { const char *key, *value; } wbcffi_config_entry;

typedef struct {
    gint refs;
    gboolean disposed;
    GtkWidget *box, *primary, *secondary, *separator;
    GSubprocess *process;
    GDataInputStream *stream;
    GCancellable *cancel;
    gchar *command, *state;
    guint retry;
    int font_unit;
    gchar *font_family;
    GdkRGBA colors[2];
    gboolean has_color[2];
    gboolean has_separator_color;
    GtkCssProvider *theme_separator;
    gchar *theme_separator_css;
} Panel;

typedef struct { GtkBox parent; Panel *panel; } MnwsRows;
typedef struct { GtkBoxClass parent; } MnwsRowsClass;
G_DEFINE_TYPE(MnwsRows, mnws_rows, GTK_TYPE_BOX)

static int measure(PangoLayout *layout, PangoFontDescription *font, int size) {
    pango_font_description_set_absolute_size(font, size);
    pango_layout_set_font_description(layout, font);
    int height;
    pango_layout_get_pixel_size(layout, NULL, &height);
    return height;
}

static GdkRGBA blend(GdkRGBA a, GdkRGBA b, double amount) {
    return (GdkRGBA){a.red * amount + b.red * (1-amount),
        a.green * amount + b.green * (1-amount),
        a.blue * amount + b.blue * (1-amount), 1};
}

static double color_distance(GdkRGBA a, GdkRGBA b) {
    double r=a.red-b.red, g=a.green-b.green, b1=a.blue-b.blue;
    return r*r+g*g+b1*b1;
}

static GdkRGBA theme_color(Panel *p, int index) {
    GtkStyleContext *context = gtk_widget_get_style_context(p->box);
    GdkRGBA foreground, background, accent;
    gtk_style_context_get_color(context, GTK_STATE_FLAG_NORMAL, &foreground);
    // Resolve theme roles, never a fixed application palette.
    background = foreground;
    if (!gtk_style_context_lookup_color(context, "theme_bg_color", &background))
        background = (GdkRGBA){1-foreground.red, 1-foreground.green, 1-foreground.blue, 1};
    accent = foreground;
    if (!gtk_style_context_lookup_color(context, "accent_color", &accent))
        gtk_style_context_lookup_color(context, "theme_selected_bg_color", &accent);
    if (color_distance(accent, background) < color_distance(foreground, background)*0.3)
        accent = blend(foreground, accent, .65);
    if (color_distance(accent, foreground) < .04)
        accent = blend(foreground, background, .72);
    if (index == 0) return foreground;
    if (index == 1) return accent;
    return blend(accent, background, .55);
}

static void font_size(Panel *p, GtkWidget *label, int size, int index) {
    PangoAttrList *attrs = pango_attr_list_new();
    pango_attr_list_insert(attrs, pango_attr_size_new_absolute(size));
    if (p->font_family && *p->font_family)
        pango_attr_list_insert(attrs, pango_attr_family_new(p->font_family));
    {
        GdkRGBA color = p->has_color[index] ? p->colors[index] : theme_color(p, index);
        pango_attr_list_insert(attrs, pango_attr_foreground_new(color.red * 65535, color.green * 65535, color.blue * 65535));
        pango_attr_list_insert(attrs, pango_attr_foreground_alpha_new(color.alpha * 65535));
    }
    gtk_label_set_attributes(GTK_LABEL(label), attrs);
    pango_attr_list_unref(attrs);
    if (!p->has_separator_color && index == 1) {
        GdkRGBA color = theme_color(p, 2);
        gchar *rgba = gdk_rgba_to_string(&color);
        gchar *css = g_strdup_printf("separator { background-color: %s; opacity: 1; }", rgba);
        if (g_strcmp0(css, p->theme_separator_css)) {
            gtk_css_provider_load_from_data(p->theme_separator, css, -1, NULL);
            g_free(p->theme_separator_css);
            p->theme_separator_css = g_strdup(css);
        }
        g_free(css); g_free(rgba);
    }
}

static void theme_changed(GtkWidget *widget, gpointer data) {
    Panel *p = data;
    if (p->disposed) return;
    p->font_unit = 0;
    gtk_widget_queue_resize(widget);
}

static void fit_height(Panel *p, int width, int height) {
    if (height <= 1) return;
    // Measure the active font, including CJK fallback, against the allocated bar
    // height. Font sizes are 3u and 2u; u is found rather than fixed in pixels.
    PangoLayout *layout = gtk_widget_create_pango_layout(p->primary, "Ag国語あいう");
    PangoFontDescription *font = pango_font_description_copy(
        pango_context_get_font_description(pango_layout_get_context(layout)));
    if (p->font_family && *p->font_family)
        pango_font_description_set_family(font, p->font_family);
    int thickness = MAX(1, (height + 18) / 36);
    int low = 1, high = height * PANGO_SCALE;
    while (low < high) {
        int middle = (low + high + 1) / 2;
        int used = measure(layout, font, middle * 3) + measure(layout, font, middle * 2) + thickness;
        if (used <= height) low = middle;
        else high = middle - 1;
    }
    if (p->font_unit != low) {
        p->font_unit = low;
        font_size(p, p->primary, low * 3, 0);
        font_size(p, p->secondary, low * 2, 1);
    }
    int old_height;
    gtk_widget_get_size_request(p->separator, NULL, &old_height);
    if (old_height != thickness) gtk_widget_set_size_request(p->separator, -1, thickness);
    int margin = width / 20;
    if (gtk_widget_get_margin_start(p->separator) != margin) {
        gtk_widget_set_margin_start(p->separator, margin);
        gtk_widget_set_margin_end(p->separator, margin);
    }
    pango_font_description_free(font);
    g_object_unref(layout);
}

static void rows_height(GtkWidget *widget, int *minimum, int *natural) {
    (void)widget;
    // The bar determines the height. Old font metrics must not prevent a shrink.
    *minimum = *natural = 0;
}
static void rows_height_for_width(GtkWidget *widget, int width, int *minimum, int *natural) {
    (void)width;
    rows_height(widget, minimum, natural);
}
static void rows_allocate(GtkWidget *widget, GtkAllocation *allocation) {
    Panel *p = ((MnwsRows *)widget)->panel;
    if (p && !p->disposed) fit_height(p, allocation->width, allocation->height);
    GTK_WIDGET_CLASS(mnws_rows_parent_class)->size_allocate(widget, allocation);
}
static void mnws_rows_class_init(MnwsRowsClass *klass) {
    GtkWidgetClass *widget = GTK_WIDGET_CLASS(klass);
    widget->get_preferred_height = rows_height;
    widget->get_preferred_height_for_width = rows_height_for_width;
    widget->size_allocate = rows_allocate;
}
static void mnws_rows_init(MnwsRows *rows) { (void)rows; }

static Panel *panel_ref(Panel *p) { p->refs++; return p; }
static void panel_unref(gpointer data) {
    Panel *p = data;
    if (--p->refs) return;
    g_clear_object(&p->stream);
    g_clear_object(&p->process);
    g_clear_object(&p->cancel);
    g_free(p->command);
    g_free(p->state);
    g_free(p->font_family);
    g_clear_object(&p->theme_separator);
    g_free(p->theme_separator_css);
    g_free(p);
}

static const char *string_member(JsonObject *obj, const char *name) {
    JsonNode *node = json_object_get_member(obj, name);
    return node && JSON_NODE_HOLDS_VALUE(node) && json_node_get_value_type(node) == G_TYPE_STRING
        ? json_node_get_string(node) : "";
}

static void update(Panel *p, const char *line) {
    JsonParser *parser = json_parser_new();
    if (!json_parser_load_from_data(parser, line, -1, NULL)) { g_object_unref(parser); return; }
    JsonNode *root = json_parser_get_root(parser);
    if (!JSON_NODE_HOLDS_OBJECT(root)) { g_object_unref(parser); return; }
    JsonObject *obj = json_node_get_object(root);
    const char *primary = string_member(obj, "primary");
    const char *secondary = string_member(obj, "secondary");
    gtk_label_set_text(GTK_LABEL(p->primary), primary);
    gtk_label_set_text(GTK_LABEL(p->secondary), secondary);
    gboolean bilingual = *secondary != '\0';
    gtk_widget_set_visible(p->secondary, bilingual);
    gtk_widget_set_visible(p->separator, bilingual);
    gtk_widget_set_tooltip_markup(p->box, string_member(obj, "tooltip"));
    GtkStyleContext *style = gtk_widget_get_style_context(p->box);
    if (p->state) gtk_style_context_remove_class(style, p->state);
    g_free(p->state);
    p->state = g_strdup(string_member(obj, "class"));
    if (*p->state) gtk_style_context_add_class(style, p->state);
    if (g_getenv("MNWS_PANEL_DEBUG")) {
        GtkWidget *parent = gtk_widget_get_parent(p->box);
        g_message("MNWS rows: payload=%zu/%zu allocation=%dx%d parent=%s %dx%d font-unit=%d",
            strlen(primary), strlen(secondary), gtk_widget_get_allocated_width(p->box),
            gtk_widget_get_allocated_height(p->box), G_OBJECT_TYPE_NAME(parent),
            gtk_widget_get_allocated_width(parent), gtk_widget_get_allocated_height(parent), p->font_unit);
    }
    g_object_unref(parser);
}

static void read_next(Panel *p);
static gboolean start(gpointer data);

static void read_done(GObject *source, GAsyncResult *result, gpointer data) {
    Panel *p = data;
    GError *error = NULL;
    gchar *line = g_data_input_stream_read_line_finish_utf8(G_DATA_INPUT_STREAM(source), result, NULL, &error);
    if (!p->disposed) {
        if (line) {
            update(p, line);
            read_next(p);
        } else {
            gtk_label_set_text(GTK_LABEL(p->primary), mnws_text("♫ 正在重新连接", "♫ Reconnecting"));
            gtk_widget_hide(p->secondary);
            gtk_widget_hide(p->separator);
            p->retry = g_timeout_add_seconds_full(G_PRIORITY_DEFAULT, 5, start, panel_ref(p), panel_unref);
        }
    }
    g_clear_error(&error);
    g_free(line);
    panel_unref(p);
}

static void read_next(Panel *p) {
    g_data_input_stream_read_line_async(p->stream, G_PRIORITY_DEFAULT, p->cancel, read_done, panel_ref(p));
}

static gboolean start(gpointer data) {
    Panel *p = data;
    p->retry = 0;
    if (p->disposed) return G_SOURCE_REMOVE;
    g_clear_object(&p->stream);
    if (p->process) g_subprocess_send_signal(p->process, SIGTERM);
    g_clear_object(&p->process);
    gchar **argv = NULL;
    GError *error = NULL;
    if (g_shell_parse_argv(p->command, NULL, &argv, &error)) {
        p->process = g_subprocess_newv((const gchar *const *)argv, G_SUBPROCESS_FLAGS_STDOUT_PIPE, &error);
        g_strfreev(argv);
    }
    if (p->process) {
        p->stream = g_data_input_stream_new(g_subprocess_get_stdout_pipe(p->process));
        read_next(p);
    } else {
        g_warning("MNWS panel: %s", error ? error->message : "cannot launch plugin");
        p->retry = g_timeout_add_seconds_full(G_PRIORITY_DEFAULT, 5, start, panel_ref(p), panel_unref);
    }
    g_clear_error(&error);
    return G_SOURCE_REMOVE;
}

static GtkWidget *label(const char *class_name) {
    GtkWidget *widget = gtk_label_new("");
    gtk_label_set_xalign(GTK_LABEL(widget), 0.5);
    gtk_label_set_justify(GTK_LABEL(widget), GTK_JUSTIFY_CENTER);
    gtk_label_set_ellipsize(GTK_LABEL(widget), PANGO_ELLIPSIZE_END);
    gtk_label_set_width_chars(GTK_LABEL(widget), 1);
    gtk_label_set_max_width_chars(GTK_LABEL(widget), 1);
    gtk_style_context_add_class(gtk_widget_get_style_context(widget), class_name);
    return widget;
}

static Panel *create_widgets(GtkContainer *root, const char *name, int width) {
    static gboolean styled = FALSE;
    if (!styled) {
        GtkCssProvider *css = gtk_css_provider_new();
        gtk_css_provider_load_from_data(css,
            ".mnws-rows label { min-height: 0; padding: 0; }"
            ".mnws-rows separator { min-height: 0; margin: 0; border: none;"
            " background-color: transparent; opacity: 1; }", -1, NULL);
        gtk_style_context_add_provider_for_screen(gdk_screen_get_default(), GTK_STYLE_PROVIDER(css),
            GTK_STYLE_PROVIDER_PRIORITY_APPLICATION + 1);
        g_object_unref(css);
        styled = TRUE;
    }
    Panel *p = g_new0(Panel, 1);
    p->refs = 1;
    p->cancel = g_cancellable_new();
    p->box = g_object_new(mnws_rows_get_type(), "orientation", GTK_ORIENTATION_VERTICAL, NULL);
    ((MnwsRows *)p->box)->panel = p;
    gtk_widget_set_name(p->box, name);
    gtk_style_context_add_class(gtk_widget_get_style_context(p->box), "mnws-rows");
    gtk_widget_set_size_request(p->box, CLAMP(width, 80, 2000), -1);
    gtk_widget_set_valign(p->box, GTK_ALIGN_FILL);
    p->primary = label("primary");
    p->secondary = label("secondary");
    p->separator = gtk_separator_new(GTK_ORIENTATION_HORIZONTAL);
    p->theme_separator = gtk_css_provider_new();
    gtk_style_context_add_provider(gtk_widget_get_style_context(p->separator),
        GTK_STYLE_PROVIDER(p->theme_separator), GTK_STYLE_PROVIDER_PRIORITY_APPLICATION + 1);
    g_signal_connect(p->box, "style-updated", G_CALLBACK(theme_changed), p);
    gtk_widget_set_no_show_all(p->secondary, TRUE);
    gtk_widget_set_no_show_all(p->separator, TRUE);
    gtk_box_pack_start(GTK_BOX(p->box), gtk_box_new(GTK_ORIENTATION_VERTICAL, 0), TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(p->box), p->primary, FALSE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(p->box), p->separator, FALSE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(p->box), p->secondary, FALSE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(p->box), gtk_box_new(GTK_ORIENTATION_VERTICAL, 0), TRUE, TRUE, 0);
    gtk_label_set_text(GTK_LABEL(p->primary), mnws_text("♫ 等待网易云", "♫ Waiting for NetEase"));
    gtk_container_add(root, p->box);
    return p;
}

const size_t wbcffi_version = 2;
static gchar *config_string(const char *value) {
    JsonParser *parser = json_parser_new();
    gchar *result = NULL;
    if (json_parser_load_from_data(parser, value, -1, NULL)) {
        JsonNode *node = json_parser_get_root(parser);
        if (JSON_NODE_HOLDS_VALUE(node) && json_node_get_value_type(node) == G_TYPE_STRING)
            result = g_strdup(json_node_get_string(node));
    }
    g_object_unref(parser);
    return result ? result : g_strdup(value);
}
void *wbcffi_init(const wbcffi_init_info *info, const wbcffi_config_entry *entries, size_t count) {
    const char *command = "", *name = "mnws-panel-rows";
    int width = 420;
    for (size_t i = 0; i < count; i++) {
        if (!strcmp(entries[i].key, "exec")) command = entries[i].value;
        else if (!strcmp(entries[i].key, "widget_name")) name = entries[i].value;
        else if (!strcmp(entries[i].key, "width")) width = atoi(entries[i].value);
    }
    gchar *widget_name = config_string(name);
    Panel *p = create_widgets(info->get_root_widget(info->obj), widget_name, width);
    g_free(widget_name);
    p->command = config_string(command);
    for (size_t i = 0; i < count; i++) {
        gchar *value = config_string(entries[i].value);
        if (!strcmp(entries[i].key, "font_family")) p->font_family = g_strdup(value);
        else if (!strcmp(entries[i].key, "primary_color")) p->has_color[0] = gdk_rgba_parse(&p->colors[0], value);
        else if (!strcmp(entries[i].key, "secondary_color")) p->has_color[1] = gdk_rgba_parse(&p->colors[1], value);
        else if (!strcmp(entries[i].key, "separator_color")) {
            GdkRGBA color;
            if (gdk_rgba_parse(&color, value)) {
                p->has_separator_color = TRUE;
                gchar *rgba = gdk_rgba_to_string(&color);
                gchar *style = g_strdup_printf("separator { background-color: %s; opacity: 1; }", rgba);
                GtkCssProvider *css = gtk_css_provider_new();
                gtk_css_provider_load_from_data(css, style, -1, NULL);
                gtk_style_context_add_provider(gtk_widget_get_style_context(p->separator), GTK_STYLE_PROVIDER(css), GTK_STYLE_PROVIDER_PRIORITY_USER);
                g_object_unref(css);
                g_free(style);
                g_free(rgba);
            }
        }
        g_free(value);
    }
    start(p);
    return p;
}

void wbcffi_deinit(void *instance) {
    Panel *p = instance;
    p->disposed = TRUE;
    g_signal_handlers_disconnect_by_func(p->box, G_CALLBACK(theme_changed), p);
    ((MnwsRows *)p->box)->panel = NULL;
    if (p->retry) { g_source_remove(p->retry); p->retry = 0; }
    g_cancellable_cancel(p->cancel);
    if (p->process) g_subprocess_send_signal(p->process, SIGTERM);
    panel_unref(p);
}
