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
    gboolean split;
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
    if (!self->sync) self->sync = g_idle_add(sync_state, self);
}

static void occupancy_changed(GtkWidget *window, gpointer data) {
    (void)window;
    changed(NULL,data);
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
    self->style = g_object_ref(gtk_widget_get_style_context(content));
    self->handler = g_signal_connect(self->style, "changed", G_CALLBACK(changed), self);
    return sync_state(self);
}

const size_t wbcffi_version = 2;
void *wbcffi_init(const wbcffi_init_info *info,
                  const wbcffi_config_entry *entries, size_t count) {

    Space *self = g_new0(Space, 1);
    self->hidden = -1; self->docked=-1; self->duration=280;
    for(size_t i=0;i<count;i++) {
        const char *value=entries[i].value;
        char *clean=g_strstrip(g_strdup(value));
        if(clean[0]=='"' && strlen(clean)>1) { memmove(clean,clean+1,strlen(clean)); clean[strlen(clean)-1]='\0'; }
        if(!strcmp(entries[i].key,"panel_mode"))self->mode=g_strdup(clean);
        else if(!strcmp(entries[i].key,"position"))self->position=g_strdup(clean);
        else if(!strcmp(entries[i].key,"window_animations"))self->animations=!strcmp(clean,"true");
        else if(!strcmp(entries[i].key,"animation_duration"))self->duration=CLAMP(atoi(clean),80,1000);
        else if(!strcmp(entries[i].key,"split_panel"))self->split=!strcmp(clean,"true");
        g_free(clean);
    }
    self->root = GTK_WIDGET(info->get_root_widget(info->obj));
    /* This is a controller, not a visible module; it adds no spacing. */
    gtk_widget_set_no_show_all(self->root, TRUE);
    gtk_widget_hide(self->root);
    self->sync = g_idle_add(attach, self);
    return self;
}

void wbcffi_deinit(void *instance) {
    Space *self = instance;
    stop_animation(self);
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
