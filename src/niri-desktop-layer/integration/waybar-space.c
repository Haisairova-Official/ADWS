/* Waybar CFFI v2: retain the exclusive zone until the CSS fade completes.
 * ABI: Waybar 0.15.0 include/modules/cffi.hpp. No worker thread or polling.
 */
#include <gtk/gtk.h>
#include <gtk-layer-shell.h>

typedef struct wbcffi_module wbcffi_module;
typedef struct {
    wbcffi_module *obj;
    const char *waybar_version;
    GtkContainer *(*get_root_widget)(wbcffi_module *);
    void (*queue_update)(wbcffi_module *);
} wbcffi_init_info;
typedef struct { const char *key, *value; } wbcffi_config_entry;

typedef struct {
    GtkWidget *root;
    GtkWindow *window;
    GtkStyleContext *style;
    gulong handler;
    guint sync, release;
    int hidden, docked;
    guint animation;
    gint64 animation_start;
    double gap, from_gap, target_gap;
    gboolean animations;
    int duration;
    gulong occupancy_handler;
    gboolean split, pointed;
    GtkWidget *segments[3];
    gulong segment_draw[3];
    int thickness;
    char *mode, *position;
    GtkStyleContext *window_style;
    gulong window_handler;
} Space;

#ifdef SPACE_TEST
static void release_zone(GtkWindow *window);
#else
static void release_zone(GtkWindow *window) {
    gtk_layer_set_exclusive_zone(window, 0);
    gtk_layer_try_force_commit(window);
}
#endif

static void cancel(guint *source) {
    if (*source) { g_source_remove(*source); *source = 0; }
}

static gboolean release_space(gpointer data) {
    Space *self = data;
    self->release = 0;
    if (self->window && gtk_style_context_has_class(gtk_widget_get_style_context(GTK_WIDGET(self->window)), "mode-invisible"))
        release_zone(self->window);
    return G_SOURCE_REMOVE;
}

static void apply_gap(Space *self, double gap) {
    self->gap=gap;
#ifndef SPACE_TEST
    if(self->window && gtk_layer_is_layer_window(self->window)) {
        GtkLayerShellEdge inward=g_strcmp0(self->position,"top")==0?GTK_LAYER_SHELL_EDGE_BOTTOM:g_strcmp0(self->position,"left")==0?GTK_LAYER_SHELL_EDGE_RIGHT:g_strcmp0(self->position,"right")==0?GTK_LAYER_SHELL_EDGE_LEFT:GTK_LAYER_SHELL_EDGE_TOP;
        for(int edge=0;edge<4;edge++) gtk_layer_set_margin(self->window,edge,edge==(int)inward?0:(int)(gap+0.5));
        /* A margin-only change may leave an otherwise idle surface without a
         * frame. Schedule damage and commit instead of waiting for a clock or
         * plugin update to finish initial placement. */
        gtk_widget_queue_draw(GTK_WIDGET(self->window));
        gtk_layer_try_force_commit(self->window);
    }
#endif
}
static gboolean animate_gap(GtkWidget *widget, GdkFrameClock *clock, gpointer data) {
    (void)widget;
    Space *self=data;
    double t=CLAMP((gdk_frame_clock_get_frame_time(clock)-self->animation_start)/(self->duration*1000.0),0.,1.);
    double eased=t*t*(3.-2.*t);
    apply_gap(self,self->from_gap+(self->target_gap-self->from_gap)*eased);
    if(t>=1.) {self->animation=0;return G_SOURCE_REMOVE;}
    return G_SOURCE_CONTINUE;
}
static void stop_animation(Space *self) {
    if(self->animation && self->window)gtk_widget_remove_tick_callback(GTK_WIDGET(self->window),self->animation);
    self->animation=0;
}

