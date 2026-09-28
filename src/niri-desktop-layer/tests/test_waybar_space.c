/* Real GTK style changes; replace only the Wayland exclusive-zone operation. */
#define SPACE_TEST
#include "../integration/waybar-space.c"
static int releases;
static void release_zone(GtkWindow *window) { (void)window; releases++; }
static GtkWidget *root;
static GtkContainer *get_root(wbcffi_module *obj) { (void)obj; return GTK_CONTAINER(root); }
static void drain(int ms) {
    gint64 until = g_get_monotonic_time() + ms * 1000;
    do {
        while (g_main_context_iteration(NULL, FALSE));
        g_usleep(1000);
    } while (g_get_monotonic_time() < until);
}
int main(int argc, char **argv) {
    gtk_init(&argc, &argv);
    GtkWidget *window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_container_add(GTK_CONTAINER(window), box);
    gtk_container_add(GTK_CONTAINER(box), gtk_label_new("Test"));
    root = gtk_event_box_new();
    gtk_container_add(GTK_CONTAINER(box), root);
    GtkCssProvider *css = gtk_css_provider_new();
    gtk_css_provider_load_from_data(css, "window > box { opacity: 1; transition: opacity 220ms ease-in-out; } window.mode-invisible > box { opacity: 0; }", -1, NULL);
    gtk_style_context_add_provider_for_screen(gtk_widget_get_screen(window), GTK_STYLE_PROVIDER(css), 800);
    wbcffi_init_info info = { .get_root_widget = get_root };
    Space *self = wbcffi_init(&info, NULL, 0);
    gtk_widget_show_all(window);
    drain(50);
    g_assert_false(gtk_widget_get_visible(root));
    GtkStyleContext *style = gtk_widget_get_style_context(window);
    gtk_style_context_add_class(style, "mode-invisible");
    drain(100);
    g_assert_cmpint(releases, ==, 0);
    g_assert_cmpuint(self->release, >, 0);
    gtk_style_context_remove_class(style, "mode-invisible");
    drain(300);
    g_assert_cmpint(releases, ==, 0);
    g_assert_cmpuint(self->release, ==, 0);
    gtk_style_context_add_class(style, "mode-invisible");
    drain(300);
    g_assert_cmpint(releases, ==, 1);
    drain(100);
    g_assert_cmpuint(self->sync, ==, 0);
    g_assert_cmpuint(self->release, ==, 0);
    wbcffi_deinit(self);
    /* Starting hidden must not leave an empty reserved strip. */
    self = wbcffi_init(&info, NULL, 0);
    drain(40);
    g_assert_cmpint(releases, ==, 2);
    gtk_style_context_remove_class(style, "mode-invisible");
    drain(40);
    gtk_style_context_add_class(style, "mode-invisible");
    drain(40);
    wbcffi_deinit(self);
    drain(300);
    g_assert_cmpint(releases, ==, 2);
    gtk_style_context_remove_class(style,"mode-invisible");
    wbcffi_config_entry entries[]={{"panel_mode","auto"},{"split_panel","true"},{"position","bottom"}};
    self=wbcffi_init(&info,entries,3);
    drain(50);
    g_assert_true(gtk_style_context_has_class(style,"adws-split"));
    g_assert_false(gtk_style_context_has_class(style,"adws-docked"));
    gtk_style_context_add_class(style,"adws-has-windows");g_signal_emit_by_name(window,"adws-windows-changed");drain(50);
    g_assert_true(gtk_style_context_has_class(style,"adws-docked"));
    gtk_style_context_remove_class(style,"adws-has-windows");g_signal_emit_by_name(window,"adws-windows-changed");drain(50);
    g_assert_false(gtk_style_context_has_class(style,"adws-docked"));
    g_assert_cmpuint(self->sync,==,0);
    wbcffi_deinit(self);
    wbcffi_config_entry animated[]={{"panel_mode","auto"},{"position","bottom"},{"window_animations","true"},{"animation_duration","200"}};
    self=wbcffi_init(&info,animated,4);drain(30);
    g_assert_cmpfloat(self->gap,==,8.);
    gtk_style_context_add_class(style,"adws-has-windows");g_signal_emit_by_name(window,"adws-windows-changed");drain(90);
    g_assert_true(self->gap>0. && self->gap<8.);
    gtk_style_context_remove_class(style,"adws-has-windows");g_signal_emit_by_name(window,"adws-windows-changed");drain(250);
    g_assert_cmpfloat(self->gap,==,8.);g_assert_cmpuint(self->animation,==,0);
    gtk_style_context_add_class(style,"adws-has-windows");g_signal_emit_by_name(window,"adws-windows-changed");drain(250);
    g_assert_cmpfloat(self->gap,==,0.);
    wbcffi_deinit(self);
    GtkWidget *center=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,0);
    gtk_widget_set_name(center,"cliptest");
    gtk_widget_get_style_context(center);
    gtk_widget_set_size_request(center,160,36);
    gtk_box_set_center_widget(GTK_BOX(box),center);
    gtk_container_add(GTK_CONTAINER(center),gtk_label_new("Lyrics"));
    gtk_css_provider_load_from_data(css,"#cliptest {background:#ff0000; border-radius:0; padding:0 23px;}",-1,NULL);
    wbcffi_config_entry pointed[]={{"split_panel","true"},{"split_center_corners","pointed"},{"position","bottom"},{"thickness","36"}};
    self=wbcffi_init(&info,pointed,4);gtk_widget_show_all(window);drain(60);
    g_assert_true(self->segments[1]==center);
    int width=gtk_widget_get_allocated_width(center),height=gtk_widget_get_allocated_height(center);
    cairo_surface_t *surface=cairo_image_surface_create(CAIRO_FORMAT_ARGB32,width,height);
    cairo_t *cr=cairo_create(surface);gtk_widget_draw(center,cr);cairo_destroy(cr);cairo_surface_flush(surface);
    unsigned char *pixels=cairo_image_surface_get_data(surface);int stride=cairo_image_surface_get_stride(surface);
    g_assert_cmpint(pixels[stride+4+3],==,0); /* transparent cut corner */
    g_assert_cmpint(pixels[(height/2)*stride+4+3],>,200); /* visible point */
    g_assert_cmpint(pixels[stride+24*4+3],>,200); /* protected content rectangle */
    cairo_surface_write_to_png(surface,"/tmp/adws-center-pointed.png");cairo_surface_destroy(surface);
    wbcffi_deinit(self);
    GtkWidget *front=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,0),*back=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,0);
    gtk_style_context_add_class(gtk_widget_get_style_context(front),"modules-left");
    gtk_style_context_add_class(gtk_widget_get_style_context(back),"modules-right");
    gtk_widget_set_size_request(front,160,36);gtk_widget_set_size_request(back,160,36);
    gtk_box_pack_start(GTK_BOX(box),front,FALSE,FALSE,0);gtk_box_pack_end(GTK_BOX(box),back,FALSE,FALSE,0);
    gtk_css_provider_load_from_data(css,".modules-left,.modules-right {background:#ff0000; border-radius:0;}",-1,NULL);
    wbcffi_config_entry docked_pointed[]={{"split_panel","true"},{"split_center_corners","pointed"},{"position","bottom"},{"thickness","36"},{"panel_mode","docked"}};
    self=wbcffi_init(&info,docked_pointed,5);gtk_widget_show_all(window);drain(60);
    g_assert_true(self->segments[0]==front);g_assert_true(self->segments[2]==back);
    for(int index=0;index<2;index++) {
        GtkWidget *segment=index?back:front;
        width=gtk_widget_get_allocated_width(segment);height=gtk_widget_get_allocated_height(segment);
        surface=cairo_image_surface_create(CAIRO_FORMAT_ARGB32,width,height);cr=cairo_create(surface);
        gtk_widget_draw(segment,cr);cairo_destroy(cr);cairo_surface_flush(surface);
        pixels=cairo_image_surface_get_data(surface);stride=cairo_image_surface_get_stride(surface);
        int outside=index?width-2:1, inside=index?1:width-2;
        g_assert_cmpint(pixels[stride+outside*4+3],>,200); /* outside edge remains flat */
        g_assert_cmpint(pixels[stride+inside*4+3],==,0); /* inside stays pointed while docked */
        g_assert_cmpint(pixels[(height/2)*stride+inside*4+3],>,200);
        cairo_surface_destroy(surface);
    }
    wbcffi_deinit(self);
    /* Both orientations contain the tip and leave corners outside the polygon. */
    for(int vertical=0;vertical<2;vertical++) {
        surface=cairo_image_surface_create(CAIRO_FORMAT_ARGB32,200,200);cr=cairo_create(surface);
        segment_path(cr,vertical?36:160,vertical?160:36,vertical,18,TRUE,TRUE);
        g_assert_false(cairo_in_fill(cr,1,1));
        g_assert_true(cairo_in_fill(cr,vertical?18:1,vertical?1:18));
        g_assert_true(cairo_in_fill(cr,vertical?1:23,vertical?23:1));
        cairo_destroy(cr);cairo_surface_destroy(surface);
    }
    gtk_widget_destroy(window);
    g_print("PASS: deferred release, reversal, hidden startup, teardown, idle cleanup\n");
}
