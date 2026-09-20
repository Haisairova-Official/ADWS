#include "panel.c"

static GtkContainer *root_widget(wbcffi_module *module) { return GTK_CONTAINER(module); }
static void settle(void) {
    for (int i=0;i<100;i++) {
        int count=0;
        while (gtk_events_pending()) {g_assert_cmpint(++count,<,2000);gtk_main_iteration();}
        g_usleep(5000);
    }
}

int main(int argc,char **argv) {
    gtk_init(&argc,&argv);
    for (int animated=0;animated<2;animated++) {
        GtkWidget *window=gtk_offscreen_window_new();
        GtkWidget *root=gtk_box_new(GTK_ORIENTATION_VERTICAL,0);
        gtk_container_add(GTK_CONTAINER(window),root);
        gtk_widget_set_size_request(window,48,-1);
        wbcffi_init_info info={.obj=(wbcffi_module *)root,.get_root_widget=root_widget};
        wbcffi_config_entry entries[]={
            {"exec","\"/usr/bin/sleep 30\""},{"width","0"},{"vertical","true\n"},
            {"animations",animated?"true\n":"false\n"},
            {"previous_command","\"true\""},{"next_command","\"true\""},
        };
        Panel *p=wbcffi_init(&info,entries,G_N_ELEMENTS(entries));
        update(p,"{\"primary\":\"中文歌词 English 123\",\"secondary\":\"双语歌词\"}");
        gtk_widget_show_all(window);settle();
        g_assert_true(p->vertical);
        g_assert_cmpint(pango_context_get_base_gravity(pango_layout_get_context(gtk_label_get_layout(GTK_LABEL(p->primary)))),==,PANGO_GRAVITY_AUTO);
        g_assert_cmpfloat(gtk_label_get_angle(GTK_LABEL(p->primary)),==,270.);
        g_assert_cmpint(gtk_widget_get_allocated_width(window),==,48);
        int minimum,before,after;
        gtk_widget_get_preferred_height(p->event_box,&minimum,&before);
        show_controls(p,TRUE);settle();
        gtk_widget_get_preferred_height(p->event_box,&minimum,&after);
        g_assert_cmpint(after,>,before);
        g_assert_cmpint(gtk_widget_get_allocated_width(window),==,48);
        show_controls(p,FALSE);settle();
        gtk_widget_get_preferred_height(p->event_box,&minimum,&after);
        g_assert_cmpint(after,==,before);
        GdkPixbuf *shot=gtk_offscreen_window_get_pixbuf(GTK_OFFSCREEN_WINDOW(window));
        gdk_pixbuf_save(shot,"/tmp/mnws130-vertical-lyrics.png","png",NULL,NULL);
        g_object_unref(shot);
        wbcffi_deinit(p);gtk_widget_destroy(window);settle();
    }
    GtkWidget *start=g_object_new(mnws_start_get_type(),NULL);
    g_object_ref_sink(start);
    MnwsStart *s=(MnwsStart *)start;s->vertical=TRUE;
    s->normal=gdk_pixbuf_new(GDK_COLORSPACE_RGB,TRUE,8,100,50);
    int minimum,natural;
    start_height_for_width(start,48,&minimum,&natural);
    g_assert_cmpint(natural,==,24);
    gtk_widget_destroy(start);g_object_unref(start);
    g_print("Vertical lyrics, hover transitions and image aspect checks passed\n");
    return 0;
}
