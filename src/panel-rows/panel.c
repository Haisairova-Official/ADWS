#include <signal.h>
#include "../adws-i18n.h"
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
#include "start-image.h"
#include "motion.h"

typedef struct {
    GtkWidget *start_image;
    GtkWidget *event_box;
    gint refs;
    gboolean disposed;
    gboolean has_content;
    GtkWidget *box, *controls, *previous_button, *next_button;
    gboolean controls_visible;
    gboolean animations, dynamic_width, vertical;
    GtkWidget *previous_motion, *lyrics_motion, *next_motion;
    GtkWidget *primary, *secondary, *separator;
    GSubprocess *process;
    GDataInputStream *stream;
    GCancellable *cancel;
    gchar *command, *left_command, *right_command, *previous_command, *next_command, *state;
    guint pressed;
    guint retry;
    int font_unit;
    int allocated_height, fitted_height;
    guint refresh_source;
    guint palette_watch;
    guint hover_source;
    guint hover_outside;
    GdkRectangle hover_anchor;
    gboolean hover_anchor_valid;
    gboolean theme_dirty;
    gboolean palette_valid;
    GdkRGBA applied_colors[3];
    gchar *font_family;
    GdkRGBA colors[2];
    gboolean has_color[2];
    gboolean has_separator_color;
    GdkRGBA separator_color;
} Panel;

typedef struct { GtkBox parent; Panel *panel; } AdwsRows;
typedef struct { GtkBoxClass parent; } AdwsRowsClass;
G_DEFINE_TYPE(AdwsRows, adws_rows, GTK_TYPE_BOX)

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

static gboolean lookup_color(GtkStyleContext *context, GdkRGBA *color,
                             const char *const *names) {
    for (int i = 0; names[i]; i++)
        if (gtk_style_context_lookup_color(context, names[i], color)) return TRUE;
    return FALSE;
}

static GdkRGBA theme_color(Panel *p, int index) {
    GtkStyleContext *context = gtk_widget_get_style_context(p->box);
    GdkRGBA foreground, background, accent;
    gtk_style_context_get_color(context, GTK_STATE_FLAG_NORMAL, &foreground);
    // Resolve theme roles, never a fixed application palette.
    background = foreground;
    if (!lookup_color(context, &background, (const char *[]) {
            "surface_container_high", "surface", "theme_bg_color", NULL}))
        background = (GdkRGBA){1-foreground.red, 1-foreground.green, 1-foreground.blue, 1};
    accent = foreground;
    lookup_color(context, &accent, (const char *[]) {
        "primary", "accent_color", "theme_selected_bg_color", NULL});
    if (color_distance(accent, background) < color_distance(foreground, background)*0.3)
        accent = blend(foreground, accent, .65);
    if (color_distance(accent, foreground) < .04)
        accent = blend(foreground, background, .72);
    if (index == 0) return foreground;
    if (index == 1) return accent;
    GdkRGBA line = blend(accent, background, .45);
    lookup_color(context, &line, (const char *[]) {"outline", "borders", NULL});
    if (color_distance(line, accent) < .06 || color_distance(line, foreground) < .04)
        line = blend(accent, background, .40);
    return line;
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
    PangoAttrList *old = gtk_label_get_attributes(GTK_LABEL(label));
    if (!old || !pango_attr_list_equal(old, attrs))
        gtk_label_set_attributes(GTK_LABEL(label), attrs);
    pango_attr_list_unref(attrs);
    if (p->vertical) {
        // GtkLabel replaces its transformed layout context on reparent, text
        // or theme changes. Configure it after applying the font attributes.
        PangoLayout *layout = gtk_label_get_layout(GTK_LABEL(label));
        PangoContext *context = pango_layout_get_context(layout);
        if (pango_context_get_base_gravity(context) != PANGO_GRAVITY_AUTO) {
            pango_context_set_base_gravity(context, PANGO_GRAVITY_AUTO);
            pango_context_set_gravity_hint(context, PANGO_GRAVITY_HINT_NATURAL);
            pango_layout_context_changed(layout);
            gtk_widget_queue_resize(label);
        }
    }
}

static void schedule_refresh(Panel *p);

static void theme_changed(GtkWidget *widget, gpointer data) {
    (void)widget;
    Panel *p = data;
    if (p->disposed) return;
    p->theme_dirty = TRUE;
    schedule_refresh(p);
}

