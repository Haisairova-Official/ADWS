#define SPACE_TEST
#include "../src/niri-desktop-layer/integration/waybar-space.c"
static void release_zone(GtkWindow *w){(void)w;}
static GtkWidget *root;
static GtkContainer *get_root(wbcffi_module *obj){(void)obj;return GTK_CONTAINER(root);}
static void pump(void){for(int i=0;i<80;i++){while(g_main_context_iteration(NULL,FALSE));g_usleep(1000);}}
static void check_corners(GtkWidget *window){
 int w=gtk_widget_get_allocated_width(window),h=gtk_widget_get_allocated_height(window);
 cairo_surface_t *surface=cairo_image_surface_create(CAIRO_FORMAT_ARGB32,w,h);cairo_t *cr=cairo_create(surface);
 /* Deliberately dirty the buffer to catch missing clears as well as CSS leaks. */
 cairo_set_source_rgb(cr,0,0,0);cairo_paint(cr);gtk_widget_draw(window,cr);cairo_destroy(cr);cairo_surface_flush(surface);
 unsigned char *pixels=cairo_image_surface_get_data(surface);int stride=cairo_image_surface_get_stride(surface);
 g_assert_cmpint(pixels[1*stride+1*4+3],==,0);
 g_assert_cmpint(pixels[1*stride+(w-2)*4+3],==,0);
 g_assert_cmpint(pixels[(h-2)*stride+1*4+3],==,0);
 g_assert_cmpint(pixels[(h-2)*stride+(w-2)*4+3],==,0);
 g_assert_cmpint(pixels[(h/2)*stride+(w/2)*4+3],>,200);
 cairo_surface_destroy(surface);
}
int main(int argc,char **argv){
 gtk_init(&argc,&argv);
 GtkWidget *window=gtk_window_new(GTK_WINDOW_TOPLEVEL);gtk_widget_set_name(window,"waybar");
 gtk_window_set_default_size(GTK_WINDOW(window),220,60);
 GtkWidget *box=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,0);gtk_container_add(GTK_CONTAINER(window),box);
 root=gtk_event_box_new();gtk_container_add(GTK_CONTAINER(box),root);
 GtkWidget *label=gtk_label_new("ADWS");gtk_container_add(GTK_CONTAINER(box),label);
 GtkCssProvider *hostile=gtk_css_provider_new();
 const char *theme="window#waybar.background {background-color:black;background-image:linear-gradient(black,black);box-shadow:0 0 8px black;} window#waybar > box {background:white;border-radius:22px;} window#waybar.adws-panel.adws-docked > box {border-radius:0;}";
 gtk_css_provider_load_from_data(hostile,theme,-1,NULL);
 gtk_style_context_add_provider_for_screen(gtk_widget_get_screen(window),GTK_STYLE_PROVIDER(hostile),GTK_STYLE_PROVIDER_PRIORITY_USER);
 wbcffi_init_info info={.get_root_widget=get_root};
 wbcffi_config_entry config[]={{"panel_mode","auto"}};Space *s=wbcffi_init(&info,config,1);
 gtk_widget_show_all(window);pump();
 GtkStyleContext *style=gtk_widget_get_style_context(window);
 for(int cycle=0;cycle<8;cycle++) {
  if(cycle%2)gtk_style_context_add_class(style,"adws-has-windows");
  else gtk_style_context_remove_class(style,"adws-has-windows");
  g_signal_emit_by_name(window,"adws-windows-changed");pump();
  g_assert_cmpint(s->docked,==,cycle%2);
  g_assert_false(gtk_style_context_has_class(style,"adws-docked"));
  /* A theme refresh must not expose the opaque outer surface or re-enable
   * the old docked-radius override, even with an existing user stylesheet. */
  gtk_css_provider_load_from_data(hostile,theme,-1,NULL);pump();
  check_corners(window);
 }
 wbcffi_deinit(s);gtk_widget_destroy(window);g_object_unref(hostile);
 g_print("PASS: all four corners remain transparent across 8 docking transitions and opaque theme reloads\n");return 0;
}
