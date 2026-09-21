/* Optional, frame-clock-driven viewport. Never changes CSS or parent geometry
 * from crossing/size-allocation callbacks. Each transition has one tick source. */
typedef struct {
    GtkEventBox parent;
    gboolean revealed, fade, initialized, vertical;
    double width, from_width, target_width, opacity, from_opacity, target_opacity;
    gint64 started;
    guint tick;
} AdwsMotion;
typedef struct { GtkEventBoxClass parent; } AdwsMotionClass;
G_DEFINE_TYPE(AdwsMotion, adws_motion, GTK_TYPE_EVENT_BOX)

#define ADWS_MOTION_DURATION_US 280000

/* cubic-bezier(.4, 0, .2, 1). Solve x(u) for elapsed time before reading
 * y(u); treating time as u would be a different curve. Both ends start/stop
 * gently, rather than spending a quarter of the resize in the first frame. */
static double motion_ease(double t) {
    t = CLAMP(t, 0., 1.);
    if (t == 0. || t == 1.) return t;
    double low = 0., high = 1.;
    for (int i = 0; i < 20; i++) {
        double u = (low + high) / 2.;
        double x = 3. * (1.-u) * (1.-u) * u * .4 + 3. * (1.-u) * u * u * .2 + u*u*u;
        if (x < t) low = u;
        else high = u;
    }
    double u = (low + high) / 2.;
    return 3. * (1.-u) * u*u + u*u*u;
}

static void motion_sample(AdwsMotion *m, gint64 now) {
    double t = CLAMP((now - m->started) / (double)ADWS_MOTION_DURATION_US, 0., 1.);
    double ease = motion_ease(t);
    m->width = m->from_width + (m->target_width - m->from_width) * ease;
    m->opacity = m->from_opacity + (m->target_opacity - m->from_opacity) * ease;
    GtkWidget *child = gtk_bin_get_child(GTK_BIN(m));
    if (child && m->fade) gtk_widget_set_opacity(child, m->opacity);
}

static gboolean motion_tick(GtkWidget *widget, GdkFrameClock *clock, gpointer data) {
    (void)data;
    AdwsMotion *m = (AdwsMotion *)widget;
    gint64 now = gdk_frame_clock_get_frame_time(clock);
    motion_sample(m, now);
    gtk_widget_queue_resize(widget);
    gtk_widget_queue_draw(widget);
    if (now - m->started < ADWS_MOTION_DURATION_US) return G_SOURCE_CONTINUE;
    m->tick = 0;
    GtkWidget *child = gtk_bin_get_child(GTK_BIN(m));
    if (m->fade && !m->revealed && child) gtk_widget_hide(child);
    return G_SOURCE_REMOVE;
}

static void motion_target(AdwsMotion *m, double width, double opacity) {
    if (m->initialized && m->target_width == width && m->target_opacity == opacity) return;
    GtkWidget *widget = GTK_WIDGET(m);
    gboolean enabled = TRUE;
    g_object_get(gtk_widget_get_settings(widget), "gtk-enable-animations", &enabled, NULL);
    GdkFrameClock *clock = gtk_widget_get_frame_clock(widget);
    gint64 now = clock ? gdk_frame_clock_get_frame_time(clock) : 0;
    // Retarget from the last rendered state. Sampling ahead here can jump the
    // width forward before reversing when a new lyric/hover target arrives.
    m->from_width = m->width;
    m->from_opacity = m->opacity;
    m->target_width = width;
    m->target_opacity = opacity;
    m->started = now;
    if (!m->initialized || !enabled || !gtk_widget_get_mapped(widget) || !clock) {
        m->width = width;
        m->opacity = opacity;
        if (m->tick) gtk_widget_remove_tick_callback(widget, m->tick);
        m->tick = 0;
        GtkWidget *child = gtk_bin_get_child(GTK_BIN(m));
        if (child && m->fade) {
            gtk_widget_set_opacity(child, opacity);
            if (!m->revealed) gtk_widget_hide(child);
        }
    } else if (!m->tick) {
        m->tick = gtk_widget_add_tick_callback(widget, motion_tick, NULL, NULL);
    }
    m->initialized = TRUE;
}

static void motion_extent(GtkWidget *widget, int *minimum, int *natural) {
    AdwsMotion *m = (AdwsMotion *)widget;
    int child_min = 0, child_nat = 0;
    GtkWidget *child = gtk_bin_get_child(GTK_BIN(m));
    if (child && m->revealed) {
        if (m->vertical) gtk_widget_get_preferred_height(child, &child_min, &child_nat);
        else gtk_widget_get_preferred_width(child, &child_min, &child_nat);
    }
    motion_target(m, child_nat, m->revealed ? 1. : 0.);
    *minimum = *natural = MAX(0, (int)(m->width + .5));
}