static gboolean sync_state(gpointer data) {
    Space *self = data;
    self->sync = 0;
    if (!self->window) return G_SOURCE_REMOVE;
    GtkStyleContext *style=gtk_widget_get_style_context(GTK_WIDGET(self->window));
    gboolean docked=g_strcmp0(self->mode,"docked")==0 || (g_strcmp0(self->mode,"auto")==0 && gtk_style_context_has_class(style,"adws-has-windows"));
    if (self->docked != docked) {
        gboolean initial=self->docked<0;
        if(g_getenv("ADWS_TASKBAR_TIMING"))g_printerr("ADWS_TASKBAR_TIMING space_dock=%d at_us=%lld\n",docked,(long long)g_get_monotonic_time());
        self->docked=docked;
        if(docked) gtk_style_context_add_class(style,"adws-docked"); else gtk_style_context_remove_class(style,"adws-docked");
        stop_animation(self);
        self->target_gap=docked?0.:8.;
        if(!initial && self->animations && gtk_widget_get_mapped(GTK_WIDGET(self->window))) {
            self->from_gap=self->gap;
            self->animation_start=g_get_monotonic_time();
            self->animation=gtk_widget_add_tick_callback(GTK_WIDGET(self->window),animate_gap,self,NULL);
        } else apply_gap(self,self->target_gap);
    }
    int hidden = gtk_style_context_has_class(gtk_widget_get_style_context(GTK_WIDGET(self->window)), "mode-invisible");
    if (hidden == self->hidden) return G_SOURCE_REMOVE;
    cancel(&self->release);
    if (hidden) {
        if (self->hidden < 0) release_zone(self->window);
        else self->release = g_timeout_add(240, release_space, self);
    }
    /* The normal Waybar mode restores automatic reservation before fade-in. */
    self->hidden = hidden;
    return G_SOURCE_REMOVE;
}

static void changed(GtkStyleContext *style, gpointer data) {
    (void)style;
    Space *self = data;
    /* Defer until Waybar has finished applying the new mode. */
    if (!self->sync) self->sync = g_idle_add_full(G_PRIORITY_HIGH_IDLE, sync_state, self, NULL);
}

static void occupancy_changed(GtkWidget *window, gpointer data) {
    (void)window;
    changed(NULL,data);
}
/* Clip the segment's normal CSS rendering, preserving materials and live colors.
 * Invoke the class renderer inside our clip; GTK restores Cairo between signal
 * handlers, so returning FALSE here would lose the polygon before default draw. */
static void segment_path(cairo_t *cr, double w, double h, gboolean vertical, double tip, gboolean front, gboolean back) {
    tip=MIN(tip,(vertical?h:w)/2.);
    double start=front?tip:0, end=back?tip:0;
    if(vertical) {
        cairo_move_to(cr,front?w/2.:0,0); cairo_line_to(cr,w,start);
        cairo_line_to(cr,w,h-end); cairo_line_to(cr,back?w/2.:w,h);
        cairo_line_to(cr,0,h-end); cairo_line_to(cr,0,start);
    } else {
        cairo_move_to(cr,0,front?h/2.:0); cairo_line_to(cr,start,0);
        cairo_line_to(cr,w-end,0); cairo_line_to(cr,w,back?h/2.:0);
        cairo_line_to(cr,w-end,h); cairo_line_to(cr,start,h);
        cairo_line_to(cr,0,front?h/2.:h);
    }
    cairo_close_path(cr);
}
static gboolean draw_segment(GtkWidget *widget, cairo_t *cr, gpointer data) {
    Space *self=data;
    gboolean vertical=g_strcmp0(self->position,"left")==0 || g_strcmp0(self->position,"right")==0;
    segment_path(cr,gtk_widget_get_allocated_width(widget),gtk_widget_get_allocated_height(widget),vertical,self->thickness/2.,widget!=self->segments[0],widget!=self->segments[2]);
    cairo_clip(cr);
    GTK_WIDGET_GET_CLASS(widget)->draw(widget,cr);
    return TRUE;
}
static gboolean attach(gpointer data) {
    Space *self = data;
    self->sync = 0;
    GtkWidget *top = gtk_widget_get_toplevel(self->root);
    if (!GTK_IS_WINDOW(top)) return G_SOURCE_REMOVE;
    self->window = GTK_WINDOW(top);
    self->window_style=g_object_ref(gtk_widget_get_style_context(top));
    gtk_style_context_add_class(self->window_style,"adws-panel");
    if(self->split)gtk_style_context_add_class(self->window_style,"adws-split");
    /* A CSS class with no direct selector need not emit style::changed.
     * Consume an explicit occupancy signal instead of relying on theme invalidation. */
    if(!g_signal_lookup("adws-windows-changed",GTK_TYPE_WINDOW))
        g_signal_new("adws-windows-changed",GTK_TYPE_WINDOW,G_SIGNAL_RUN_LAST,0,NULL,NULL,NULL,G_TYPE_NONE,0);
    self->occupancy_handler=g_signal_connect(top,"adws-windows-changed",G_CALLBACK(occupancy_changed),self);
    self->window_handler=g_signal_connect(self->window_style,"changed",G_CALLBACK(changed),self);
    g_object_add_weak_pointer(G_OBJECT(top), (gpointer *)&self->window);
    /* The content box opacity actually changes; the window style may not. */
    GtkWidget *content = gtk_bin_get_child(GTK_BIN(top));
    if(self->split && self->pointed && GTK_IS_BOX(content)) {
        const char *classes[]={"modules-left","modules-center","modules-right"};
        GList *children=gtk_container_get_children(GTK_CONTAINER(content));
        for(GList *it=children;it;it=it->next) {
            GtkWidget *child=it->data;
            GtkStyleContext *ctx=gtk_widget_get_style_context(child);
            for(int i=0;i<3;i++) {
                if(gtk_style_context_has_class(ctx,classes[i]) || (i==1 && child==gtk_box_get_center_widget(GTK_BOX(content)))) {
                    self->segments[i]=child;
                    g_object_add_weak_pointer(G_OBJECT(child),(gpointer *)&self->segments[i]);
                    self->segment_draw[i]=g_signal_connect(child,"draw",G_CALLBACK(draw_segment),self);
                    gtk_widget_queue_draw(child);
                    break;
                }
            }
        }
        g_list_free(children);
    }
    self->style = g_object_ref(gtk_widget_get_style_context(content));
    self->handler = g_signal_connect(self->style, "changed", G_CALLBACK(changed), self);
    return sync_state(self);
}

