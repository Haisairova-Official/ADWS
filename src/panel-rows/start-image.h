/* Image start button: height follows allocation; width preserves image aspect. */
typedef struct {
    GtkDrawingArea parent;
    GdkPixbuf *normal, *hover;
    gchar *command, *right_command, *middle_command, *label;
    gboolean inside, vertical;
    guint pressed;
    int last_height;
} MnwsStart;
typedef struct { GtkDrawingAreaClass parent; } MnwsStartClass;
G_DEFINE_TYPE(MnwsStart, mnws_start, GTK_TYPE_DRAWING_AREA)

static void start_metrics(GtkWidget *w, int height, int *width, int *image_height) {
    MnwsStart *s = (MnwsStart *)w;
    GtkStyleContext *ctx = gtk_widget_get_style_context(w);
    GtkBorder pad, border;
    gtk_style_context_get_padding(ctx, GTK_STATE_FLAG_NORMAL, &pad);
    gtk_style_context_get_border(ctx, GTK_STATE_FLAG_NORMAL, &border);
    PangoLayout *text = gtk_widget_create_pango_layout(w, s->label ? s->label : "Apps");
    int tw, th, css_min = 0;
    pango_layout_get_pixel_size(text, &tw, &th);
    g_object_unref(text);
    gtk_style_context_get(ctx, GTK_STATE_FLAG_NORMAL, "min-width", &css_min, NULL);
    int h = MAX(1, height > 1 ? height - pad.top - pad.bottom - border.top - border.bottom : th);
    int iw = s->normal ? (int)((double)h * gdk_pixbuf_get_width(s->normal) / gdk_pixbuf_get_height(s->normal) + .5) : tw;
    *width = MAX(MAX(tw, css_min) + pad.left + pad.right + border.left + border.right, iw);
    *image_height = h;
}
static GtkSizeRequestMode start_request_mode(GtkWidget *w) {
    return ((MnwsStart *)w)->vertical ? GTK_SIZE_REQUEST_HEIGHT_FOR_WIDTH : GTK_SIZE_REQUEST_WIDTH_FOR_HEIGHT;
}
static void start_height_for_width(GtkWidget *w, gint width, gint *minimum, gint *natural) {
    MnwsStart *s = (MnwsStart *)w;
    if (!s->vertical) { *minimum = *natural = 1; return; }
    int available = MAX(1,width);
    int height = s->normal ? (int)((double)available*gdk_pixbuf_get_height(s->normal)/gdk_pixbuf_get_width(s->normal)+.5) : available;
    *minimum = *natural = MAX(1,height);
}
static void start_width_for_height(GtkWidget *w, gint h, gint *minimum, gint *natural) {
    if (((MnwsStart *)w)->vertical) { *minimum = *natural = 1; return; }
    int width, ih; start_metrics(w, h, &width, &ih); *minimum = *natural = width;
}
static void start_width(GtkWidget *w, gint *minimum, gint *natural) {
    if (((MnwsStart *)w)->vertical) *minimum = *natural = 1;
    else start_width_for_height(w, ((MnwsStart *)w)->last_height, minimum, natural);
}
static void start_height(GtkWidget *w, gint *minimum, gint *natural) {
    if (((MnwsStart *)w)->vertical) start_height_for_width(w, ((MnwsStart *)w)->last_height, minimum, natural);
    else *minimum = *natural = 1;
}
static void start_allocate(GtkWidget *w, GtkAllocation *a) {
    GTK_WIDGET_CLASS(mnws_start_parent_class)->size_allocate(w, a);
    MnwsStart *s = (MnwsStart *)w;
    int thickness = s->vertical ? a->width : a->height;
    if (s->last_height != thickness) { s->last_height = thickness; gtk_widget_queue_resize(w); }
}
static gboolean start_draw(GtkWidget *w, cairo_t *cr) {
    MnwsStart *s = (MnwsStart *)w;
    int width = gtk_widget_get_allocated_width(w), height = gtk_widget_get_allocated_height(w), wanted, ih;
    start_metrics(w, height, &wanted, &ih);
    GtkStyleContext *ctx = gtk_widget_get_style_context(w);
    if (!s->hover) {
        gtk_render_background(ctx, cr, 0, 0, width, height);
        gtk_render_frame(ctx, cr, 0, 0, width, height);
    }
    GdkPixbuf *image = s->inside && s->hover ? s->hover : s->normal;
    if (image) {
        double scale = s->vertical ? (double)width/gdk_pixbuf_get_width(image) : (double)ih / gdk_pixbuf_get_height(image);
        if (s->vertical) ih = (int)(scale*gdk_pixbuf_get_height(image));
        double iw = scale * gdk_pixbuf_get_width(image);
        cairo_save(cr);
        cairo_translate(cr, (width-iw)/2, (height-ih)/2.0);
        cairo_scale(cr, scale, scale);
        gdk_cairo_set_source_pixbuf(cr, image, 0, 0);
        cairo_paint(cr);
        cairo_restore(cr);
    }
    return TRUE;
}
static gboolean start_crossing(GtkWidget *w, GdkEventCrossing *event) {
    MnwsStart *s = (MnwsStart *)w;
    s->inside = event->type == GDK_ENTER_NOTIFY;
    if (s->inside) gtk_widget_set_state_flags(w, GTK_STATE_FLAG_PRELIGHT, FALSE);
    else gtk_widget_unset_state_flags(w, GTK_STATE_FLAG_PRELIGHT);
    gtk_widget_queue_draw(w); return FALSE;
}
static gboolean start_press(GtkWidget *w, GdkEventButton *event) {
    if (event->button < 1 || event->button > 3) return FALSE;
    ((MnwsStart *)w)->pressed = event->button;
    return TRUE;
}
static gboolean start_click(GtkWidget *w, GdkEventButton *event) {
    MnwsStart *s = (MnwsStart *)w;
    if (event->button < 1 || event->button > 3) return FALSE;
    gboolean pressed = s->pressed == event->button;
    s->pressed = FALSE;
    if (!pressed || event->x < 0 || event->y < 0
            || event->x >= gtk_widget_get_allocated_width(w)
            || event->y >= gtk_widget_get_allocated_height(w)) return TRUE;
    const gchar *command = event->button == 3 ? s->right_command : event->button == 2 ? s->middle_command : s->command;
    if (!command || !*command) return TRUE;
    const gchar *argv[] = {"/bin/sh", "-c", command, NULL};
    GError *error = NULL;
    if (!g_spawn_async(NULL, (gchar **)argv, NULL, G_SPAWN_SEARCH_PATH, NULL, NULL, NULL, &error)) {
        g_warning("MNWS start: %s", error->message); g_clear_error(&error);
    }
    return TRUE;
}
static void start_finalize(GObject *obj) {
    MnwsStart *s = (MnwsStart *)obj;
    g_clear_object(&s->normal); g_clear_object(&s->hover);
    g_free(s->command); g_free(s->right_command); g_free(s->middle_command); g_free(s->label);
    G_OBJECT_CLASS(mnws_start_parent_class)->finalize(obj);
}
static void mnws_start_class_init(MnwsStartClass *klass) {
    GtkWidgetClass *w = GTK_WIDGET_CLASS(klass);
    w->get_request_mode=start_request_mode; w->get_preferred_width=start_width;
    w->get_preferred_width_for_height=start_width_for_height; w->get_preferred_height=start_height;
    w->get_preferred_height_for_width=start_height_for_width;
    w->size_allocate=start_allocate; w->draw=start_draw;
    w->enter_notify_event=start_crossing; w->leave_notify_event=start_crossing;
    w->button_press_event=start_press;
    w->button_release_event=start_click;
    G_OBJECT_CLASS(klass)->finalize=start_finalize;
}
static void mnws_start_init(MnwsStart *s) {
    GtkWidget *w=GTK_WIDGET(s);
    gtk_widget_set_name(w,"custom-applauncher");
    gtk_widget_set_valign(w,GTK_ALIGN_FILL);
    gtk_widget_add_events(w,GDK_ENTER_NOTIFY_MASK|GDK_LEAVE_NOTIFY_MASK|GDK_BUTTON_PRESS_MASK|GDK_BUTTON_RELEASE_MASK);
}