static void motion_width(GtkWidget *widget, int *minimum, int *natural) {
    if (((AdwsMotion *)widget)->vertical)
        GTK_WIDGET_CLASS(adws_motion_parent_class)->get_preferred_width(widget, minimum, natural);
    else motion_extent(widget, minimum, natural);
}
static void motion_height(GtkWidget *widget, int *minimum, int *natural) {
    if (((AdwsMotion *)widget)->vertical) motion_extent(widget, minimum, natural);
    else GTK_WIDGET_CLASS(adws_motion_parent_class)->get_preferred_height(widget, minimum, natural);
}
static void motion_width_for_height(GtkWidget *widget, int height, int *minimum, int *natural) {
    (void)height; motion_width(widget, minimum, natural);
}
static void motion_height_for_width(GtkWidget *widget, int width, int *minimum, int *natural) {
    (void)width; motion_height(widget, minimum, natural);
}

static void motion_allocate(GtkWidget *widget, GtkAllocation *allocation) {
    GtkWidget *child = gtk_bin_get_child(GTK_BIN(widget));
    int minimum = 0, natural = 0;
    gboolean vertical = ((AdwsMotion *)widget)->vertical;
    if (child && gtk_widget_get_visible(child)) {
        if (vertical) gtk_widget_get_preferred_height(child, &minimum, &natural);
        else gtk_widget_get_preferred_width(child, &minimum, &natural);
    }
    // Allocate the child once, at a valid size. Shrink only our clipping window,
    // never a GtkButton below its CSS padding/border minimum.
    GtkAllocation full = *allocation;
    if (vertical) full.height = MAX(full.height, natural);
    else full.width = MAX(full.width, natural);
    GTK_WIDGET_CLASS(adws_motion_parent_class)->size_allocate(widget, &full);
    gtk_widget_set_allocation(widget, allocation);
    gtk_widget_set_clip(widget, allocation);
    if (gtk_widget_get_realized(widget))
        gdk_window_move_resize(gtk_widget_get_window(widget), allocation->x, allocation->y,
                               MAX(1, allocation->width), MAX(1, allocation->height));
}

static gboolean motion_draw(GtkWidget *widget, cairo_t *cr) {
    cairo_save(cr);
    cairo_rectangle(cr, 0, 0, gtk_widget_get_allocated_width(widget), gtk_widget_get_allocated_height(widget));
    cairo_clip(cr);
    gboolean result = GTK_WIDGET_CLASS(adws_motion_parent_class)->draw(widget, cr);
    cairo_restore(cr);
    return result;
}

static void motion_unmap(GtkWidget *widget) {
    AdwsMotion *m = (AdwsMotion *)widget;
    if (m->tick) gtk_widget_remove_tick_callback(widget, m->tick);
    m->tick = 0;
    m->width = m->target_width;
    m->opacity = m->target_opacity;
    GtkWidget *child = gtk_bin_get_child(GTK_BIN(m));
    if (child && m->fade) {
        gtk_widget_set_opacity(child, m->opacity);
        if (!m->revealed) gtk_widget_hide(child);
    }
    GTK_WIDGET_CLASS(adws_motion_parent_class)->unmap(widget);
}

static void adws_motion_class_init(AdwsMotionClass *klass) {
    GtkWidgetClass *widget = GTK_WIDGET_CLASS(klass);
    widget->get_preferred_width = motion_width;
    widget->get_preferred_height = motion_height;
    widget->get_preferred_height_for_width = motion_height_for_width;
    widget->get_preferred_width_for_height = motion_width_for_height;
    widget->size_allocate = motion_allocate;
    widget->draw = motion_draw;
    widget->unmap = motion_unmap;
}
static void adws_motion_init(AdwsMotion *m) {
    m->revealed = TRUE;
    m->opacity = m->target_opacity = 1.;
    gtk_event_box_set_visible_window(GTK_EVENT_BOX(m), TRUE);
}

static GtkWidget *motion_wrap(GtkWidget *child, gboolean fade) {
    AdwsMotion *m = g_object_new(adws_motion_get_type(), NULL);
    m->fade = fade;
    gtk_container_add(GTK_CONTAINER(m), child);
    gtk_widget_show(GTK_WIDGET(m));
    return GTK_WIDGET(m);
}

static void motion_reveal(GtkWidget *widget, gboolean revealed) {
    AdwsMotion *m = (AdwsMotion *)widget;
    if (m->initialized && m->revealed == revealed) return;
    m->revealed = revealed;
    GtkWidget *child = gtk_bin_get_child(GTK_BIN(m));
    gtk_widget_set_sensitive(child, revealed);
    if (revealed) gtk_widget_show(child);
    int minimum, natural;
    motion_extent(widget, &minimum, &natural);
    gtk_widget_queue_resize(widget);
}