const size_t wbcffi_version = 2;
void *wbcffi_init(const wbcffi_init_info *info,
                  const wbcffi_config_entry *entries, size_t count) {

    Space *self = g_new0(Space, 1);
    if(g_getenv("ADWS_TASKBAR_TIMING"))g_printerr("ADWS_TASKBAR_TIMING space_init_us=%lld\n",(long long)g_get_monotonic_time());
    self->hidden = -1; self->docked=-1; self->duration=280; self->thickness=36;
    for(size_t i=0;i<count;i++) {
        const char *value=entries[i].value;
        char *clean=g_strstrip(g_strdup(value));
        if(clean[0]=='"' && strlen(clean)>1) { memmove(clean,clean+1,strlen(clean)); clean[strlen(clean)-1]='\0'; }
        if(!strcmp(entries[i].key,"panel_mode"))self->mode=g_strdup(clean);
        else if(!strcmp(entries[i].key,"position"))self->position=g_strdup(clean);
        else if(!strcmp(entries[i].key,"window_animations"))self->animations=!strcmp(clean,"true");
        else if(!strcmp(entries[i].key,"animation_duration"))self->duration=CLAMP(atoi(clean),80,1000);
        else if(!strcmp(entries[i].key,"split_center_corners"))self->pointed=!strcmp(clean,"pointed");
        else if(!strcmp(entries[i].key,"thickness"))self->thickness=CLAMP(atoi(clean),24,160);
        else if(!strcmp(entries[i].key,"split_panel"))self->split=!strcmp(clean,"true");
        g_free(clean);
    }
    self->root = GTK_WIDGET(info->get_root_widget(info->obj));
    /* This is a controller, not a visible module; it adds no spacing. */
    gtk_widget_set_no_show_all(self->root, TRUE);
    gtk_widget_hide(self->root);
    self->sync = g_idle_add_full(G_PRIORITY_HIGH_IDLE, attach, self, NULL);
    return self;
}

void wbcffi_deinit(void *instance) {
    Space *self = instance;
    stop_animation(self);
    for(int i=0;i<3;i++) if(self->segments[i]) {
        if(self->segment_draw[i])g_signal_handler_disconnect(self->segments[i],self->segment_draw[i]);
        g_object_remove_weak_pointer(G_OBJECT(self->segments[i]),(gpointer *)&self->segments[i]);
    }
    if(self->window && self->occupancy_handler)g_signal_handler_disconnect(self->window,self->occupancy_handler);
    cancel(&self->sync);
    cancel(&self->release);
    if (self->style) {
        g_signal_handler_disconnect(self->style, self->handler);
        g_object_unref(self->style);
    }
    if(self->window_style) {g_signal_handler_disconnect(self->window_style,self->window_handler);g_object_unref(self->window_style);}
    g_free(self->mode);g_free(self->position);
    if (self->window)
        g_object_remove_weak_pointer(G_OBJECT(self->window), (gpointer *)&self->window);
    g_free(self);
}
