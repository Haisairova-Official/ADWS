#include "panel.c"
#include <glib/gstdio.h>

static GtkContainer *root_widget(wbcffi_module *module) { return GTK_CONTAINER(module); }
static void settle(void) {
    for (int i=0;i<40;i++) {
        int count=0;
        while (gtk_events_pending()) { g_assert_cmpint(++count,<,2000); gtk_main_iteration(); }
        g_usleep(1000);
    }
}

int main(int argc, char **argv) {
    gtk_init(&argc,&argv);
    gchar *directory=g_dir_make_tmp("adws-start-instances-XXXXXX",NULL);
    g_assert_nonnull(directory);
    for (int iteration=0;iteration<16;iteration++) {
        GtkWidget *window=gtk_window_new(GTK_WINDOW_TOPLEVEL);
        GtkWidget *bar=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,12);
        gtk_container_add(GTK_CONTAINER(window),bar);
        gtk_widget_set_size_request(bar,-1,36);
        Panel *instances[2];
        gchar *paths[2];
        for (int i=0;i<2;i++) {
            GtkWidget *root=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,0);
            gtk_box_pack_start(GTK_BOX(bar),root,FALSE,FALSE,0);
            paths[i]=g_strdup_printf("%s/%d-%d",directory,iteration,i);
            gchar *quoted=g_shell_quote(paths[i]);
            gchar *command=g_strdup_printf("printf %d > %s",i,quoted);
            JsonNode *node=json_node_new(JSON_NODE_VALUE);
            json_node_set_string(node,command);
            gchar *encoded=json_to_string(node,FALSE);
            wbcffi_init_info info={.obj=(wbcffi_module *)root,.get_root_widget=root_widget};
            wbcffi_config_entry entries[]={
                {"start_image","\"\""},{"start_label",i?"\"Second\"":"\"First\""},
                {"exec",encoded},{"thickness","36"},{"start_animations","true"},
            };
            instances[i]=wbcffi_init(&info,entries,G_N_ELEMENTS(entries));
            json_node_free(node); g_free(encoded); g_free(command); g_free(quoted);
        }
        gtk_widget_show_all(window); settle();
        g_assert_cmpuint(g_list_length(start_widgets),==,2);
        g_assert_cmpstr(((AdwsStart *)instances[0]->start_image)->label,==,"First");
        g_assert_cmpstr(((AdwsStart *)instances[1]->start_image)->label,==,"Second");
        GdkEventButton click={.button=1,.x=2,.y=2};
        // Both buttons receive one complete click, launch separate commands.
        for (int i=0;i<2;i++) {
            start_press(instances[i]->start_image,&click);
            start_click(instances[i]->start_image,&click);
        }
        gint64 deadline=g_get_monotonic_time()+2*G_TIME_SPAN_SECOND;
        while ((!g_file_test(paths[0],G_FILE_TEST_EXISTS)||!g_file_test(paths[1],G_FILE_TEST_EXISTS))
                &&g_get_monotonic_time()<deadline) settle();
        for (int i=0;i<2;i++) {
            gchar *value=NULL;
            g_assert_true(g_file_get_contents(paths[i],&value,NULL,NULL));
            g_assert_cmpstr(value,==,i?"1":"0");
            g_free(value); g_unlink(paths[i]); g_free(paths[i]);
            wbcffi_deinit(instances[i]);
        }
        gtk_widget_destroy(window); settle();
        g_assert_null(start_widgets);
        g_assert_cmpuint(start_bus_owner,==,0);
        g_assert_cmpuint(start_bus_registration,==,0);
    }
    g_rmdir(directory);g_free(directory);
    g_print("Two native Start instances launch independently and release all registrations across 16 cycles.\n");
    return 0;
}