static void fit_height(Panel *p, int height) {
    if (height <= 1) return;
    // Measure the active font, including CJK fallback, against the allocated bar
    // height. Font sizes are 3u and 2u; u is found rather than fixed in pixels.
    PangoLayout *layout = gtk_widget_create_pango_layout(p->primary, "Ag国語あいう");
    PangoFontDescription *font = pango_font_description_copy(
        pango_context_get_font_description(pango_layout_get_context(layout)));
    if (p->font_family && *p->font_family)
        pango_font_description_set_family(font, p->font_family);
    int thickness = MAX(1, (height + 18) / 36);
    if (p->previous_button && p->next_button) {
        int icon_size = MAX(1, height / 2);
        gtk_image_set_pixel_size(GTK_IMAGE(gtk_button_get_image(GTK_BUTTON(p->previous_button))), icon_size);
        gtk_image_set_pixel_size(GTK_IMAGE(gtk_button_get_image(GTK_BUTTON(p->next_button))), icon_size);
    }
    int low = 1, high = height * PANGO_SCALE;
    while (low < high) {
        int middle = (low + high + 1) / 2;
        int used = measure(layout, font, middle * 3) + measure(layout, font, middle * 2) + thickness;
        if (used <= height) low = middle;
        else high = middle - 1;
    }
    p->font_unit = low;
    font_size(p, p->primary, low * 3, 0);
    font_size(p, p->secondary, low * 2, 1);
    int old_height;
    if (p->vertical) {
        gtk_widget_get_size_request(p->separator, &old_height, NULL);
        if (old_height != thickness) gtk_widget_set_size_request(p->separator, thickness, -1);
    } else {
        gtk_widget_get_size_request(p->separator, NULL, &old_height);
        if (old_height != thickness) gtk_widget_set_size_request(p->separator, -1, thickness);
    }
    pango_font_description_free(font);
    g_object_unref(layout);
}

static gboolean refresh_palette(gpointer data) {
    Panel *p = data;
    if (p->disposed) return G_SOURCE_REMOVE;
    if (!p->font_unit) return G_SOURCE_CONTINUE;
    for (int i = 0; i < 3; i++) {
        GdkRGBA color = i < 2 ? (p->has_color[i] ? p->colors[i] : theme_color(p, i))
            : (p->has_separator_color ? p->separator_color : theme_color(p, 2));
        if (!p->palette_valid || !gdk_rgba_equal(&color, &p->applied_colors[i])) {
            p->applied_colors[i] = color;
            if (i < 2) font_size(p, i == 0 ? p->primary : p->secondary,
                                 p->font_unit * (i == 0 ? 3 : 2), i);
            else {
                p->separator_color = color;
                gtk_widget_queue_draw(p->separator);
            }
        }
    }
    p->palette_valid = TRUE;
    return G_SOURCE_CONTINUE;
}

static gboolean refresh_visuals(gpointer data) {
    Panel *p = data;
    p->refresh_source = 0;
    if (p->disposed) return G_SOURCE_REMOVE;
    gboolean dirty = p->theme_dirty;
    p->theme_dirty = FALSE;
    if (dirty || p->allocated_height != p->fitted_height) {
        p->fitted_height = p->allocated_height;
        fit_height(p, p->allocated_height);
        refresh_palette(p);
    }
    return G_SOURCE_REMOVE;
}

static void schedule_refresh(Panel *p) {
    if (!p->refresh_source && !p->disposed)
        p->refresh_source = g_idle_add(refresh_visuals, p);
}

static gboolean draw_separator(GtkWidget *widget, cairo_t *cr, gpointer data) {
    Panel *p = data;
    int width = gtk_widget_get_allocated_width(widget);
    int height = gtk_widget_get_allocated_height(widget);
    // Drawing the inset does not change widget requisitions or trigger relayout.
    gdk_cairo_set_source_rgba(cr, &p->separator_color);
    if (p->vertical) cairo_rectangle(cr, 0, height * .05, width, height * .9);
    else cairo_rectangle(cr, width * .05, 0, width * .9, height);
    cairo_fill(cr);
    return TRUE;
}

