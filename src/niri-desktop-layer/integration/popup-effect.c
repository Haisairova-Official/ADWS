/* ADWS popup blur regions. Protocol: ext-background-effect-v1 (version 1).
 * This shares GDK's connection; never creates a second Wayland surface.
 * Only GTK3 callers own an effect on these surfaces. No compositor config edits.
 */
#include <gdk/gdkwayland.h>
#include <wayland-client.h>

static const struct wl_interface adws_effect_interface;
static const struct wl_interface *adws_effect_get_types[] = {
    &adws_effect_interface, &wl_surface_interface
};
static const struct wl_interface *adws_effect_region_types[] = { &wl_region_interface };
static const struct wl_message adws_effect_requests[] = {
    { "destroy", "", NULL }, { "set_blur_region", "?o", adws_effect_region_types }
};
static const struct wl_interface adws_effect_interface = {
    "ext_background_effect_surface_v1", 1, 2, adws_effect_requests, 0, NULL
};
static const struct wl_message adws_effect_manager_requests[] = {
    { "destroy", "", NULL }, { "get_background_effect", "no", adws_effect_get_types }
};
static const struct wl_message adws_effect_manager_events[] = { { "capabilities", "u", NULL } };
static const struct wl_interface adws_effect_manager_interface = {
    "ext_background_effect_manager_v1", 1, 2, adws_effect_manager_requests,
    1, adws_effect_manager_events
};
typedef struct {
    struct wl_proxy *manager;
    struct wl_compositor *compositor;
    struct wl_event_queue *queue;
    uint32_t capabilities;
} AdwsEffectFactory;
typedef struct {
    struct wl_proxy *effect;
    AdwsEffectFactory *factory;
} AdwsPopupEffect;

static void adws_effect_caps(void *data, struct wl_proxy *proxy, uint32_t flags) {
    (void)proxy;
    ((AdwsEffectFactory *)data)->capabilities = flags;
}
static void (*adws_effect_listener[])(void) = { (void (*)(void))adws_effect_caps };
static void adws_effect_global(void *data, struct wl_registry *registry,
                               uint32_t name, const char *interface, uint32_t version) {
    (void)version;
    AdwsEffectFactory *f = data;
    if (!f->manager && !strcmp(interface, adws_effect_manager_interface.name)) {
        f->manager = wl_registry_bind(registry, name, &adws_effect_manager_interface, 1);
        wl_proxy_set_queue(f->manager, f->queue);
        wl_proxy_add_listener(f->manager, adws_effect_listener, f);
    } else if (!f->compositor && !strcmp(interface, "wl_compositor")) {
        f->compositor = wl_registry_bind(registry, name, &wl_compositor_interface, 1);
        wl_proxy_set_queue((struct wl_proxy *)f->compositor, f->queue);
    }
}
static void adws_effect_global_remove(void *data, struct wl_registry *registry, uint32_t name) {
    (void)data; (void)registry; (void)name;
}
static const struct wl_registry_listener adws_effect_registry_listener = {
    adws_effect_global, adws_effect_global_remove
};
static void adws_effect_factory_free(void *data) {
    AdwsEffectFactory *f = data;
    if (f->manager) {
        wl_proxy_marshal(f->manager, 0);
        wl_proxy_destroy(f->manager);
    }
    if (f->compositor) wl_compositor_destroy(f->compositor);
    g_free(f);
}

/* NULL is a supported fallback: X11, older compositor, or unavailable blur. */
void *adws_popup_effect_create(GdkWindow *window) {
    if (!GDK_IS_WAYLAND_WINDOW(window)) return NULL;
    GdkDisplay *display = gdk_window_get_display(window);
    AdwsEffectFactory *f = g_object_get_data(G_OBJECT(display), "adws-popup-effect-factory");
    if (!f) {
        f = g_new0(AdwsEffectFactory, 1);
        struct wl_display *wl = gdk_wayland_display_get_wl_display(display);
        f->queue = wl_display_create_queue(wl);
        struct wl_registry *registry = wl_display_get_registry(wl);
        wl_proxy_set_queue((struct wl_proxy *)registry, f->queue);
        wl_registry_add_listener(registry, &adws_effect_registry_listener, f);
        /* Discover once per display, outside animation callbacks. The private
         * queue avoids re-entering GDK while constructing the popup. */
        int result = wl_display_roundtrip_queue(wl, f->queue);
        if (result >= 0) result = wl_display_roundtrip_queue(wl, f->queue);
        if (result < 0) f->capabilities = 0;
        if (f->manager) wl_proxy_set_queue(f->manager, NULL);
        if (f->compositor) wl_proxy_set_queue((struct wl_proxy *)f->compositor, NULL);
        wl_registry_destroy(registry);
        wl_event_queue_destroy(f->queue); f->queue = NULL;
        g_object_set_data_full(G_OBJECT(display), "adws-popup-effect-factory", f, adws_effect_factory_free);
    }
    if (!f->manager || !f->compositor || !(f->capabilities & 1)) return NULL;
    struct wl_surface *surface = gdk_wayland_window_get_wl_surface(window);
    if (!surface) return NULL;
    AdwsPopupEffect *effect = g_new0(AdwsPopupEffect, 1);
    effect->factory = f;
    effect->effect = wl_proxy_marshal_constructor(f->manager, 1, &adws_effect_interface, NULL, surface);
    return effect;
}

void adws_popup_effect_region(void *data, int x, int y, int width, int height, int radius) {
    AdwsPopupEffect *effect = data;
    if (!effect) return;
    struct wl_region *region = wl_compositor_create_region(effect->factory->compositor);
    if (width > 0 && height > 0) {
        radius = MAX(0, MIN(radius, MIN(width, height) / 2));
        if (height > 2 * radius)
            wl_region_add(region, x, y + radius, width, height - 2 * radius);
        if (radius && width > 2 * radius) {
            /* Keep the blur inside the rounded silhouette using three broad
             * bands. Pixel-row circles fragment compositor damage into many
             * tiny regions and repeatedly run the blur pass at high refresh
             * rates. GTK still paints the exact rounded border and fill. */
            wl_region_add(region, x + radius, y, width - 2 * radius, radius);
            wl_region_add(region, x + radius, y + height - radius, width - 2 * radius, radius);
        }
    }
    wl_proxy_marshal(effect->effect, 1, region);
    wl_region_destroy(region);
    /* The next GTK buffer commit atomically applies pixels and blur region. */
}

void adws_popup_effect_destroy(void *data) {
    AdwsPopupEffect *effect = data;
    if (!effect) return;
    wl_proxy_marshal(effect->effect, 0);
    wl_proxy_destroy(effect->effect);
    g_free(effect);
}