static void rows_height(GtkWidget *widget, int *minimum, int *natural) {
    Panel *p = ((AdwsRows *)widget)->panel;
    if (p && p->vertical) {
        GTK_WIDGET_CLASS(adws_rows_parent_class)->get_preferred_height(widget, minimum, natural);
        return;
    }
    // The bar determines the height. Old font metrics must not prevent a shrink.
    *minimum = *natural = 0;
}
static void rows_height_for_width(GtkWidget *widget, int width, int *minimum, int *natural) {
    (void)width;
    rows_height(widget, minimum, natural);
}
static void rows_width(GtkWidget *widget, int *minimum, int *natural) {
    Panel *p = ((AdwsRows *)widget)->panel;
    if (p && p->vertical) *minimum = *natural = 0;
    else GTK_WIDGET_CLASS(adws_rows_parent_class)->get_preferred_width(widget, minimum, natural);
}
static void rows_width_for_height(GtkWidget *widget, int height, int *minimum, int *natural) {
    (void)height; rows_width(widget, minimum, natural);
}
static void rows_allocate(GtkWidget *widget, GtkAllocation *allocation) {
    Panel *p = ((AdwsRows *)widget)->panel;
    GTK_WIDGET_CLASS(adws_rows_parent_class)->size_allocate(widget, allocation);
    int thickness = p && p->vertical ? allocation->width : allocation->height;
    if (p && !p->disposed && p->allocated_height != thickness) {
        p->allocated_height = thickness;
        schedule_refresh(p);
    }
}
static void adws_rows_class_init(AdwsRowsClass *klass) {
    GtkWidgetClass *widget = GTK_WIDGET_CLASS(klass);
    widget->get_preferred_width = rows_width;
    widget->get_preferred_width_for_height = rows_width_for_height;
    widget->get_preferred_height = rows_height;
    widget->get_preferred_height_for_width = rows_height_for_width;
    widget->size_allocate = rows_allocate;
}
static void adws_rows_init(AdwsRows *rows) { (void)rows; }

static Panel *panel_ref(Panel *p) { p->refs++; return p; }
static void panel_unref(gpointer data) {
    Panel *p = data;
    if (--p->refs) return;
    g_clear_object(&p->stream);
    g_clear_object(&p->process);
    g_clear_object(&p->cancel);
    g_free(p->command);
    g_free(p->left_command);
    g_free(p->right_command);
    g_free(p->previous_command);
    g_free(p->next_command);
    g_free(p->state);
    g_free(p->font_family);
    if (p->refresh_source) g_source_remove(p->refresh_source);
    if (p->palette_watch) g_source_remove(p->palette_watch);
    if (p->hover_source) g_source_remove(p->hover_source);
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
    // An interrupted stream must not replace already displayed lyrics with a transient error.
    if (p->has_content && !strcmp(string_member(obj, "class"), "error")) {
        g_object_unref(parser);
        return;
    }
    const char *primary = string_member(obj, "primary");
    const char *secondary = string_member(obj, "secondary");
    p->has_content = TRUE;
    gtk_label_set_text(GTK_LABEL(p->primary), primary);
    gtk_label_set_text(GTK_LABEL(p->secondary), secondary);
    gboolean bilingual = *secondary != '\0';
    gtk_widget_set_visible(p->secondary, bilingual);
    gtk_widget_set_visible(p->separator, bilingual);
    GtkStyleContext *style = gtk_widget_get_style_context(p->box);
    const char *state = string_member(obj, "class");
    if (g_strcmp0(p->state, state)) {
        if (p->state) gtk_style_context_remove_class(style, p->state);
        g_free(p->state);
        p->state = g_strdup(state);
        if (*p->state) gtk_style_context_add_class(style, p->state);
    }
    if (g_getenv("ADWS_PANEL_DEBUG")) {
        GtkWidget *parent = gtk_widget_get_parent(p->box);
        g_message("ADWS rows: payload=%zu/%zu allocation=%dx%d parent=%s %dx%d font-unit=%d",
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
            // Retry in the background while preserving the last rendered state.
            if (error) g_warning("ADWS panel stream interrupted: %s", error->message);
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
        g_warning("ADWS panel: %s", error ? error->message : "cannot launch plugin");
        p->retry = g_timeout_add_seconds_full(G_PRIORITY_DEFAULT, 5, start, panel_ref(p), panel_unref);
    }
    g_clear_error(&error);
    return G_SOURCE_REMOVE;
}

static GtkWidget *label(const char *class_name, gboolean dynamic_width) {
    GtkWidget *widget = gtk_label_new("");
    gtk_label_set_xalign(GTK_LABEL(widget), 0.5);
    gtk_label_set_justify(GTK_LABEL(widget), GTK_JUSTIFY_CENTER);
    if (!dynamic_width) {
        gtk_label_set_ellipsize(GTK_LABEL(widget), PANGO_ELLIPSIZE_END);
        gtk_label_set_width_chars(GTK_LABEL(widget), 1);
        gtk_label_set_max_width_chars(GTK_LABEL(widget), 1);
    }
    gtk_style_context_add_class(gtk_widget_get_style_context(widget), class_name);
    return widget;
}

static gboolean event_from_controls(Panel *p, GdkEventButton *event) {
    GtkWidget *source = gtk_get_event_widget((GdkEvent *)event);
    return source && (source == p->previous_button || source == p->next_button
        || gtk_widget_is_ancestor(source, p->previous_button)
        || gtk_widget_is_ancestor(source, p->next_button));
}

static void spawn_command(const gchar *command, const gchar *label) {
    if (!command || !*command) return;
    gchar **argv = NULL;
    GError *error = NULL;
    if (!g_shell_parse_argv(command, NULL, &argv, &error)
            || !g_spawn_async(NULL, argv, NULL, G_SPAWN_SEARCH_PATH,
                              NULL, NULL, NULL, &error)) {
        g_warning("ADWS panel %s: %s", label, error ? error->message : "cannot launch command");
    }
    g_strfreev(argv);
    g_clear_error(&error);
}

static gboolean panel_press(GtkWidget *widget, GdkEventButton *event, gpointer data) {
    (void)widget;
    Panel *p = data;
    if ((event->button != 1 && event->button != 3) || event_from_controls(p, event)) return FALSE;
    p->pressed = event->button;
    return TRUE;
}

static gboolean panel_release(GtkWidget *widget, GdkEventButton *event, gpointer data) {
    Panel *p = data;
    if ((event->button != 1 && event->button != 3) || event_from_controls(p, event)) return FALSE;
    gboolean activate = p->pressed == event->button && event->x >= 0 && event->y >= 0
        && event->x < gtk_widget_get_allocated_width(widget)
        && event->y < gtk_widget_get_allocated_height(widget);
    p->pressed = 0;
    if (activate) spawn_command(event->button == 3 ? p->right_command : p->left_command,
                                event->button == 3 ? "settings" : "play-pause");
    return TRUE;
}

static gboolean panel_bounds(Panel *p, GdkRectangle *bounds) {
    GtkWidget *top = gtk_widget_get_toplevel(p->event_box);
    if (!gtk_widget_get_mapped(p->event_box)
            || !gtk_widget_translate_coordinates(p->event_box, top, 0, 0,
                                                  &bounds->x, &bounds->y)) return FALSE;
    bounds->width = gtk_widget_get_allocated_width(p->event_box);
    bounds->height = gtk_widget_get_allocated_height(p->event_box);
    return TRUE;
}

static gboolean in_bounds(const GdkRectangle *bounds, int x, int y) {
    return x >= bounds->x && y >= bounds->y
        && x < bounds->x + bounds->width && y < bounds->y + bounds->height;
}

static void show_controls(Panel *p, gboolean shown) {
    p->controls_visible = shown;
    gboolean previous = shown && p->previous_command && *p->previous_command;
    gboolean next = shown && p->next_command && *p->next_command;
    if (p->animations) {
        motion_reveal(p->previous_motion, previous);
        motion_reveal(p->next_motion, next);
    } else {
        gtk_widget_set_visible(p->previous_button, previous);
        gtk_widget_set_visible(p->next_button, next);
    }
}

static gboolean panel_crossing(GtkWidget *widget, GdkEventCrossing *event, gpointer data);

static void enable_motion(Panel *p) {
    GtkWidget *children[] = {p->previous_button, p->box, p->next_button};
    for (guint i = 0; i < G_N_ELEMENTS(children); i++) {
        GtkWidget *child = children[i];
        g_object_ref(child);
        gtk_container_remove(GTK_CONTAINER(p->controls), child);
        GtkWidget *wrapper = i == 1 && !p->dynamic_width ? child : motion_wrap(child, i != 1);
        if (wrapper != child) {
            ((AdwsMotion *)wrapper)->vertical = p->vertical;
            // Crossing events do not bubble through GtkEventBox windows. The
            // animation viewport must start the same deferred hover check.
            gtk_widget_add_events(wrapper, GDK_ENTER_NOTIFY_MASK | GDK_LEAVE_NOTIFY_MASK);
            g_signal_connect(wrapper, "enter-notify-event", G_CALLBACK(panel_crossing), p);
        }
        gtk_box_pack_start(GTK_BOX(p->controls), wrapper, i == 1, i == 1, 0);
        g_object_unref(child);
        if (i == 0) p->previous_motion = wrapper;
        if (i == 1 && wrapper != child) p->lyrics_motion = wrapper;
        if (i == 2) p->next_motion = wrapper;
    }
    p->animations = TRUE;
}

static gboolean hover_step(Panel *p, const GdkRectangle *bounds, int x, int y, gboolean on_surface) {
    if (!on_surface) {
        p->hover_anchor_valid = FALSE;
        p->hover_outside = 0;
        show_controls(p, FALSE);
        return G_SOURCE_REMOVE;
    }
    gboolean shown = p->controls_visible;
    // Keep the pre-expansion hit area valid until the pointer really leaves.
    // Right-aligned/centred bars can move the widget when its width changes.
    gboolean inside = in_bounds(bounds, x, y)
        || (shown && p->hover_anchor_valid && in_bounds(&p->hover_anchor, x, y));
    if (inside) {
        p->hover_outside = 0;
        if (!shown) {
            p->hover_anchor = *bounds;
            p->hover_anchor_valid = TRUE;
            show_controls(p, TRUE);
        }
        return G_SOURCE_CONTINUE;
    }
    if (shown && ++p->hover_outside < 2) return G_SOURCE_CONTINUE;
    p->hover_anchor_valid = FALSE;
    show_controls(p, FALSE);
    return G_SOURCE_REMOVE;
}

static gboolean check_hover(gpointer data) {
    Panel *p = data;
    GdkRectangle bounds;
    if (p->disposed || !panel_bounds(p, &bounds)) {
        p->hover_source = 0;
        return G_SOURCE_REMOVE;
    }
    GtkWidget *top = gtk_widget_get_toplevel(p->event_box);
    GdkSeat *seat = gdk_display_get_default_seat(gtk_widget_get_display(top));
    GdkDevice *pointer = seat ? gdk_seat_get_pointer(seat) : NULL;
    int x = -1, y = -1;
    GdkWindow *surface = gtk_widget_get_window(top);
    // The coordinate query's return value may be NULL over a client-side child
    // window. Query the actual pointer window separately for surface membership.
    GdkWindow *under_pointer = pointer ? gdk_device_get_window_at_position(pointer, NULL, NULL) : NULL;
    if (pointer) gdk_window_get_device_position(surface, pointer, &x, &y, NULL);
    // Wayland keeps the last in-surface coordinates after wl_pointer.leave.
    // Coordinates alone therefore cannot tell whether the pointer left the bar.
    gboolean on_surface = under_pointer
        && gdk_window_get_effective_toplevel(under_pointer) == gdk_window_get_effective_toplevel(surface);
    gboolean keep = hover_step(p, &bounds, x, y, on_surface);
    if (!keep) p->hover_source = 0;
    return keep;
}

static gboolean panel_crossing(GtkWidget *widget, GdkEventCrossing *event, gpointer data) {
    (void)widget;
    Panel *p = data;
    if (p->disposed || event->type != GDK_ENTER_NOTIFY
            || event->mode != GDK_CROSSING_NORMAL) return FALSE;
    gboolean available = (p->previous_command && *p->previous_command)
        || (p->next_command && *p->next_command);
    // Never alter geometry from a crossing callback. Mapping child buttons can
    // synchronously generate more crossing events before show/hide returns.
    if (available && !p->hover_source) p->hover_source = g_timeout_add(60, check_hover, p);
    return FALSE;
}

static void previous_clicked(GtkButton *button, gpointer data) {
    (void)button;
    Panel *p = data;
    spawn_command(p->previous_command, "previous");
}

static void next_clicked(GtkButton *button, gpointer data) {
    (void)button;
    Panel *p = data;
    spawn_command(p->next_command, "next");
}

static void configure_controls(Panel *p) {
    show_controls(p, FALSE);
}

static Panel *create_widgets(GtkContainer *root, const char *name, int width) {
    static gboolean styled = FALSE;
    if (!styled) {
        GtkCssProvider *css = gtk_css_provider_new();
        gtk_css_provider_load_from_data(css,
            ".adws-rows label { min-height: 0; padding: 0; }"
            ".adws-rows separator { min-height: 0; margin: 0; border: none;"
            " background-color: transparent; opacity: 1; }"
            ".adws-controls button { min-width: 0; min-height: 0; padding: 0 0.35em; }", -1, NULL);
        gtk_style_context_add_provider_for_screen(gdk_screen_get_default(), GTK_STYLE_PROVIDER(css),
            GTK_STYLE_PROVIDER_PRIORITY_APPLICATION + 1);
        g_object_unref(css);
        styled = TRUE;
    }
    Panel *p = g_new0(Panel, 1);
    p->refs = 1;
    p->dynamic_width = width <= 0;
    p->cancel = g_cancellable_new();
    p->event_box = gtk_event_box_new();
    gtk_widget_set_hexpand(p->event_box, FALSE);
    gtk_widget_set_hexpand(GTK_WIDGET(root), FALSE);
    gtk_event_box_set_visible_window(GTK_EVENT_BOX(p->event_box), FALSE);
    gtk_widget_add_events(p->event_box, GDK_BUTTON_PRESS_MASK | GDK_BUTTON_RELEASE_MASK
                          | GDK_ENTER_NOTIFY_MASK | GDK_LEAVE_NOTIFY_MASK);
    g_signal_connect(p->event_box, "button-press-event", G_CALLBACK(panel_press), p);
    g_signal_connect(p->event_box, "button-release-event", G_CALLBACK(panel_release), p);
    g_signal_connect(p->event_box, "enter-notify-event", G_CALLBACK(panel_crossing), p);
    g_signal_connect(p->event_box, "leave-notify-event", G_CALLBACK(panel_crossing), p);
    GtkWidget *content = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    p->box = g_object_new(adws_rows_get_type(), "orientation", GTK_ORIENTATION_VERTICAL, NULL);
    ((AdwsRows *)p->box)->panel = p;
    gtk_widget_set_name(p->event_box, name);
    gtk_style_context_add_class(gtk_widget_get_style_context(p->box), "adws-rows");
    if (width > 0) gtk_widget_set_size_request(p->event_box, CLAMP(width, 80, 2000), -1);
    gtk_widget_set_hexpand(p->box, FALSE);
    gtk_widget_set_valign(p->box, GTK_ALIGN_FILL);
    p->primary = label("primary", width <= 0);
    p->secondary = label("secondary", width <= 0);
    p->separator = gtk_drawing_area_new();
    g_signal_connect(p->separator, "draw", G_CALLBACK(draw_separator), p);
    g_signal_connect(p->box, "style-updated", G_CALLBACK(theme_changed), p);
    gtk_widget_set_no_show_all(p->secondary, TRUE);
    gtk_widget_set_no_show_all(p->separator, TRUE);
    gtk_box_pack_start(GTK_BOX(p->box), gtk_box_new(GTK_ORIENTATION_VERTICAL, 0), TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(p->box), p->primary, FALSE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(p->box), p->separator, FALSE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(p->box), p->secondary, FALSE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(p->box), gtk_box_new(GTK_ORIENTATION_VERTICAL, 0), TRUE, TRUE, 0);
    gtk_label_set_text(GTK_LABEL(p->primary), adws_text("♫ 等待网易云", "♫ Waiting for NetEase"));
    p->controls = content;
    gtk_style_context_add_class(gtk_widget_get_style_context(p->controls), "adws-controls");
    p->previous_button = gtk_button_new_from_icon_name("media-skip-backward-symbolic", GTK_ICON_SIZE_MENU);
    p->next_button = gtk_button_new_from_icon_name("media-skip-forward-symbolic", GTK_ICON_SIZE_MENU);
    gtk_widget_set_no_show_all(p->previous_button, TRUE);
    gtk_widget_set_no_show_all(p->next_button, TRUE);
    atk_object_set_name(gtk_widget_get_accessible(p->previous_button), adws_text("上一首", "Previous"));
    atk_object_set_name(gtk_widget_get_accessible(p->next_button), adws_text("下一首", "Next"));
    g_signal_connect(p->previous_button, "clicked", G_CALLBACK(previous_clicked), p);
    g_signal_connect(p->next_button, "clicked", G_CALLBACK(next_clicked), p);
    g_signal_connect(p->previous_button, "enter-notify-event", G_CALLBACK(panel_crossing), p);
    g_signal_connect(p->next_button, "enter-notify-event", G_CALLBACK(panel_crossing), p);
    gtk_box_pack_start(GTK_BOX(content), p->previous_button, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(content), p->box, TRUE, TRUE, 0);
    gtk_box_pack_end(GTK_BOX(content), p->next_button, FALSE, FALSE, 0);
    gtk_container_add(GTK_CONTAINER(p->event_box), content);
    gtk_container_add(root, p->event_box);
    // GTK does not emit style-updated for changes affecting only named colors.
    // Compare the resolved palette; only changed colors cause widget updates.
    p->palette_watch = g_timeout_add(100, refresh_palette, p);
    return p;
}

const size_t wbcffi_version = 2;
static gchar *config_string(const char *value) {
    JsonParser *parser = json_parser_new();
    gchar *result = NULL;
    if (json_parser_load_from_data(parser, value, -1, NULL)) {
        JsonNode *node = json_parser_get_root(parser);
        if (node && JSON_NODE_HOLDS_VALUE(node) && json_node_get_value_type(node) == G_TYPE_STRING)
            result = g_strdup(json_node_get_string(node));
    }
    g_object_unref(parser);
    return result ? result : g_strdup(value);
}

static gboolean config_boolean(const char *value) {
    JsonParser *parser = json_parser_new();
    gboolean result = FALSE;
    // Waybar serializes CFFI values as JSON, including trailing whitespace.
    // Parse the boolean type instead of comparing the raw serialized text.
    if (json_parser_load_from_data(parser, value, -1, NULL)) {
        JsonNode *node = json_parser_get_root(parser);
        result = node && JSON_NODE_HOLDS_VALUE(node) && json_node_get_value_type(node) == G_TYPE_BOOLEAN
            && json_node_get_boolean(node);
    }
    g_object_unref(parser);
    return result;
}
void *wbcffi_init(const wbcffi_init_info *info, const wbcffi_config_entry *entries, size_t count) {
    for (size_t i = 0; i < count; i++) {
        if (strcmp(entries[i].key, "start_image")) continue;
        Panel *p = g_new0(Panel, 1);
        AdwsStart *s = g_object_new(adws_start_get_type(), NULL);
        p->start_image = GTK_WIDGET(s);
        for (size_t j = 0; j < count; j++) {
            gchar *value = config_string(entries[j].value);
            if (!strcmp(entries[j].key, "start_animations")) s->animations = config_boolean(entries[j].value);
            else if (!strcmp(entries[j].key, "animation_duration")) s->fade_duration=CLAMP(atoi(value),80,1000);
            else if (!strcmp(entries[j].key, "vertical")) s->vertical = config_boolean(entries[j].value);
            else if (!strcmp(entries[j].key, "start_image")) s->normal = gdk_pixbuf_new_from_file(value, NULL);
            else if (!strcmp(entries[j].key, "start_hover_image") && *value) s->hover = gdk_pixbuf_new_from_file(value, NULL);
            else if (!strcmp(entries[j].key, "exec")) s->command = g_strdup(value);
            else if (!strcmp(entries[j].key, "start_right_command")) s->right_command = g_strdup(value);
            else if (!strcmp(entries[j].key, "start_middle_command")) s->middle_command = g_strdup(value);
            else if (!strcmp(entries[j].key, "start_tooltip") && *value) gtk_widget_set_tooltip_text(GTK_WIDGET(s), value);
            else if (!strcmp(entries[j].key, "start_label")) s->label = g_strdup(value);
            g_free(value);
        }
        if (s->hover && (!s->normal || gdk_pixbuf_get_width(s->normal) != gdk_pixbuf_get_width(s->hover)
                || gdk_pixbuf_get_height(s->normal) != gdk_pixbuf_get_height(s->hover))) {
            g_warning("ADWS start: image dimensions differ; ignoring hover image");
            g_clear_object(&s->hover);
        }
        gtk_container_add(info->get_root_widget(info->obj), p->start_image);
        g_object_ref(p->start_image);
        gtk_widget_show(p->start_image);
        return p;
    }
    const char *command = "", *name = "adws-panel-rows";
    int width = 420;
    gboolean vertical = FALSE;
    for (size_t i = 0; i < count; i++) {
        if (!strcmp(entries[i].key, "exec")) command = entries[i].value;
        else if (!strcmp(entries[i].key, "widget_name")) name = entries[i].value;
        else if (!strcmp(entries[i].key, "width")) width = atoi(entries[i].value);
        else if (!strcmp(entries[i].key, "vertical")) vertical = config_boolean(entries[i].value);
    }
    gchar *widget_name = config_string(name);
    Panel *p = create_widgets(info->get_root_widget(info->obj), widget_name, width);
    g_free(widget_name);
    if (vertical) {
        p->vertical = TRUE;
        gtk_orientable_set_orientation(GTK_ORIENTABLE(p->controls), GTK_ORIENTATION_VERTICAL);
        gtk_orientable_set_orientation(GTK_ORIENTABLE(p->box), GTK_ORIENTATION_HORIZONTAL);
        gtk_widget_set_size_request(p->event_box, -1, width > 0 ? CLAMP(width,80,2000) : -1);
        GtkWidget *labels[] = {p->primary,p->secondary};
        for (int i=0;i<2;i++) {
            gtk_label_set_ellipsize(GTK_LABEL(labels[i]), PANGO_ELLIPSIZE_NONE);
            gtk_label_set_width_chars(GTK_LABEL(labels[i]), -1);
            gtk_label_set_max_width_chars(GTK_LABEL(labels[i]), -1);
            // GTK's angle is counter-clockwise. 270 gives top-to-bottom progression.
            // Pango AUTO keeps CJK upright while Latin follows the rotated line.
            PangoContext *context = gtk_widget_get_pango_context(labels[i]);
            pango_context_set_base_gravity(context, PANGO_GRAVITY_AUTO);
            pango_context_set_gravity_hint(context, PANGO_GRAVITY_HINT_NATURAL);
            gtk_label_set_angle(GTK_LABEL(labels[i]), 270);
        }
    }
    p->command = config_string(command);
    for (size_t i = 0; i < count; i++) {
        gchar *value = config_string(entries[i].value);
        if (!strcmp(entries[i].key, "font_family")) p->font_family = g_strdup(value);
        else if (!strcmp(entries[i].key, "animations")) p->animations = config_boolean(entries[i].value);
        else if (!strcmp(entries[i].key, "left_command")) p->left_command = g_strdup(value);
        else if (!strcmp(entries[i].key, "right_command")) p->right_command = g_strdup(value);
        else if (!strcmp(entries[i].key, "previous_command")) p->previous_command = g_strdup(value);
        else if (!strcmp(entries[i].key, "next_command")) p->next_command = g_strdup(value);
        else if (!strcmp(entries[i].key, "primary_color")) p->has_color[0] = gdk_rgba_parse(&p->colors[0], value);
        else if (!strcmp(entries[i].key, "secondary_color")) p->has_color[1] = gdk_rgba_parse(&p->colors[1], value);
        else if (!strcmp(entries[i].key, "separator_color")) {
            p->has_separator_color = gdk_rgba_parse(&p->separator_color, value);
        }
        g_free(value);
    }
    if (p->animations) enable_motion(p);
    configure_controls(p);
    start(p);
    return p;
}

void wbcffi_deinit(void *instance) {
    Panel *p = instance;
    if (p->start_image) {
        gtk_widget_destroy(p->start_image);
        g_object_unref(p->start_image);
        g_free(p);
        return;
    }
    p->disposed = TRUE;
    if (p->refresh_source) { g_source_remove(p->refresh_source); p->refresh_source = 0; }
    if (p->palette_watch) { g_source_remove(p->palette_watch); p->palette_watch = 0; }
    if (p->hover_source) { g_source_remove(p->hover_source); p->hover_source = 0; }
    g_signal_handlers_disconnect_by_data(p->event_box, p);
    g_signal_handlers_disconnect_by_data(p->previous_button, p);
    g_signal_handlers_disconnect_by_data(p->next_button, p);
    if (p->previous_motion) g_signal_handlers_disconnect_by_data(p->previous_motion, p);
    if (p->lyrics_motion) g_signal_handlers_disconnect_by_data(p->lyrics_motion, p);
    if (p->next_motion) g_signal_handlers_disconnect_by_data(p->next_motion, p);
    g_signal_handlers_disconnect_by_data(p->separator, p);
    g_signal_handlers_disconnect_by_func(p->box, G_CALLBACK(theme_changed), p);
    ((AdwsRows *)p->box)->panel = NULL;
    if (p->retry) { g_source_remove(p->retry); p->retry = 0; }
    g_cancellable_cancel(p->cancel);
    if (p->process) g_subprocess_send_signal(p->process, SIGTERM);
    panel_unref(p);
}
